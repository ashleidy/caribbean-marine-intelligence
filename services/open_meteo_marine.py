"""Open-Meteo Marine API client.

Docs : https://open-meteo.com/en/docs/marine-weather-api
Endpoint: https://marine-api.open-meteo.com/v1/marine

Marine grids are coarse and masked over land, so for a small island such as
Providencia the exact coordinate can return nulls. `fetch_marine_near` tries a
few nearby sea points and reports which grid cell actually answered.
"""
from __future__ import annotations

import pandas as pd

from services.base import DataValidationError, SourceError, get_logger, http_get_json

log = get_logger("open_meteo_marine")

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
MARINE_VARIABLES = [
    "wave_height", "wave_direction", "wave_period", "wave_peak_period",
    "swell_wave_height", "swell_wave_direction", "swell_wave_period",
    "sea_level_height_msl", "sea_surface_temperature",
    "ocean_current_velocity", "ocean_current_direction",
]
# Offsets (deg lat, deg lon) tried when the exact point is land-masked / empty.
_FALLBACK_OFFSETS = [(0.0, 0.0), (0.08, 0.0), (-0.08, 0.0), (0.0, 0.08), (0.0, -0.08), (0.16, 0.16)]
_CORE_VARS = ("wave_height", "sea_surface_temperature", "sea_level_height_msl")


def _parse(payload: dict) -> pd.DataFrame:
    """Validate + normalise one API response into a UTC-indexed numeric frame."""
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not hourly or "time" not in hourly:
        raise DataValidationError("Open-Meteo Marine: response has no 'hourly.time' block")
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).drop_duplicates("time", keep="last").set_index("time").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")  # missing -> NaN (never invented)
    df.attrs.update(units=payload.get("hourly_units", {}), grid_lat=payload.get("latitude"),
                    grid_lon=payload.get("longitude"), source="Open-Meteo Marine")
    return df


def _request(lat: float, lon: float, variables: list[str], **time_params) -> pd.DataFrame:
    params = {"latitude": lat, "longitude": lon, "hourly": ",".join(variables),
              "timezone": "UTC", **{k: v for k, v in time_params.items() if v is not None}}
    return _parse(http_get_json(MARINE_URL, params))


def fetch_marine(lat: float, lon: float, past_days: int = 7, forecast_days: int = 7,
                 start_date: str | None = None, end_date: str | None = None,
                 variables: list[str] | None = None) -> pd.DataFrame:
    """Hourly marine data. Use (start_date, end_date) for a historical window, otherwise
    (past_days, forecast_days). If the API rejects the combined request (e.g. one variable is
    not offered), variables are requested one by one and only the available ones are kept."""
    variables = variables or MARINE_VARIABLES
    tp = ({"start_date": start_date, "end_date": end_date} if start_date and end_date
          else {"past_days": past_days, "forecast_days": forecast_days})
    try:
        return _request(lat, lon, variables, **tp)
    except SourceError as exc:
        log.warning("Combined marine request failed (%s); retrying per variable", exc)
    frames, missing, units = [], [], {}
    for var in variables:
        try:
            part = _request(lat, lon, [var], **tp)
            frames.append(part)
            units.update(part.attrs.get("units", {}))
        except SourceError:
            missing.append(var)
    if not frames:
        raise SourceError("Open-Meteo Marine returned no data for any requested variable")
    df = pd.concat(frames, axis=1)
    df.attrs.update(units=units, grid_lat=frames[0].attrs.get("grid_lat"),
                    grid_lon=frames[0].attrs.get("grid_lon"), source="Open-Meteo Marine",
                    unavailable=missing)
    return df


def _has_data(df: pd.DataFrame) -> bool:
    cols = [c for c in _CORE_VARS if c in df.columns]
    return bool(cols) and bool(df[cols].notna().any().any())


def fetch_marine_near(lat: float, lon: float, **kwargs) -> pd.DataFrame:
    """Like `fetch_marine` but walks a few nearby points if the exact one is masked/empty.
    The point that answered is stored in `df.attrs['query_point']` (shown in the UI)."""
    last_exc: Exception | None = None
    for dlat, dlon in _FALLBACK_OFFSETS:
        qlat, qlon = round(lat + dlat, 4), round(lon + dlon, 4)
        try:
            df = fetch_marine(qlat, qlon, **kwargs)
        except SourceError as exc:
            last_exc = exc
            continue
        if _has_data(df):
            df.attrs["query_point"] = (qlat, qlon)
            df.attrs["offset_used"] = (dlat, dlon) != (0.0, 0.0)
            return df
    raise SourceError(f"No marine data near ({lat}, {lon})" + (f": {last_exc}" if last_exc else ""))
