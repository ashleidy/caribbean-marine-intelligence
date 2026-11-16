"""NOAA National Hurricane Center (NHC) client.

Official products used (see https://www.nhc.noaa.gov/gis/):

* ``CurrentStorms.json``  - machine-readable status of every active cyclone
  (documented in "NHC Tropical Cyclone Status JSON File Reference"). Units per
  the documentation: intensity = knots, pressure = mb, movementSpeed = mph,
  movementDir = degrees from north.
* Advisory GIS zip files linked from that JSON (5-day forecast track, cone of
  uncertainty, wind watches/warnings, wind radii, preliminary best track).
* HURDAT2 - final best-track archive (text); the file name changes with every
  release, so the latest one is discovered from the NHC index page.

Everything returned here is *official NHC data*. Derived quantities
(distances, trends...) live in ``analytics/cyclones.py`` and are labelled as
computed by this app.
"""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from services.base import DataValidationError, SourceError, get_logger, http_get, http_get_json
from utils.config import RAW_DIR
from utils.formatting import CLASSIFICATION_LABELS, MPH_TO_KT

try:  # GeoPandas is only needed for shapefile products; JSON/HURDAT work without it
    import geopandas as gpd

    HAS_GEO = True
except Exception:  # pragma: no cover
    gpd = None
    HAS_GEO = False

log = get_logger("noaa_nhc")

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
HURDAT_INDEX_URLS = ("https://www.nhc.noaa.gov/data/hurdat/", "https://www.nhc.noaa.gov/data/")
HURDAT_BASE_URL = "https://www.nhc.noaa.gov/data/hurdat/"
MAX_ZIP_BYTES = 60 * 1024 * 1024

# Official NHC watch/warning codes (TCWW attribute of the advisory shapefile)
WW_LABELS = {
    "HWR": "Hurricane Warning", "HWA": "Hurricane Watch",
    "TWR": "Tropical Storm Warning", "TWA": "Tropical Storm Watch",
    "SSR": "Storm Surge Warning", "SSA": "Storm Surge Watch",
}
WW_COLORS = {  # NHC convention: red / pink / blue / yellow
    "HWR": [255, 59, 59, 230], "HWA": [255, 130, 190, 230],
    "TWR": [56, 130, 255, 230], "TWA": [255, 220, 60, 230],
    "SSR": [199, 125, 255, 230], "SSA": [230, 190, 255, 230],
}


# --------------------------------------------------------------------------- #
# Active storms (CurrentStorms.json)
# --------------------------------------------------------------------------- #
def _nested(d: dict, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _coord_value(numeric, text) -> float:
    """Numeric field first; fall back to the text form ('21.3N', '75.4W') so a storm is never plotted at (0, 0)."""
    val = pd.to_numeric(numeric, errors="coerce")
    if pd.notna(val):
        return float(val)
    try:
        t = str(text).strip().upper()
        return float(t[:-1]) * (-1 if t[-1] in "SW" else 1)
    except (ValueError, IndexError):
        return float("nan")


def fetch_active_storms() -> pd.DataFrame:
    """One row per active cyclone (Atlantic, East & Central Pacific). Empty frame = none active."""
    payload = http_get_json(CURRENT_STORMS_URL)
    if not isinstance(payload, dict) or "activeStorms" not in payload:
        raise DataValidationError("NHC CurrentStorms.json: missing 'activeStorms'")
    rows = []
    for s in payload["activeStorms"]:
        sid = str(s.get("id", "")).lower()
        rows.append({
            "id": sid,
            "basin": {"al": "Atlantic", "ep": "East Pacific", "cp": "Central Pacific"}.get(sid[:2], sid[:2].upper()),
            "name": s.get("name"),
            "classification": s.get("classification"),
            "classification_label": CLASSIFICATION_LABELS.get(s.get("classification"), s.get("classification")),
            "intensity_kt": pd.to_numeric(s.get("intensity"), errors="coerce"),
            "pressure_mb": pd.to_numeric(s.get("pressure"), errors="coerce"),
            "lat": _coord_value(s.get("latitude_numeric"), s.get("latitude")),
            "lon": _coord_value(s.get("longitude_numeric"), s.get("longitude")),
            "movement_dir_deg": pd.to_numeric(s.get("movementDir"), errors="coerce"),
            "movement_speed_mph": pd.to_numeric(s.get("movementSpeed"), errors="coerce"),
            "last_update": pd.to_datetime(s.get("lastUpdate"), utc=True, errors="coerce"),
            "advisory_number": _nested(s, "publicAdvisory", "advNum"),
            "public_advisory_url": _nested(s, "publicAdvisory", "url"),
            "forecast_advisory_url": _nested(s, "forecastAdvisory", "url"),
            "discussion_url": _nested(s, "forecastDiscussion", "url"),
            "graphics_url": _nested(s, "forecastGraphics", "url"),
            "forecast_zip": _nested(s, "forecastTrack", "zipFile"),
            "cone_zip": _nested(s, "trackCone", "zipFile"),
            "warnings_zip": _nested(s, "windWatchesWarnings", "zipFile"),
            "initial_wind_zip": _nested(s, "initialWindExtent", "zipFile"),
            "forecast_radii_zip": _nested(s, "forecastWindRadiiGIS", "zipFile"),
            "best_track_zip": _nested(s, "bestTrackGIS", "zipFile"),
            "surge_ww_kml": _nested(s, "stormSurgeWatchWarningGIS", "kmlFile"),
            "surge_flooding_zip": _nested(s, "potentialStormSurgeFloodingGIS", "zipFile"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        bad = df["lat"].isna() | df["lon"].isna()
        if bad.any():
            log.warning("Dropping %d active storm(s) without coordinates: %s", int(bad.sum()), list(df.loc[bad, "name"]))
            df = df[~bad].reset_index(drop=True)
    if not df.empty:
        df["movement_speed_kt"] = df["movement_speed_mph"] * MPH_TO_KT
    return df


# --------------------------------------------------------------------------- #
# Advisory shapefile packages
# --------------------------------------------------------------------------- #
def _col(gdf, *candidates):
    """Case-insensitive column lookup."""
    lower = {c.lower(): c for c in gdf.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def read_zip_shapefiles(url: str) -> dict:
    """Download an NHC zip and return {shapefile_stem: GeoDataFrame (EPSG:4326)}."""
    if not HAS_GEO:
        raise SourceError("GeoPandas is not installed; shapefile products are unavailable")
    resp = http_get(url, timeout=(5, 60), max_bytes=MAX_ZIP_BYTES)
    out: dict = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                zf.extractall(tmp)
            for shp in Path(tmp).rglob("*.shp"):
                try:
                    gdf = gpd.read_file(shp)
                except Exception as exc:  # corrupt/odd layer: skip, keep others
                    log.warning("Could not read %s: %s", shp.name, exc)
                    continue
                if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
                    gdf = gdf.to_crs(4326)
                out[shp.stem.lower()] = gdf
    except zipfile.BadZipFile as exc:
        raise DataValidationError(f"{url} is not a valid zip archive") from exc
    return out


def fetch_forecast_package(zip_url: str) -> dict:
    """Split the 5-day advisory zip into cone / track line / forecast points / watches-warnings."""
    layers = read_zip_shapefiles(zip_url)
    pkg = {"cone": None, "track_line": None, "points": None, "warnings": None}
    for stem, gdf in layers.items():
        if "ww" in stem.split("_"):
            pkg["warnings"] = gdf
        elif stem.endswith("_pgn"):
            pkg["cone"] = gdf
        elif stem.endswith("_lin"):
            pkg["track_line"] = gdf
        elif stem.endswith("_pts"):
            pkg["points"] = gdf
    return pkg


def fetch_wind_radii(zip_url: str):
    """Initial / forecast wind radii polygons (kt quadrants) as one GeoDataFrame, or None."""
    layers = read_zip_shapefiles(zip_url)
    frames = [g.assign(layer=stem) for stem, g in layers.items() if "radii" in stem or "fcst" in stem]
    return pd.concat(frames, ignore_index=True) if frames else None


def fetch_best_track(zip_url: str) -> dict:
    """Preliminary best track (points/line/wind swath) of an active storm."""
    layers = read_zip_shapefiles(zip_url)
    out = {"points": None, "line": None, "swath": None}
    for stem, gdf in layers.items():
        if stem.endswith("_pts"):
            out["points"] = gdf
        elif stem.endswith("_lin"):
            out["line"] = gdf
        elif "swath" in stem:
            out["swath"] = gdf
    return out


def _geom_latlon(gdf):
    return gdf.geometry.y.to_numpy(), gdf.geometry.x.to_numpy()


def normalize_forecast_points(gdf) -> pd.DataFrame:
    """Official forecast positions: tau (h), position, max wind (kt), gust, pressure, type."""
    if gdf is None or len(gdf) == 0:
        return pd.DataFrame()
    lat, lon = _geom_latlon(gdf)
    out = pd.DataFrame({"lat": lat, "lon": lon})
    for target, cands in {"tau_h": ("TAU",), "wind_kt": ("MAXWIND",), "gust_kt": ("GUST",),
                          "pressure_mb": ("MSLP",), "status": ("TCDVLP",), "label": ("DATELBL",),
                          "ss_cat": ("SSNUM",)}.items():
        c = _col(gdf, *cands)
        out[target] = gdf[c].to_numpy() if c else np.nan
    for c in ("tau_h", "wind_kt", "gust_kt", "pressure_mb"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out.loc[out["pressure_mb"] <= 0, "pressure_mb"] = np.nan
    return out.sort_values("tau_h", na_position="first").reset_index(drop=True)


def normalize_best_track_points(gdf) -> pd.DataFrame:
    """Best-track history of an active storm -> time, lat, lon, wind_kt, pressure_mb (best effort)."""
    if gdf is None or len(gdf) == 0:
        return pd.DataFrame()
    lat, lon = _geom_latlon(gdf)
    out = pd.DataFrame({"lat": lat, "lon": lon})
    c_w, c_p = _col(gdf, "INTENSITY", "MAXWIND", "WIND"), _col(gdf, "MSLP", "PRESSURE", "PRES")
    out["wind_kt"] = pd.to_numeric(gdf[c_w], errors="coerce").to_numpy() if c_w else np.nan
    out["pressure_mb"] = pd.to_numeric(gdf[c_p], errors="coerce").to_numpy() if c_p else np.nan
    out.loc[out["pressure_mb"] <= 0, "pressure_mb"] = np.nan
    t = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]")
    try:
        cy, cm, cd, ch = (_col(gdf, n) for n in ("YEAR", "MONTH", "DAY", "HHMM"))
        if all((cy, cm, cd, ch)):
            hhmm = pd.to_numeric(gdf[ch], errors="coerce").fillna(0).astype(int)
            t = pd.to_datetime({"year": pd.to_numeric(gdf[cy]), "month": pd.to_numeric(gdf[cm]),
                                "day": pd.to_numeric(gdf[cd]), "hour": hhmm // 100,
                                "minute": hhmm % 100}, utc=True, errors="coerce")
        elif _col(gdf, "DTG"):
            t = pd.to_datetime(gdf[_col(gdf, "DTG")].astype(str), format="%Y%m%d%H", utc=True, errors="coerce")
    except Exception as exc:
        log.warning("Could not parse best-track timestamps: %s", exc)
    out["time"] = t.to_numpy()
    return out.sort_values("time").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# HURDAT2 (final best-track archive)
# --------------------------------------------------------------------------- #
_HURDAT_RE = re.compile(r"hurdat2-1851-(\d{4})-(\d{6})\.txt")


def find_latest_hurdat_url() -> str:
    """Discover the current Atlantic HURDAT2 file name (it embeds the release date)."""
    best: tuple | None = None
    for index_url in HURDAT_INDEX_URLS:
        try:
            html = http_get(index_url).text
        except SourceError as exc:
            log.warning("HURDAT index %s failed: %s", index_url, exc)
            continue
        for year, mmddyy in _HURDAT_RE.findall(html):
            key = (int(year), int(mmddyy[4:6]), int(mmddyy[0:2]), int(mmddyy[2:4]))  # year, YY, MM, DD
            if best is None or key > best[0]:
                best = (key, f"hurdat2-1851-{year}-{mmddyy}.txt")
        if best:
            break
    if not best:
        raise SourceError("Could not locate the Atlantic HURDAT2 file on nhc.noaa.gov")
    return HURDAT_BASE_URL + best[1]


def fetch_hurdat_text() -> tuple[str, str]:
    url = find_latest_hurdat_url()
    text = http_get(url, timeout=(5, 90), max_bytes=40 * 1024 * 1024).text
    try:  # keep the raw file for reproducibility
        (RAW_DIR / url.rsplit("/", 1)[-1]).write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text, url


def _coord(token: str) -> float:
    token = token.strip()
    val = float(token[:-1])
    return -val if token[-1] in "SW" else val


def parse_hurdat2(text: str) -> pd.DataFrame:
    """Parse HURDAT2 text -> tidy frame (one row per 6-hourly/landfall record)."""
    rows, sid, name = [], None, None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[0]:
            continue
        if parts[0][:2] in {"AL", "EP", "CP"} and len(parts[0]) == 8 and parts[2].isdigit():
            sid, name = parts[0], parts[1]
            if name.upper() == "UNNAMED":
                name = f"UNNAMED-{sid}"
            continue
        if sid is None or len(parts) < 8:
            continue
        try:
            rows.append((sid, name, int(sid[4:8]),
                         pd.Timestamp(f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]} {parts[1][:2]}:{parts[1][2:4]}", tz="UTC"),
                         parts[2], parts[3], _coord(parts[4]), _coord(parts[5]),
                         float(parts[6]), float(parts[7])))
        except (ValueError, IndexError):
            continue
    if not rows:
        raise DataValidationError("HURDAT2: no records could be parsed")
    df = pd.DataFrame(rows, columns=["storm_id", "name", "year", "time", "record_id", "status",
                                     "lat", "lon", "wind_kt", "pressure_mb"])
    df.loc[df["wind_kt"] < 0, "wind_kt"] = np.nan          # -99 = missing
    df.loc[df["pressure_mb"] < 0, "pressure_mb"] = np.nan  # -999 = missing
    return df.drop_duplicates(["storm_id", "time", "record_id"]).sort_values(["storm_id", "time"]).reset_index(drop=True)
