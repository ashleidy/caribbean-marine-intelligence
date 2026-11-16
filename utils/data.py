"""Data-access layer used by the pages.

* Wraps every service in ``st.cache_data`` (TTL tuned per source) so reruns/clicks never re-hit APIs.
* Cached functions RAISE on failure (Streamlit does not cache exceptions) and the public
  ``load_*`` wrappers convert them to ``FetchResult(ok=False)``: one failing source never breaks the page.
* Open-Meteo observations are persisted to SQLite (deduplicated) to build local history.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from analytics.cyclones import rank_active
from services import gdacs
from services import noaa_erddap as erddap
from services import noaa_nhc as nhc
import numpy as np
from services.base import FetchResult, get_logger
from services.open_meteo_marine import fetch_marine, fetch_marine_near
from services.open_meteo_weather import fetch_weather, fetch_weather_archive
from utils.cache import ObservationStore, is_fresh, safe_write_parquet
from utils.config import (PROCESSED_DIR, TTL_ERDDAP, TTL_HURDAT, TTL_MARINE, TTL_NHC, TTL_WEATHER,
                          VARIABLES, Location)

log = get_logger("data")
SRC_MARINE, SRC_WEATHER = "open_meteo_marine", "open_meteo_weather"


@st.cache_resource(show_spinner=False)
def store() -> ObservationStore:
    return ObservationStore()


def _fail(source: str, exc: Exception, url: str = "") -> FetchResult:
    log.warning("%s unavailable: %s", source, exc)
    return FetchResult(None, False, source, str(exc), url)


# ----------------------------------------------------------------- Open-Meteo
@st.cache_data(ttl=TTL_MARINE, show_spinner=False)
def _marine(name: str, lat: float, lon: float) -> pd.DataFrame:
    df = fetch_marine_near(lat, lon, past_days=92, forecast_days=7)
    now = pd.Timestamp.now(tz="UTC")
    store().upsert_wide(df[df.index <= now], name, SRC_MARINE)
    return df


@st.cache_data(ttl=TTL_WEATHER, show_spinner=False)
def _weather(name: str, lat: float, lon: float) -> pd.DataFrame:
    df = fetch_weather(lat, lon, past_days=92, forecast_days=7)
    store().upsert_wide(df[df.index <= pd.Timestamp.now(tz="UTC")], name, SRC_WEATHER)
    return df


def load_marine(loc: Location) -> FetchResult:
    try:
        return FetchResult(_marine(loc.name, loc.lat, loc.lon), True, "Open-Meteo Marine", url="https://marine-api.open-meteo.com/v1/marine")
    except Exception as exc:
        return _fail("Open-Meteo Marine", exc)


def load_weather(loc: Location) -> FetchResult:
    try:
        return FetchResult(_weather(loc.name, loc.lat, loc.lon), True, "Open-Meteo Weather", url="https://api.open-meteo.com/v1/forecast")
    except Exception as exc:
        return _fail("Open-Meteo Weather", exc)


def with_history(live: pd.DataFrame | None, loc: Location, source: str) -> pd.DataFrame | None:
    """Live frame (incl. forecast) completed with locally stored history (live values win)."""
    hist = store().read_wide(loc.name, source)
    if live is None or live.empty:
        return hist if not hist.empty else None
    if hist.empty:
        return live
    out = live.combine_first(hist).sort_index()
    out.attrs = live.attrs
    return out


def unified_frame(loc: Location, marine: FetchResult, weather: FetchResult) -> pd.DataFrame | None:
    parts = []
    for res, src in ((marine, SRC_MARINE), (weather, SRC_WEATHER)):
        df = with_history(res.data if res.ok else None, loc, src)
        if df is not None:
            parts.append(df)
    if not parts:
        return None
    out = pd.concat(parts, axis=1)
    return out.loc[:, ~out.columns.duplicated()].sort_index()


def backfill_marine(loc: Location, years: int) -> tuple[bool, str]:
    """Pull `years` of history (Open-Meteo supports start/end dates) into the local store."""
    end = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
    start = end - pd.DateOffset(years=years)
    ok_marine = ok_weather = False
    msgs = []
    try:
        df = fetch_marine(loc.lat, loc.lon, start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d"))
        n = store().upsert_wide(df, loc.name, SRC_MARINE)
        ok_marine = True
        msgs.append(f"marine: {n:,} values")
    except Exception as exc:
        msgs.append(f"marine failed ({exc})")
    try:
        df = fetch_weather_archive(loc.lat, loc.lon, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        n = store().upsert_wide(df, loc.name, SRC_WEATHER)
        ok_weather = True
        msgs.append(f"weather: {n:,} values")
    except Exception as exc:
        msgs.append(f"weather failed ({exc})")
    return (ok_marine or ok_weather), "; ".join(msgs)


def latest_obs(df: pd.DataFrame | None, col: str, now: pd.Timestamp | None = None):
    """(value, timestamp) of the most recent non-null observation up to ~now (+30 min)."""
    if df is None or col not in df.columns:
        return None, None
    now = now or pd.Timestamp.now(tz="UTC")
    s = df.loc[df.index <= now + pd.Timedelta(minutes=30), col].dropna()
    return (float(s.iloc[-1]), s.index[-1]) if len(s) else (None, None)


def snapshot(marine: FetchResult, weather: FetchResult) -> dict:
    """{variable: {value, unit, time, source}} for the current hour; missing -> value None."""
    out = {}
    for res in (marine, weather):
        for col in (res.data.columns if res.ok and res.data is not None else []):
            v, t = latest_obs(res.data, col)
            units = res.data.attrs.get("units", {})
            out[col] = {"value": v, "time": t, "unit": units.get(col, VARIABLES.get(col, {}).get("unit", "")),
                        "source": res.source}
    return out


# ----------------------------------------------------------------- NOAA NHC
@st.cache_data(ttl=TTL_NHC, show_spinner=False)
def _storms() -> pd.DataFrame:
    return nhc.fetch_active_storms()


def load_active_storms(loc: Location | None = None) -> FetchResult:
    try:
        df = _storms()
        if loc is not None:
            df = rank_active(df, loc.lat, loc.lon)
        return FetchResult(df, True, "NOAA NHC", url=nhc.CURRENT_STORMS_URL)
    except Exception as exc:
        return _fail("NOAA NHC", exc, nhc.CURRENT_STORMS_URL)


@st.cache_data(ttl=TTL_NHC, show_spinner=False)
def _forecast_pkg(url: str) -> dict:
    return nhc.fetch_forecast_package(url)


@st.cache_data(ttl=TTL_NHC, show_spinner=False)
def _best_track(url: str) -> dict:
    return nhc.fetch_best_track(url)


@st.cache_data(ttl=TTL_NHC, show_spinner=False)
def _wind_radii(url: str):
    return nhc.fetch_wind_radii(url)


def load_forecast_package(url: str | None) -> FetchResult:
    if not url:
        return FetchResult(None, False, "NOAA NHC", "No forecast package listed for this storm")
    try:
        return FetchResult(_forecast_pkg(url), True, "NOAA NHC", url=url)
    except Exception as exc:
        return _fail("NOAA NHC", exc, url)


def load_best_track(url: str | None) -> FetchResult:
    if not url:
        return FetchResult(None, False, "NOAA NHC", "No best-track package listed")
    try:
        return FetchResult(_best_track(url), True, "NOAA NHC", url=url)
    except Exception as exc:
        return _fail("NOAA NHC", exc, url)


def load_wind_radii(url: str | None) -> FetchResult:
    if not url:
        return FetchResult(None, False, "NOAA NHC", "No wind-radii package listed")
    try:
        return FetchResult(_wind_radii(url), True, "NOAA NHC", url=url)
    except Exception as exc:
        return _fail("NOAA NHC", exc, url)


@st.cache_data(ttl=TTL_HURDAT, show_spinner="Loading HURDAT2 (NHC best-track archive)…")
def _hurdat() -> tuple[pd.DataFrame, str]:
    path, meta = PROCESSED_DIR / "hurdat2_atlantic.parquet", PROCESSED_DIR / "hurdat2_atlantic.json"
    if is_fresh(path, TTL_HURDAT) and meta.exists():
        return pd.read_parquet(path), json.loads(meta.read_text())["url"]
    try:
        text, url = nhc.fetch_hurdat_text()
        df = nhc.parse_hurdat2(text)
        if safe_write_parquet(df, path):
            meta.write_text(json.dumps({"url": url}))
        return df, url
    except Exception:
        if path.exists() and meta.exists():       # stale-but-valid copy beats nothing
            log.warning("HURDAT2 refresh failed; using stale local copy")
            return pd.read_parquet(path), json.loads(meta.read_text())["url"]
        raise


def load_hurdat() -> FetchResult:
    try:
        df, url = _hurdat()
        return FetchResult(df, True, "NOAA NHC HURDAT2", url=url)
    except Exception as exc:
        return _fail("NOAA NHC HURDAT2", exc)


# ----------------------------------------------------------------- ERDDAP
@st.cache_data(ttl=TTL_ERDDAP, show_spinner=False)
def erddap_search(query: str) -> pd.DataFrame:
    return erddap.search_datasets(query)


@st.cache_data(ttl=TTL_ERDDAP, show_spinner=False)
def erddap_variables(dataset_id: str) -> pd.DataFrame:
    return erddap.dataset_variables(dataset_id)


@st.cache_data(ttl=TTL_ERDDAP, show_spinner=False)
def erddap_table(dataset_id: str, variables: tuple, start: str, end: str, bbox: tuple) -> pd.DataFrame:
    return erddap.fetch_tabledap(dataset_id, list(variables), start, end, bbox)


@st.cache_data(ttl=TTL_ERDDAP, show_spinner=False)
def erddap_grid(dataset_id: str, variable: str, start: str, end: str, bbox: tuple, stride: int) -> pd.DataFrame:
    return erddap.fetch_griddap(dataset_id, variable, start, end, bbox, stride)


# ----------------------------------------------------------------- GDACS (worldwide cyclones)
@st.cache_data(ttl=TTL_NHC, show_spinner=False)
def _gdacs_events() -> pd.DataFrame:
    return gdacs.fetch_active_events()


@st.cache_data(ttl=TTL_NHC, show_spinner=False)
def _gdacs_track(eventid: int, ref_kmh: float | None) -> dict:
    return gdacs.fetch_track(eventid, ref_kmh)


def load_gdacs_storms() -> FetchResult:
    try:
        return FetchResult(gdacs.to_storm_frame(_gdacs_events()), True, "GDACS (worldwide)", url=gdacs.BASE_URL)
    except Exception as exc:
        return _fail("GDACS (worldwide)", exc, gdacs.BASE_URL)


def load_gdacs_track(eventid: int, ref_kmh: float | None = None) -> FetchResult:
    try:
        return FetchResult(_gdacs_track(int(eventid), None if ref_kmh is None or pd.isna(ref_kmh) else float(ref_kmh)), True, "GDACS (worldwide)")
    except Exception as exc:
        return _fail("GDACS (worldwide)", exc)


def load_all_storms(loc: Location) -> tuple[FetchResult, FetchResult, FetchResult]:
    """Every active tropical cyclone on Earth: NOAA NHC (Atlantic / E & C Pacific, full detail) + GDACS (all other basins).

    Returns (combined, nhc_result, gdacs_result). `combined.ok` is True if at least one source answered.
    """
    nhc_res, gd_res = load_active_storms(None), load_gdacs_storms()
    parts = []
    if nhc_res.ok and not nhc_res.data.empty:
        parts.append(nhc_res.data.assign(source="NOAA NHC"))
    if gd_res.ok and not gd_res.data.empty:
        g = gd_res.data
        if nhc_res.ok:                                    # NHC is the official source inside its own basins
            g = g[~np.array([gdacs.in_nhc_area(a, b) for a, b in zip(g["lat"], g["lon"])], dtype=bool)]
        if not g.empty:
            parts.append(g)
    if not (nhc_res.ok or gd_res.ok):
        return FetchResult(None, False, "Active storms", f"{nhc_res.message}; {gd_res.message}"), nhc_res, gd_res
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not df.empty:
        df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)      # never plot a storm at (0, 0)
    if not df.empty:
        df = rank_active(df, loc.lat, loc.lon)
    return FetchResult(df, True, "Active storms (NHC + GDACS)"), nhc_res, gd_res
