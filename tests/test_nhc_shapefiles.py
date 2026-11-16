"""Build an NHC-style advisory zip (same file suffixes/fields) and run it through the real parsing path."""
import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

import services.noaa_nhc as nhc


def _zip_bytes(tmp: Path) -> bytes:
    pts = gpd.GeoDataFrame({"TAU": [0, 12, 24], "MAXWIND": [80, 90, 95], "GUST": [100, 110, 115], "MSLP": [975, 970, 965],
                            "TCDVLP": ["Hurricane"] * 3, "DATELBL": ["8 PM Mon", "8 AM Tue", "8 PM Tue"]},
                           geometry=[Point(-78, 16), Point(-79.5, 15), Point(-81, 14)], crs=4326)
    lin = gpd.GeoDataFrame({"STORMNAME": ["TESTA"]}, geometry=[LineString([(-78, 16), (-79.5, 15), (-81, 14)])], crs=4326)
    cone = gpd.GeoDataFrame({"STORMNAME": ["TESTA"]}, geometry=[Polygon([(-77, 17), (-82, 15), (-80, 12), (-76, 15)])], crs=4326)
    ww = gpd.GeoDataFrame({"TCWW": ["HWR"]}, geometry=[LineString([(-82, 14), (-80, 13)])], crs=4326)
    for name, g in (("al092026_5day_pts", pts), ("al092026_5day_lin", lin), ("al092026_5day_pgn", cone), ("al092026_ww_wwlin", ww)):
        g.to_file(tmp / f"{name}.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in tmp.iterdir():
            zf.write(f, f.name)
    return buf.getvalue()


def test_forecast_package_roundtrip(tmp_path, monkeypatch):
    content = _zip_bytes(tmp_path)
    class R: pass
    r = R(); r.content = content
    monkeypatch.setattr(nhc, "http_get", lambda *a, **k: r)
    pkg = nhc.fetch_forecast_package("https://example/x.zip")
    assert all(pkg[k] is not None for k in ("cone", "track_line", "points", "warnings"))
    fc = nhc.normalize_forecast_points(pkg["points"])
    assert fc["wind_kt"].tolist() == [80, 90, 95] and fc["tau_h"].tolist() == [0, 12, 24]
    assert pkg["warnings"]["TCWW"].iloc[0] == "HWR"
    from utils import maps
    fig = maps.base_fig("Dark", 15, -80, 4, 500)
    n0 = len(fig.data)
    maps.add_forecast_pkg(fig, pkg, "Dark")
    assert len(fig.data) - n0 == 4          # cone + warning line (halo-less) + track halo + track line


def test_full_app_navigation_boots(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import services.base as base
    monkeypatch.setattr(base, "http_get", lambda *a, **k: (_ for _ in ()).throw(base.SourceError("offline")))
    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "app.py"), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]


def test_storm_without_numeric_coordinates_is_parsed_or_dropped(monkeypatch):
    payload = {"activeStorms": [
        {"id": "al012026", "name": "Ana", "classification": "TS", "intensity": "50", "pressure": "1000", "latitude": "21.3N", "longitude": "75.4W"},
        {"id": "al022026", "name": "Ghost", "classification": "TS", "intensity": "40", "pressure": "1004"}]}
    monkeypatch.setattr(nhc, "http_get_json", lambda *a, **k: payload)
    df = nhc.fetch_active_storms()
    assert df["name"].tolist() == ["Ana"] and df["lat"].iloc[0] == 21.3 and df["lon"].iloc[0] == -75.4
