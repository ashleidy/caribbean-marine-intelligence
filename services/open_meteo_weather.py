"""Open-Meteo Weather API client (forecast + short history, plus the ERA5 archive).

Docs    : https://open-meteo.com/en/docs
Endpoint: https://api.open-meteo.com/v1/forecast
Archive : https://archive-api.open-meteo.com/v1/archive  (historical re-analysis)
"""
from __future__ import annotations

import pandas as pd

from services.base import DataValidationError, get_logger, http_get_json

log = get_logger("open_meteo_weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "precipitation", "rain",
    "surface_pressure", "pressure_msl", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "cloud_cover", "weather_code",
]

# WMO weather interpretation codes, as documented by Open-Meteo.
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def describe_weather_code(code) -> str:
    try:
        return WMO_CODES.get(int(code), f"Code {int(code)}")
    except (TypeError, ValueError):
        return "Data unavailable"


def _parse(payload: dict) -> pd.DataFrame:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not hourly or "time" not in hourly:
        raise DataValidationError("Open-Meteo Weather: response has no 'hourly.time' block")
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).drop_duplicates("time", keep="last").set_index("time").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")
    df.attrs.update(units=payload.get("hourly_units", {}), grid_lat=payload.get("latitude"),
                    grid_lon=payload.get("longitude"), elevation=payload.get("elevation"),
                    source="Open-Meteo Weather")
    return df


def fetch_weather(lat: float, lon: float, past_days: int = 7, forecast_days: int = 7,
                  variables: list[str] | None = None) -> pd.DataFrame:
    """Hourly weather in UTC; wind in knots (marine convention), precipitation in mm."""
    params = {"latitude": lat, "longitude": lon, "hourly": ",".join(variables or WEATHER_VARIABLES),
              "past_days": past_days, "forecast_days": forecast_days,
              "wind_speed_unit": "kn", "timezone": "UTC"}
    return _parse(http_get_json(FORECAST_URL, params))


def fetch_weather_archive(lat: float, lon: float, start_date: str, end_date: str,
                          variables: list[str] | None = None) -> pd.DataFrame:
    """Historical hourly weather (ERA5-based archive) for a date window."""
    params = {"latitude": lat, "longitude": lon, "hourly": ",".join(variables or WEATHER_VARIABLES),
              "start_date": start_date, "end_date": end_date,
              "wind_speed_unit": "kn", "timezone": "UTC"}
    return _parse(http_get_json(ARCHIVE_URL, params, timeout=(5, 60)))
