"""Structural checks on charts/maps + hurricane page with a full simulated NHC package."""
import io, json, zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon
from streamlit.testing.v1 import AppTest

from analytics.anomalies import detect, plain_summary
from tests.test_pages_with_data import fake_marine, fake_storms, fake_weather
from utils import maps
from utils.charts import anomaly_chart, compass, gauge, intensity_chart, zone_line_chart
from utils.config import LOCATIONS, PRIMARY
from tests.test_pages_with_data import fake_gdacs_events

ROOT = Path(__file__).resolve().parents[1]


def test_charts_build_and_have_expected_parts():
    now = pd.Timestamp.now(tz="UTC").floor("h")
    m = fake_marine(13, -81)
    f = zone_line_chart({"Wave height": m["wave_height"]}, [1, 2, 3], ["a", "b", "c", "d"], "m", "t", now)
    assert len(f.layout.shapes) >= 4 and any(a.text == "Now" for a in f.layout.annotations)   # zones + Now marker
    assert zone_line_chart({}, [1, 2, 3], list("abcd"), "m", "t") is None
    assert gauge(1.2, [1, 2, 3], "m", "x", 4).data[0].gauge.steps.__len__() == 4 and gauge(None, [1, 2, 3], "m", "x", 4) is None
    assert compass(90) is not None and compass(None) is None
    assert intensity_chart([0, 12, 24], [60, 80, 100], "t", "x") is not None
    w = fake_weather(13, -81)["temperature_2m"]
    w = w[w.index <= now].copy()
    w.iloc[-50:-40] += 12
    res = detect(w, "rolling_z")
    assert (res["level"] > 0).any() and {"lower", "upper", "typical"} <= set(res.columns)
    assert len(anomaly_chart(res.tail(500), "Air temperature", "°C").data) >= 5


def test_plain_summary_is_readable():
    now = pd.Timestamp.now(tz="UTC").floor("h")
    s = fake_weather(13, -81)["temperature_2m"]
    s = s[s.index <= now].copy(); s.iloc[-1] += 15
    ps = plain_summary(detect(s, "rolling_z"), "Air temperature", "°C")
    assert ps["lay"] in ("Unusual", "Very unusual") and "above the usual level" in ps["text"]


def test_locations_only_providencia_primary():
    assert PRIMARY.name == "Providencia & Santa Catalina" and PRIMARY.name in LOCATIONS and sum("Santa Catalina" in k for k in LOCATIONS) == 1


def _pkg_zip(tmp: Path) -> bytes:
    pts = gpd.GeoDataFrame({"TAU": [0, 12, 24, 48], "MAXWIND": [80, 90, 100, 85], "GUST": [100, 110, 120, 105], "MSLP": [975, 970, 962, 970],
                            "TCDVLP": ["Hurricane"] * 4, "DATELBL": ["8 PM Mon", "8 AM Tue", "8 PM Tue", "8 PM Wed"]},
                           geometry=[Point(-78, 16), Point(-79.5, 15), Point(-81, 14), Point(-84, 13)], crs=4326)
    lin = gpd.GeoDataFrame({"S": ["T"]}, geometry=[LineString([(-78, 16), (-79.5, 15), (-81, 14), (-84, 13)])], crs=4326)
    cone = gpd.GeoDataFrame({"S": ["T"]}, geometry=[Polygon([(-77, 17), (-86, 14), (-84, 11), (-76, 15)])], crs=4326)
    ww = gpd.GeoDataFrame({"TCWW": ["HWR", "TWA"]}, geometry=[LineString([(-82, 14), (-80, 13)]), LineString([(-83, 13), (-85, 12)])], crs=4326)
    for n, g in (("al092026_5day_pts", pts), ("al092026_5day_lin", lin), ("al092026_5day_pgn", cone), ("al092026_ww_wwlin", ww)):
        g.to_file(tmp / f"{n}.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in tmp.iterdir():
            zf.write(f, f.name)
    return buf.getvalue()


def _best_zip(tmp: Path) -> bytes:
    t = pd.date_range("2026-10-05", periods=6, freq="12h", tz="UTC")
    pts = gpd.GeoDataFrame({"YEAR": t.year, "MONTH": t.month, "DAY": t.day, "HHMM": t.hour * 100, "INTENSITY": [40, 50, 60, 70, 75, 80],
                            "MSLP": [1000, 995, 990, 985, 980, 975]}, geometry=[Point(-70 - i, 18 - i * .4) for i in range(6)], crs=4326)
    pts.to_file(tmp / "al092026_pts.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in tmp.iterdir():
            zf.write(f, f.name)
    return buf.getvalue()


@pytest.mark.parametrize("region", ["Auto - where the storms are", "World (all active storms)", "West Pacific & Asia", "Caribbean Sea"])
@pytest.mark.parametrize("style", ["Satellite (NASA, live)", "Dark"])
def test_hurricane_page_full_package(tmp_path, monkeypatch, region, style):
    import services.noaa_nhc as nhc, streamlit as st, utils.data as data
    st.cache_data.clear()
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    fz, bz = _pkg_zip(tmp_path / "a"), _best_zip(tmp_path / "b")
    class R:  # fake response
        def __init__(self, c): self.content = c
    monkeypatch.setattr(nhc, "http_get", lambda url, *a, **k: R(fz if "forecast" in url else bz))
    def storms():
        d = fake_storms(); d["forecast_zip"] = "https://x/forecast.zip"; d["best_track_zip"] = "https://x/best.zip"
        d["discussion_url"] = "https://www.nhc.noaa.gov/"; return d
    monkeypatch.setattr(nhc, "fetch_active_storms", storms)
    monkeypatch.setattr(data.nhc, "fetch_active_storms", storms)
    from tests.test_pages_with_data import fake_gdacs_events, fake_gdacs_track
    monkeypatch.setattr(data.gdacs, "fetch_active_events", fake_gdacs_events)
    monkeypatch.setattr(data.gdacs, "fetch_track", fake_gdacs_track)
    at = AppTest.from_file(str(ROOT / "pages" / "hurricanes.py"), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]
    at.selectbox[0].select(region).run()
    at.radio[0].set_value(style).run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(m.value for m in at.markdown)
    assert "TESTA" in html and "Category 2" in html and "Hurricane" in html and "KOINU" in html


def test_plotly_maps_have_small_markers_hover_and_nasa_layer(tmp_path, monkeypatch):
    import services.noaa_nhc as nhc
    (tmp_path / "a").mkdir()
    class R: content = _pkg_zip(tmp_path / "a")
    monkeypatch.setattr(nhc, "http_get", lambda *a, **k: R())
    pkg = nhc.fetch_forecast_package("https://x/y.zip")
    fc = nhc.normalize_forecast_points(pkg["points"])
    storms = fake_storms().assign(distance_km=500.0, source="NOAA NHC")
    for style in maps.STYLES:
        fig = maps.base_fig(style, 15, -78, 4.5, 600, "t")
        maps.add_rings(fig, PRIMARY, style)
        maps.add_forecast_pkg(fig, pkg, style)
        maps.add_forecast_points(fig, fc, style, "TESTA")
        maps.add_locations(fig, PRIMARY, style)
        maps.add_storm_markers(fig, storms, style, PRIMARY.name)
        layers = fig.layout.map.layers
        assert (len(layers) == 1 and "VIIRS_SNPP_CorrectedReflectance_TrueColor" in layers[0].source[0] and "{z}/{y}/{x}" in layers[0].source[0]) == style.startswith("Satellite")
        assert max(t.marker.size for t in fig.data if t.marker.size and not isinstance(t.marker.size, (list, tuple))) <= 26   # no giant dots
        storm_tr = [t for t in fig.data if t.customdata is not None and any("TESTA" in str(c[0]) for c in t.customdata)]
        assert storm_tr and storm_tr[-1].customdata[0][1] == "al092026"          # click selection id
        fig.to_json()                                                              # serialisable


def test_gdacs_frame_and_basins():
    from services import gdacs
    ev = fake_gdacs_events()
    df = gdacs.to_storm_frame(ev)
    assert set(df["basin"]) == {"West Pacific", "South Indian", "Atlantic"} and df["name"].tolist()[0] == "Koinu"
    assert abs(df["intensity_kt"].iloc[0] - 130 / 1.852) < 0.01
    assert gdacs.in_nhc_area(16, -78) and not gdacs.in_nhc_area(18, 128) and not gdacs.in_nhc_area(-15, 75)


def test_gdacs_track_unit_check(monkeypatch):
    from services import gdacs
    detail = {"properties": {"impacts": [{"resource": {"timeline": "https://x/timeline"}}]}}
    items = [{"advisory_datetime": "01 Oct 2026 00:00", "actual": "True", "latitude": 10, "longitude": 130, "wind_speed": 120, "pressure": 980},
             {"advisory_datetime": "02 October 2026 00:00", "actual": "False", "latitude": 12, "longitude": 128, "wind_speed": 140, "pressure": 0}]
    monkeypatch.setattr(gdacs, "http_get_json", lambda url, params=None, **k: detail if "geteventdata" in url else {"channel": {"item": items}})
    ok = gdacs.fetch_track(1, 120.0)                    # matches the official km/h -> wind converted to knots
    assert ok["wind_known"] and abs(ok["observed"]["wind_kt"].iloc[0] - 120 / 1.852) < 0.01 and len(ok["forecast"]) == 1
    bad = gdacs.fetch_track(1, 55.0)                    # does not match -> wind left empty, never guessed
    assert not bad["wind_known"] and bad["observed"]["wind_kt"].isna().all()


def test_global_merge_prefers_nhc_inside_its_basins(monkeypatch):
    import streamlit as st, services.noaa_nhc as nhc, utils.data as data
    st.cache_data.clear()
    monkeypatch.setattr(data.nhc, "fetch_active_storms", fake_storms)
    monkeypatch.setattr(data.gdacs, "fetch_active_events", fake_gdacs_events)
    comb, n, g = data.load_all_storms(PRIMARY)
    names = set(comb.data["name"].str.upper())
    assert comb.ok and "TESTA" in names and "KOINU" in names and "ALFA" in names
    assert (comb.data["name"].str.upper() == "TESTA").sum() == 1             # GDACS duplicate of the NHC storm dropped
    # NHC down -> GDACS fills in, including the Atlantic storm
    monkeypatch.setattr(data.nhc, "fetch_active_storms", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    st.cache_data.clear()
    comb2, n2, g2 = data.load_all_storms(PRIMARY)
    assert comb2.ok and not n2.ok and (comb2.data["name"].str.upper() == "TESTA").sum() == 1
