"""GDACS (Global Disaster Alert and Coordination System) - tropical cyclones WORLDWIDE.

NOAA NHC only covers the Atlantic, East Pacific and Central Pacific. GDACS (UN / European Commission) lists
cyclones in every basin (West Pacific/Asia, Indian Ocean, Australia/South Pacific...) using JTWC and NOAA data.
REST API, no key: https://www.gdacs.org/gdacsapi/swagger/index.html
  * /events/geteventlist/SEARCH?eventlist=TC&alertlevel=<Green|Orange|Red>&fromDate&toDate&pageSize&pageNumber
        -> GeoJSON features (eventid, eventname, alertlevel, iscurrent, severitydata{severity km/h, severitytext}, source, coords)
  * /events/geteventdata?eventtype=TC&eventid=<id>  -> event detail incl. the advisory *timeline* resource URL
  * timeline JSON -> channel.item[] with advisory_datetime, actual (observed vs forecast), latitude, longitude, wind_speed...
This is a secondary, less detailed source than NHC (no cone / watches / warnings), so NHC wins inside its basins.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from services.base import DataValidationError, SourceError, get_logger, http_get, http_get_json
from utils.formatting import KMH_TO_KT

log = get_logger("gdacs")
BASE_URL = "https://www.gdacs.org/gdacsapi/api"
ALERT_LEVELS = ("Green", "Orange", "Red")   # queried separately and de-duplicated (the combined filter is unreliable)
PAGE_SIZE = 100
REPORT_URL = "https://www.gdacs.org/report.aspx?eventtype=TC&eventid={eventid}"


def basin_from_position(lat: float, lon: float) -> str:
    """Approximate ocean basin from coordinates (display only)."""
    if lat >= 0:
        if -180 <= lon <= -100:
            return "East Pacific"
        if -100 < lon <= -10:
            return "Atlantic"
        if 40 <= lon < 100:
            return "North Indian"
        if lon >= 100 or lon < -180:
            return "West Pacific"
        return "Other"
    if 20 <= lon < 90:
        return "South Indian"
    if lon >= 90 or lon <= -120:
        return "Australia / South Pacific"
    return "South Atlantic / Other"


def in_nhc_area(lat: float, lon: float) -> bool:
    """True where NOAA NHC/CPHC is the official source (Atlantic, East & Central Pacific)."""
    return lat >= 0 and -180 <= lon <= -10


def _page(level: str, page: int, from_date: str, to_date: str) -> list[dict]:
    resp = http_get(f"{BASE_URL}/events/geteventlist/SEARCH",
                    {"eventlist": "TC", "alertlevel": level, "fromDate": from_date, "toDate": to_date,
                     "pageSize": PAGE_SIZE, "pageNumber": page}, timeout=(5, 40))
    if not resp.text.strip():            # empty body = no more pages / no events
        return []
    try:
        payload = resp.json()
    except ValueError as exc:
        raise DataValidationError("GDACS returned invalid JSON") from exc
    return payload.get("features", []) if isinstance(payload, dict) else []


def fetch_active_events(days: int = 10) -> pd.DataFrame:
    """Currently active tropical cyclones worldwide, one row per event (empty frame = none)."""
    now = pd.Timestamp.now(tz="UTC")
    from_date, to_date = (now - pd.Timedelta(days=days)).strftime("%Y-%m-%d"), (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    seen: dict[int, dict] = {}
    errors = 0
    for level in ALERT_LEVELS:
        page = 1
        while page <= 5:
            try:
                feats = _page(level, page, from_date, to_date)
            except SourceError as exc:
                errors += 1
                log.warning("GDACS %s page %s failed: %s", level, page, exc)
                break
            for f in feats:
                try:
                    p, c = f["properties"], f["geometry"]["coordinates"]
                    eid = int(p["eventid"])
                except (KeyError, TypeError, ValueError):
                    continue
                if str(p.get("iscurrent", "")).lower() != "true" or eid in seen:
                    continue
                sev = p.get("severitydata") or {}
                seen[eid] = {"eventid": eid, "name": p.get("eventname") or p.get("name") or f"TC-{eid}", "alert_level": p.get("alertlevel"),
                             "severity_kmh": pd.to_numeric(sev.get("severity"), errors="coerce"), "severity_text": sev.get("severitytext"),
                             "gdacs_source": p.get("source") or "", "country": p.get("country"), "lon": float(c[0]), "lat": float(c[1]),
                             "from_date": p.get("fromdate"), "to_date": p.get("todate"),
                             "report_url": ((p.get("url") or {}).get("report") if isinstance(p.get("url"), dict) else None) or REPORT_URL.format(eventid=eid)}
            if len(feats) < PAGE_SIZE:
                break
            page += 1
    if errors == len(ALERT_LEVELS) and not seen:
        raise SourceError("GDACS did not answer any request")
    cols = ["eventid", "name", "alert_level", "severity_kmh", "severity_text", "gdacs_source", "country", "lon", "lat", "from_date", "to_date", "report_url"]
    return pd.DataFrame(list(seen.values()), columns=cols)


def to_storm_frame(events: pd.DataFrame) -> pd.DataFrame:
    """Map GDACS events onto the same columns the NHC frame uses so both can be merged."""
    if events is None or events.empty:
        return pd.DataFrame()
    df = pd.DataFrame({
        "id": "gdacs" + events["eventid"].astype(str), "eventid": events["eventid"], "source": "GDACS" + events["gdacs_source"].map(lambda s: f" ({s})" if s else ""),
        "basin": [basin_from_position(a, b) for a, b in zip(events["lat"], events["lon"])],
        "name": events["name"].astype(str).str.replace(r"-\d{2}$", "", regex=True).str.title(),
        "classification": "", "classification_label": events["severity_text"].fillna("Tropical cyclone").astype(str).str.split("(").str[0].str.strip(),
        "intensity_kt": events["severity_kmh"] * KMH_TO_KT, "pressure_mb": np.nan, "lat": events["lat"], "lon": events["lon"],
        "movement_dir_deg": np.nan, "movement_speed_mph": np.nan, "movement_speed_kt": np.nan,
        "last_update": pd.to_datetime(events["to_date"], errors="coerce", utc=True), "alert_level": events["alert_level"], "country": events["country"],
        "public_advisory_url": events["report_url"], "forecast_advisory_url": None, "discussion_url": None, "graphics_url": None,
        "forecast_zip": None, "best_track_zip": None, "surge_ww_kml": None, "surge_flooding_zip": None,
    })
    return df


def fetch_track(eventid: int, ref_kmh: float | None = None) -> dict:
    """Advisory timeline -> {'observed': DataFrame, 'forecast': DataFrame} using the NHC-style column names.

    The wind unit of the timeline is not stated in the schema we could verify, so it is auto-checked against the
    event's official intensity (km/h): if they do not agree, wind is left empty rather than guessed.
    """
    detail = http_get_json(f"{BASE_URL}/events/geteventdata", {"eventtype": "TC", "eventid": eventid})
    url = None
    for imp in (detail.get("properties", {}) or {}).get("impacts", []) or []:
        url = (imp.get("resource") or {}).get("timeline")
        if url:
            break
    if not url:
        raise DataValidationError(f"GDACS event {eventid} has no timeline")
    items = (http_get_json(url).get("channel", {}) or {}).get("item") or []
    rows = []
    for it in items:
        rows.append({"time": it.get("advisory_datetime"), "actual": str(it.get("actual", "")).lower() == "true",
                     "lat": it.get("latitude"), "lon": it.get("longitude"), "w": it.get("wind_speed"),
                     "g": it.get("wind_gusts"), "p": it.get("pressure")})
    if not rows:
        raise DataValidationError("GDACS timeline is empty")
    df = pd.DataFrame(rows)
    for c in ("lat", "lon", "w", "g", "p"):
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    df["time"] = pd.to_datetime(df["time"], format="mixed", errors="coerce", utc=True)
    df = df.dropna(subset=["lat", "lon"]).sort_values("time")
    obs, fc = df[df["actual"]].copy(), df[~df["actual"]].copy()

    factor = None                                    # wind -> knots
    if ref_kmh and len(obs) and pd.notna(obs["w"].iloc[-1]) and obs["w"].iloc[-1] > 0:
        ratio = obs["w"].iloc[-1] / ref_kmh
        if 0.9 <= ratio <= 1.1:
            factor = KMH_TO_KT
    def conv(frame):
        out = pd.DataFrame({"lat": frame["lat"].to_numpy(), "lon": frame["lon"].to_numpy(), "time": frame["time"].to_numpy()})
        out["wind_kt"] = frame["w"].to_numpy() * factor if factor else np.nan
        out["gust_kt"] = frame["g"].to_numpy() * factor if factor else np.nan
        out["pressure_mb"] = frame["p"].where(frame["p"] > 800).to_numpy()
        return out
    obs_n, fc_n = conv(obs), conv(fc)
    now = pd.Timestamp.now(tz="UTC")
    fc_n["tau_h"] = ((fc_n["time"] - now).dt.total_seconds() / 3600).round(0)
    fc_n["label"] = pd.to_datetime(fc_n["time"], utc=True).dt.tz_convert("America/Bogota").dt.strftime("%a %d %H:%M")
    fc_n["status"], fc_n["ss_cat"] = "", np.nan
    return {"observed": obs_n.dropna(subset=["time"]).reset_index(drop=True), "forecast": fc_n.dropna(subset=["time"]).reset_index(drop=True), "wind_known": factor is not None}
