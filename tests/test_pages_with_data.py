"""Render every page with synthetic API data to exercise the data-rich code paths."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["dashboard", "hurricanes", "ocean", "weather", "sea_level", "analysis", "historical", "about"]


def _idx():
    now = pd.Timestamp.now(tz="UTC").floor("h")
    return pd.date_range(now - pd.Timedelta(days=92), now + pd.Timedelta(days=7), freq="1h")


def fake_marine(lat, lon, **kw):
    i = _idx(); t = np.arange(len(i)); r = np.random.default_rng(0)
    df = pd.DataFrame({"wave_height": 1.2 + 0.4 * np.sin(t / 30) + r.normal(0, .05, len(i)), "wave_direction": 70.0, "wave_period": 6.0,
                       "wave_peak_period": 7.0, "swell_wave_height": 0.8, "swell_wave_direction": 80.0, "swell_wave_period": 8.0,
                       "sea_level_height_msl": 0.1 * np.sin(t * 2 * np.pi / 12.42) + r.normal(0, .01, len(i)),
                       "sea_surface_temperature": 28.5 + r.normal(0, .1, len(i)), "ocean_current_velocity": 1.5, "ocean_current_direction": 270.0}, index=i)
    df.index.name = "time"
    df.attrs.update(units={"ocean_current_velocity": "km/h"}, query_point=(lat, lon), offset_used=False)
    return df


def fake_weather(lat, lon, **kw):
    i = _idx(); t = np.arange(len(i)); r = np.random.default_rng(1)
    df = pd.DataFrame({"temperature_2m": 28 + np.sin(t * 2 * np.pi / 24), "relative_humidity_2m": 75.0, "precipitation": r.choice([0, 0, 0, 1.2], len(i)),
                       "rain": 0.0, "surface_pressure": 1010.0, "pressure_msl": 1012 + np.sin(t / 50), "wind_speed_10m": 14 + 3 * np.sin(t / 20),
                       "wind_direction_10m": 80.0, "wind_gusts_10m": 20.0, "cloud_cover": 40.0, "weather_code": 2.0}, index=i)
    df.index.name = "time"; df.attrs.update(units={})
    return df


def fake_gdacs_events():
    return pd.DataFrame([{"eventid": 1001, "name": "KOINU-26", "alert_level": "Orange", "severity_kmh": 130.0, "severity_text": "Typhoon (maximum wind speed of 130 km/h)",
                          "gdacs_source": "JTWC", "country": "Philippines", "lon": 128.0, "lat": 18.0, "from_date": "2026-10-05", "to_date": pd.Timestamp.now(tz="UTC").isoformat(),
                          "report_url": "https://www.gdacs.org/report.aspx?eventtype=TC&eventid=1001"},
                         {"eventid": 1002, "name": "ALFA-26", "alert_level": "Green", "severity_kmh": 90.0, "severity_text": "Tropical Storm", "gdacs_source": "JTWC",
                          "country": "", "lon": 75.0, "lat": -15.0, "from_date": "2026-10-06", "to_date": pd.Timestamp.now(tz="UTC").isoformat(), "report_url": None},
                         {"eventid": 1003, "name": "TESTA-26", "alert_level": "Red", "severity_kmh": 157.0, "severity_text": "Hurricane", "gdacs_source": "NOAA",
                          "country": "", "lon": -78.0, "lat": 16.0, "from_date": "2026-10-06", "to_date": pd.Timestamp.now(tz="UTC").isoformat(), "report_url": None}])


def fake_gdacs_track(eventid, ref_kmh=None):
    t = pd.date_range(pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=36), periods=7, freq="6h")
    obs = pd.DataFrame({"lat": 17 + np.arange(7) * .3, "lon": 130 - np.arange(7) * .6, "time": t, "wind_kt": 55 + np.arange(7) * 4.0, "gust_kt": np.nan, "pressure_mb": np.nan})
    ft = pd.date_range(pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=6), periods=5, freq="12h")
    fc = pd.DataFrame({"lat": 19 + np.arange(5) * .5, "lon": 126 - np.arange(5), "time": ft, "wind_kt": [80, 85, 80, 70, 60.0], "gust_kt": np.nan, "pressure_mb": np.nan})
    fc["tau_h"] = [6, 18, 30, 42, 54.0]; fc["label"] = ["Fri 12:00"] * 5; fc["status"] = ""; fc["ss_cat"] = np.nan
    return {"observed": obs, "forecast": fc, "wind_known": True}


def fake_storms():
    return pd.DataFrame([{"id": "al092026", "basin": "Atlantic", "name": "TESTA", "classification": "HU", "classification_label": "Hurricane",
                          "intensity_kt": 85.0, "pressure_mb": 975.0, "lat": 16.0, "lon": -78.0, "movement_dir_deg": 280.0, "movement_speed_mph": 12.0,
                          "movement_speed_kt": 10.4, "last_update": pd.Timestamp.now(tz="UTC"), "advisory_number": "10", "public_advisory_url": "https://www.nhc.noaa.gov/",
                          "forecast_advisory_url": None, "discussion_url": None, "graphics_url": None, "forecast_zip": None, "cone_zip": None,
                          "warnings_zip": None, "initial_wind_zip": None, "forecast_radii_zip": None, "best_track_zip": None, "surge_ww_kml": None,
                          "surge_flooding_zip": None}])


HURDAT = "".join(
    f"AL{n:02d}{y},   S{n}{y},  3,\n" + "".join(f"{y}0901, {h:02d}00,  , HU, {13 + k + n * .3:.1f}N,  {80 - k * 2 - n}.0W, {70 + 5 * k}, {980 - 4 * k},\n" for k, h in enumerate((0, 6, 12)))
    for y in (2000, 2005, 2010, 2020) for n in (1, 2))


@pytest.fixture(autouse=True)
def patch_sources(monkeypatch):
    import services.noaa_nhc as nhc, services.open_meteo_marine as om, services.open_meteo_weather as ow, streamlit as st
    import utils.data as data
    st.cache_data.clear()
    monkeypatch.setattr(data, "fetch_marine_near", fake_marine)
    monkeypatch.setattr(data, "fetch_weather", fake_weather)
    monkeypatch.setattr(nhc, "fetch_active_storms", fake_storms)
    monkeypatch.setattr(nhc, "fetch_hurdat_text", lambda: (HURDAT, "https://example/hurdat2-1851-2025-010126.txt"))
    monkeypatch.setattr(data.nhc, "fetch_active_storms", fake_storms)
    monkeypatch.setattr(data.gdacs, "fetch_active_events", fake_gdacs_events)
    monkeypatch.setattr(data.gdacs, "fetch_track", fake_gdacs_track)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_data(page):
    at = AppTest.from_file(str(ROOT / "pages" / f"{page}.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


def test_dashboard_shows_values_and_sources():
    at = AppTest.from_file(str(ROOT / "pages" / "dashboard.py"), default_timeout=120).run()
    html = " ".join(m.value for m in at.markdown)
    assert "Wave Height" in html and "Source: Open-Meteo Marine" in html and "TESTA" in html and "worldwide" in html
    at.button[[b.label for b in at.button].index("GENERATE MARINE REPORT")].click().run()
    assert not at.exception and "Marine Report" in " ".join(m.value for m in at.markdown)
