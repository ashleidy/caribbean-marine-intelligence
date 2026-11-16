"""Global configuration: paths, palette, locations, variable metadata, defaults.

Everything that a maintainer may want to tweak (colours, reference points,
risk thresholds, cache TTLs) lives here so the rest of the code stays generic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# Branding / legal text
# --------------------------------------------------------------------------- #
APP_NAME = "CARIBBEAN MARINE INTELLIGENCE"
APP_SUBTITLE = (
    "Monitoring, oceanographic and weather analysis, and tropical cyclone tracking for the "
    "Caribbean, with an initial focus on Providencia and Santa Catalina, Colombia."
)
DISCLAIMER = (
    "This platform is an independent data visualization and analytics project. "
    "It does not replace official meteorological, maritime or emergency warnings."
)
USER_AGENT = "CaribbeanMarineIntelligence/1.0 (open data dashboard; Streamlit)"
UNAVAILABLE = "Data unavailable"

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"
for _d in (RAW_DIR, PROCESSED_DIR, CACHE_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only file system: the app keeps working without disk cache
        pass
STORE_PATH = CACHE_DIR / "observations.sqlite"

# --------------------------------------------------------------------------- #
# Tropical / blue palette  (change here to re-skin the whole app)
# --------------------------------------------------------------------------- #
PALETTE = {
    "abyss": "#04161F",
    "deep": "#05202D",
    "ocean": "#0B3A4F",
    "lagoon": "#0E7490",
    "turquoise": "#14D9C4",
    "aqua": "#7DF3E8",
    "sky": "#38BDF8",
    "palm": "#34D399",
    "sun": "#FFC857",
    "papaya": "#FF9F43",
    "coral": "#FF6B6B",
    "orchid": "#C77DFF",
    "sand": "#F4E9CD",
    "text": "#E6F7FA",
    "muted": "#8FB3BF",
}
COLORWAY = [
    PALETTE["turquoise"], PALETTE["sky"], PALETTE["sun"], PALETTE["coral"],
    PALETTE["palm"], PALETTE["orchid"], PALETTE["papaya"], PALETTE["aqua"],
]

# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float
    kind: str = "reference"      # "primary" | "reference"
    note: str = ""


PRIMARY = Location("Providencia & Santa Catalina", 13.34, -81.37, "primary", "Two adjacent islands shown as one point.")
LOCATIONS: dict[str, Location] = {
    PRIMARY.name: PRIMARY,
    "San Andrés": Location("San Andrés", 12.58, -81.70, "primary", "Approximate island centre."),
    "Quitasueño (approx.)": Location("Quitasueño (approx.)", 14.50, -81.25, "reference",
                                     "Approximate bank position - reference point, not a station."),
    "Cartagena": Location("Cartagena", 10.40, -75.50, "reference", "Reference point."),
    "Santa Marta": Location("Santa Marta", 11.24, -74.21, "reference", "Reference point."),
    "Kingston (Jamaica)": Location("Kingston (Jamaica)", 17.97, -76.79, "reference", "Reference point."),
    "Colón (Panama)": Location("Colón (Panama)", 9.36, -79.90, "reference", "Reference point."),
}
DEFAULT_LOCATION = PRIMARY.name
DISPLAY_TZ = "America/Bogota"          # Colombia, UTC-5 (no DST)

# --------------------------------------------------------------------------- #
# Cache TTLs (seconds) - tuned to how often each source really updates
# --------------------------------------------------------------------------- #
TTL_MARINE = 30 * 60
TTL_WEATHER = 15 * 60
TTL_NHC = 10 * 60
TTL_HURDAT = 7 * 24 * 3600
TTL_ERDDAP = 60 * 60

# --------------------------------------------------------------------------- #
# Variable metadata (labels, default units, provenance)
# --------------------------------------------------------------------------- #
VARIABLES: dict[str, dict[str, str]] = {
    "sea_level_height_msl": {"label": "Sea level (tide & model)", "unit": "m", "source": "Open-Meteo Marine"},
    "sea_surface_temperature": {"label": "Sea temperature", "unit": "°C", "source": "Open-Meteo Marine"},
    "wave_height": {"label": "Wave height", "unit": "m", "source": "Open-Meteo Marine"},
    "wave_direction": {"label": "Waves come from", "unit": "°", "source": "Open-Meteo Marine"},
    "wave_period": {"label": "Time between waves", "unit": "s", "source": "Open-Meteo Marine"},
    "wave_peak_period": {"label": "Time between waves (peak)", "unit": "s", "source": "Open-Meteo Marine"},
    "swell_wave_height": {"label": "Swell height", "unit": "m", "source": "Open-Meteo Marine"},
    "swell_wave_direction": {"label": "Swell comes from", "unit": "°", "source": "Open-Meteo Marine"},
    "swell_wave_period": {"label": "Swell: time between waves", "unit": "s", "source": "Open-Meteo Marine"},
    "ocean_current_velocity": {"label": "Ocean current speed", "unit": "km/h", "source": "Open-Meteo Marine"},
    "ocean_current_direction": {"label": "Ocean current flows toward", "unit": "°", "source": "Open-Meteo Marine"},
    "temperature_2m": {"label": "Air temperature", "unit": "°C", "source": "Open-Meteo Weather"},
    "relative_humidity_2m": {"label": "Relative humidity", "unit": "%", "source": "Open-Meteo Weather"},
    "precipitation": {"label": "Precipitation", "unit": "mm", "source": "Open-Meteo Weather"},
    "rain": {"label": "Rain", "unit": "mm", "source": "Open-Meteo Weather"},
    "surface_pressure": {"label": "Air pressure (at station)", "unit": "hPa", "source": "Open-Meteo Weather"},
    "pressure_msl": {"label": "Air pressure", "unit": "hPa", "source": "Open-Meteo Weather"},
    "wind_speed_10m": {"label": "Wind speed", "unit": "kn", "source": "Open-Meteo Weather"},
    "wind_direction_10m": {"label": "Wind comes from", "unit": "°", "source": "Open-Meteo Weather"},
    "wind_gusts_10m": {"label": "Wind gusts", "unit": "kn", "source": "Open-Meteo Weather"},
    "cloud_cover": {"label": "Cloud cover", "unit": "%", "source": "Open-Meteo Weather"},
    "weather_code": {"label": "Sky conditions", "unit": "", "source": "Open-Meteo Weather"},
}

# Variables that anomaly detection / forecasting can run on
ANALYSIS_VARIABLES = [
    "sea_level_height_msl", "sea_surface_temperature", "pressure_msl",
    "wind_speed_10m", "wave_height", "temperature_2m",
]

PERIODS: dict[str, int | None] = {
    "24 hours": 1, "7 days": 7, "30 days": 30, "3 months": 90, "1 year": 365,
    "All available": None,
}

# Map regions for the hurricane tracker (None = auto-fit to the active storms)
MAP_REGIONS: dict[str, dict | None] = {
    "Auto - where the storms are": None,
    "World (all active storms)": {"lat": 15.0, "lon": 20.0, "zoom": 1.1},
    "Atlantic basin": {"lat": 25.0, "lon": -55.0, "zoom": 3.0},
    "Caribbean Sea": {"lat": 15.5, "lon": -75.0, "zoom": 4.7},
    "Gulf of Mexico": {"lat": 25.0, "lon": -90.0, "zoom": 5.0},
    "U.S. East Coast & Western Atlantic": {"lat": 32.0, "lon": -70.0, "zoom": 4.2},
    "Eastern Pacific": {"lat": 16.0, "lon": -112.0, "zoom": 3.6},
    "Central Pacific / Hawaii": {"lat": 17.0, "lon": -157.0, "zoom": 4.2},
    "West Pacific & Asia": {"lat": 20.0, "lon": 130.0, "zoom": 3.0},
    "North Indian Ocean": {"lat": 15.0, "lon": 75.0, "zoom": 3.6},
    "South Indian Ocean": {"lat": -18.0, "lon": 70.0, "zoom": 3.2},
    "Australia & South Pacific (Oceania)": {"lat": -18.0, "lon": 160.0, "zoom": 2.7},
    "Around Providencia & Santa Catalina": {"lat": 13.34, "lon": -81.37, "zoom": 5.6},
}

# Distance rings drawn around the reference point on maps (km)
RINGS_KM = (250, 500, 1000)


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a credential from st.secrets, then environment variables.

    Never hard-code keys: none are needed for the MVP, but every service
    uses this helper so adding a keyed source later is trivial.
    """
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file / not running under Streamlit
        pass
    return os.environ.get(name, default)
