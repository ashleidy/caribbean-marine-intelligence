"""Derived cyclone metrics. Everything here is COMPUTED BY THIS APP from NHC data and
must be presented as such (never as an official alert)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from utils.config import PALETTE
from utils.coordinates import bearing_deg, deg_to_cardinal, haversine_km, km_to_nm

CATEGORY_ORDER = ["Unknown", "Tropical Depression", "Tropical Storm", "Cat 1", "Cat 2", "Cat 3", "Cat 4", "Cat 5"]
CATEGORY_COLORS = {"Unknown": PALETTE["muted"], "Tropical Depression": PALETTE["sky"], "Tropical Storm": PALETTE["aqua"],
                   "Cat 1": PALETTE["sun"], "Cat 2": PALETTE["papaya"], "Cat 3": PALETTE["coral"],
                   "Cat 4": "#E5446D", "Cat 5": PALETTE["orchid"]}


def category_from_wind(kt) -> str:
    """Saffir-Simpson category from max sustained wind in knots (computed)."""
    if kt is None or pd.isna(kt):
        return "Unknown"
    for lim, name in ((137, "Cat 5"), (113, "Cat 4"), (96, "Cat 3"), (83, "Cat 2"), (64, "Cat 1"), (34, "Tropical Storm")):
        if kt >= lim:
            return name
    return "Tropical Depression"


def densify(lat, lon, steps: int | None = None):
    """Linear sub-sampling of a track (~10 km spacing) so closest approach is not limited to the fixes."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    if len(lat) < 2:
        return lat, lon, np.arange(len(lat), dtype=float)
    if steps is None:
        longest = float(np.nanmax(haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:])))
        steps = int(np.clip(np.ceil(longest / 10.0), 6, 200))
    pos = np.linspace(0, len(lat) - 1, (len(lat) - 1) * steps + 1)
    idx = np.arange(len(lat))
    return np.interp(pos, idx, lat), np.interp(pos, idx, lon), pos


def closest_approach(lat, lon, times, ref_lat: float, ref_lon: float) -> dict:
    la, lo, pos = densify(lat, lon)
    if len(la) == 0:
        return {"min_km": np.nan, "time": pd.NaT, "index": None}
    d = haversine_km(la, lo, ref_lat, ref_lon)
    i = int(np.argmin(d))
    t = pd.NaT
    if times is not None and len(times) == len(lat):
        times = pd.DatetimeIndex(times)
        lo_i = int(np.floor(pos[i])); hi_i = min(lo_i + 1, len(times) - 1)
        if pd.notna(times[lo_i]) and pd.notna(times[hi_i]):
            t = times[lo_i] + (times[hi_i] - times[lo_i]) * (pos[i] - lo_i)
    return {"min_km": float(d[i]), "time": t, "index": int(round(pos[i]))}


def rank_active(storms: pd.DataFrame, ref_lat: float, ref_lon: float) -> pd.DataFrame:
    """Active storms sorted by distance from the reference point (computed)."""
    if storms is None or storms.empty:
        return pd.DataFrame()
    df = storms.copy()
    df["distance_km"] = haversine_km(df["lat"], df["lon"], ref_lat, ref_lon)
    df["distance_nm"] = km_to_nm(df["distance_km"])
    df["bearing_from_ref"] = bearing_deg(ref_lat, ref_lon, df["lat"], df["lon"])
    df["direction_from_ref"] = df["bearing_from_ref"].map(deg_to_cardinal)
    df["category_computed"] = df["intensity_kt"].map(category_from_wind)
    return df.sort_values("distance_km").reset_index(drop=True)


def movement_from_points(pts: pd.DataFrame, hours: float = 12) -> dict:
    """Heading/speed over the last ~`hours` of a best-track point table (needs time, lat, lon)."""
    if pts is None or len(pts) < 2 or "time" not in pts or pts["time"].isna().all():
        return {}
    p = pts.dropna(subset=["time"]).sort_values("time")
    last = p.iloc[-1]
    prev = p[p["time"] <= last["time"] - pd.Timedelta(hours=hours)]
    ref = prev.iloc[-1] if len(prev) else p.iloc[0]
    dt = (last["time"] - ref["time"]).total_seconds() / 3600
    if dt <= 0:
        return {}
    km = float(haversine_km(ref["lat"], ref["lon"], last["lat"], last["lon"]))
    return {"direction_deg": float(bearing_deg(ref["lat"], ref["lon"], last["lat"], last["lon"])),
            "speed_kt": km_to_nm(km) / dt, "window_h": dt}


def intensity_trend(pts: pd.DataFrame, hours: float = 24, threshold_kt: float = 10) -> dict:
    """Wind/pressure change over ~`hours` -> Intensifying / Weakening / Steady (computed)."""
    if pts is None or len(pts) < 2 or "time" not in pts or pts["time"].isna().all():
        return {}
    p = pts.dropna(subset=["time", "wind_kt"]).sort_values("time")
    if len(p) < 2:
        return {}
    last = p.iloc[-1]
    prev = p[p["time"] <= last["time"] - pd.Timedelta(hours=hours)]
    ref = prev.iloc[-1] if len(prev) else p.iloc[0]
    dw = float(last["wind_kt"] - ref["wind_kt"])
    dp = float(last["pressure_mb"] - ref["pressure_mb"]) if pd.notna(last.get("pressure_mb")) and pd.notna(ref.get("pressure_mb")) else None
    label = "Intensifying" if dw >= threshold_kt else "Weakening" if dw <= -threshold_kt else "Steady"
    return {"label": label, "wind_change_kt": dw, "pressure_change_mb": dp,
            "window_h": (last["time"] - ref["time"]).total_seconds() / 3600}


def storm_summary(h: pd.DataFrame, ref_lat: float, ref_lon: float) -> pd.DataFrame:
    """One row per HURDAT2 storm: peak intensity and closest approach to the reference point."""
    rows = []
    for sid, g in h.groupby("storm_id", sort=False):
        ca = closest_approach(g["lat"].to_numpy(), g["lon"].to_numpy(), g["time"].to_numpy(), ref_lat, ref_lon)
        d_pts = haversine_km(g["lat"], g["lon"], ref_lat, ref_lon)
        wmax = g["wind_kt"].max()
        rows.append({"storm_id": sid, "name": g["name"].iloc[0], "year": int(g["year"].iloc[0]),
                     "start": g["time"].iloc[0], "end": g["time"].iloc[-1], "max_wind_kt": wmax,
                     "min_pressure_mb": g["pressure_mb"].min(), "max_category": category_from_wind(wmax),
                     "min_distance_km": ca["min_km"], "closest_time": ca["time"],
                     "wind_at_closest_kt": g["wind_kt"].to_numpy()[int(np.argmin(np.asarray(d_pts)))],
                     "n_points": len(g)})
    return pd.DataFrame(rows)


def storms_in_bbox(h: pd.DataFrame, bbox: tuple[float, float, float, float]) -> set:
    lat0, lat1, lon0, lon1 = bbox
    m = h["lat"].between(lat0, lat1) & h["lon"].between(lon0, lon1)
    return set(h.loc[m, "storm_id"].unique())
