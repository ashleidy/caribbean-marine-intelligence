"""Offline unit tests (no network): geodesy, parsers, analytics."""
import numpy as np
import pandas as pd
import pytest

from analytics.anomalies import detect, latest_status
from analytics.cyclones import category_from_wind, closest_approach, intensity_trend, rank_active
from analytics.forecasting import backtest, forecast_series
from analytics.risk import evaluate
from analytics.statistics import describe, linear_trend
from services.noaa_nhc import parse_hurdat2
from services.open_meteo_marine import _parse
from utils.cache import ObservationStore
from utils.coordinates import bearing_deg, deg_to_cardinal, haversine_km

HURDAT = """AL092011,              IRENE,      3,
20110821, 0000,  , TS, 15.0N,  59.0W,  45, 1006, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999,
20110821, 0600,  , HU, 16.0N,  61.0W,  70,  990, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999,
20110821, 1200,  , HU, 17.5N,  63.0W, -99, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999,
"""


def test_haversine_known_distance():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.2)
    assert haversine_km(13.34, -81.37, 13.34, -81.37) == 0


def test_bearing_and_cardinal():
    assert bearing_deg(0, 0, 1, 0) == pytest.approx(0)
    assert bearing_deg(0, 0, 0, 1) == pytest.approx(90)
    assert deg_to_cardinal(45) == "NE" and deg_to_cardinal(None) == "—"


def test_hurdat_parser_handles_missing_and_hemispheres():
    df = parse_hurdat2(HURDAT)
    assert len(df) == 3 and df["lon"].iloc[0] == -59.0
    assert np.isnan(df["wind_kt"].iloc[2]) and df["pressure_mb"].iloc[0] == 1006
    assert df["year"].iloc[0] == 2011 and df["time"].dt.tz is not None


def test_saffir_simpson():
    assert [category_from_wind(k) for k in (20, 40, 70, 100, 140)] == ["Tropical Depression", "Tropical Storm", "Cat 1", "Cat 3", "Cat 5"]
    assert category_from_wind(None) == "Unknown"


def test_closest_approach_interpolates_between_fixes():
    ca = closest_approach([10.0, 16.0], [-81.37, -81.37], None, 13.34, -81.37)
    assert ca["min_km"] < 5  # coarse fixes are 330 km away; interpolation finds the pass


def test_rank_active_sorts_by_distance():
    st_ = pd.DataFrame({"lat": [20.0, 14.0], "lon": [-70.0, -80.0], "intensity_kt": [50, 80], "name": ["A", "B"]})
    r = rank_active(st_, 13.34, -81.37)
    assert r["name"].tolist() == ["B", "A"] and r["distance_km"].iloc[0] < 200


def test_intensity_trend():
    t = pd.date_range("2026-09-01", periods=5, freq="12h", tz="UTC")
    pts = pd.DataFrame({"time": t, "wind_kt": [40, 50, 60, 75, 90], "pressure_mb": [1000, 995, 990, 980, 970]})
    assert intensity_trend(pts)["label"] == "Intensifying"


def test_anomaly_detection_flags_spike():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(0, 1, 500), index=pd.date_range("2026-01-01", periods=500, freq="1h", tz="UTC"))
    s.iloc[-1] = 8.0
    for m in ("zscore", "rolling_z", "iqr", "percentile"):
        assert latest_status(s, method=m)["level"] >= 1, m
    assert latest_status(s.iloc[:-1], method="zscore")["level"] == 0


def test_risk_is_worst_factor_and_handles_missing():
    r = evaluate({"wave_height": 2.4, "wind_speed_10m": 10, "wind_gusts_10m": None})
    assert r.level == 2 and r.meta["label"] == "Difficult conditions"
    assert evaluate({}).level is None and evaluate({}).meta["label"] == "Data unavailable"


def test_trend_and_describe():
    s = pd.Series(np.arange(10.0), index=pd.date_range("2026-01-01", periods=10, freq="1D", tz="UTC"))
    assert linear_trend(s)["slope_per_day"] == pytest.approx(1.0)
    assert describe(s)["max"] == 9


def test_forecast_and_backtest_on_sinusoid():
    idx = pd.date_range("2026-01-01", periods=24 * 10, freq="1h", tz="UTC")
    s = pd.Series(np.sin(np.arange(len(idx)) * 2 * np.pi / 24) + np.random.default_rng(1).normal(0, 0.1, len(idx)), index=idx)
    for m in ("moving_average", "linear", "holt", "arima"):
        fc = forecast_series(s, 24, m)
        assert len(fc) == 24 and (fc["upper"] >= fc["lower"]).all()
    assert backtest(s, 24, "holt")["ok"]
    with pytest.raises(ValueError):
        forecast_series(s.iloc[:10], 12)


def test_open_meteo_parser_validates_and_dedupes():
    payload = {"hourly": {"time": ["2026-01-01T00:00", "2026-01-01T00:00", "2026-01-01T01:00"], "wave_height": [1.0, 1.2, None]},
               "hourly_units": {"wave_height": "m"}}
    df = _parse(payload)
    assert len(df) == 2 and df["wave_height"].iloc[0] == 1.2 and np.isnan(df["wave_height"].iloc[1])
    with pytest.raises(Exception):
        _parse({"nothing": 1})


def test_store_is_idempotent(tmp_path):
    s = ObservationStore(tmp_path / "t.sqlite")
    df = pd.DataFrame({"wave_height": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2, freq="1h", tz="UTC"))
    s.upsert_wide(df, "X", "src"); s.upsert_wide(df * 2, "X", "src")
    out = s.read_wide("X", "src")
    assert len(out) == 2 and out["wave_height"].tolist() == [2.0, 4.0]
