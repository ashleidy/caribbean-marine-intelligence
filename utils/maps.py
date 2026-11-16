"""Plotly map builders (MapLibre). Realistic NASA satellite imagery basemap, hover/tap details on every object.

Basemaps (all free, no API key):
  * Satellite (NASA, live) - NASA GIBS VIIRS true-colour mosaic of yesterday (UTC): real clouds, green land, blue ocean.
  * Light ocean / Dark     - Carto vector styles built into Plotly.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from analytics.cyclones import CATEGORY_COLORS, category_from_wind
from services.noaa_nhc import WW_COLORS, WW_LABELS
from utils.config import LOCATIONS, PALETTE, RINGS_KM, Location
from utils.coordinates import circle_coords, deg_to_cardinal
from utils.plain import KM_TO_MI, KN_TO_MPH, cardinal_name

STYLES = ["Satellite (NASA, live)", "Light ocean", "Dark"]
GIBS_URL = ("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/"
            "{date}/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.jpg")
THEMES = {
    "Satellite (NASA, live)": dict(base="carto-voyager", text="#FFFFFF", halo="#06222F", track="#FFFFFF", cone_fill="rgba(255,255,255,0.22)",
                                   cone_line="#FFFFFF", past="#DCE6EE", ring="#7DF3E8", sat=True),
    "Light ocean": dict(base="carto-voyager", text="#0A1F33", halo="#FFFFFF", track="#0F1A2D", cone_fill="rgba(255,255,255,0.45)",
                        cone_line="#1E3C64", past="#46506A", ring="#0E7490", sat=False),
    "Dark": dict(base="carto-darkmatter", text="#FFFFFF", halo="#000000", track="#FFFFFF", cone_fill="rgba(255,255,255,0.18)",
                 cone_line="#FFFFFF", past="#D2D2D2", ring="#7DF3E8", sat=False),
}


def satellite_date() -> str:
    """Latest complete daily mosaic = yesterday (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def fit_view(lats, lons, min_zoom: float = 1.0, max_zoom: float = 6.0) -> tuple[float, float, float]:
    """Centre and zoom that frame all points with padding (works from one storm up to the whole world)."""
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    ok = ~(np.isnan(lats) | np.isnan(lons))
    lats, lons = lats[ok], lons[ok]
    if not len(lats):
        return 20.0, -40.0, 1.5
    span = max(lats.max() - lats.min(), (lons.max() - lons.min()) * 0.55, 6.0) * 1.35
    zoom = float(np.clip(math.log2(700.0 / span), min_zoom, max_zoom))
    return float((lats.max() + lats.min()) / 2), float((lons.max() + lons.min()) / 2), zoom


def base_fig(style: str, lat: float, lon: float, zoom: float, height: int = 640, revision: str = "") -> go.Figure:
    th = THEMES.get(style, THEMES["Satellite (NASA, live)"])
    layers = []
    if th["sat"]:
        layers.append(dict(sourcetype="raster", source=[GIBS_URL.format(date=satellite_date())], below="traces", opacity=1.0,
                           sourceattribution="Imagery: NASA GIBS / VIIRS (SNPP)"))
    fig = go.Figure(go.Scattermap(lon=[lon], lat=[lat], mode="markers", marker=dict(size=1, opacity=0), hoverinfo="skip", showlegend=False))
    fig.update_layout(map=dict(style=th["base"], center=dict(lat=lat, lon=lon), zoom=zoom, layers=layers), height=height,
                      margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", hovermode="closest",
                      hoverlabel=dict(bgcolor="#0B3A4F", bordercolor="#14D9C4", font=dict(color="#E6F7FA", size=13)),
                      uirevision=f"{revision}|{style}")
    return fig


# ---------------------------------------------------------------------------- primitives
def _dots(fig, lon, lat, colors, size, th, hover=None, ids=None, text=None, textpos="top center", textsize=13, halo=5):
    fig.add_trace(go.Scattermap(lon=list(lon), lat=list(lat), mode="markers", marker=dict(size=size + halo, color=th["halo"]), hoverinfo="skip", showlegend=False))
    custom = None
    if hover is not None:
        custom = [[h, (ids[i] if ids is not None else "")] for i, h in enumerate(hover)]
    fig.add_trace(go.Scattermap(lon=list(lon), lat=list(lat), mode="markers+text" if text is not None else "markers", marker=dict(size=size, color=colors),
                                text=text, textposition=textpos, textfont=dict(size=textsize, color=th["text"]), customdata=custom,
                                hovertemplate="%{customdata[0]}<extra></extra>" if custom is not None else None,
                                hoverinfo=None if custom is not None else "skip", showlegend=False))


def _line(fig, lon, lat, color, width, halo=None, hover=None, dash=None):
    if halo:
        fig.add_trace(go.Scattermap(lon=lon, lat=lat, mode="lines", line=dict(width=width + 3, color=halo), opacity=0.55, hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scattermap(lon=lon, lat=lat, mode="lines", line=dict(width=width, color=color), hovertemplate=(hover + "<extra></extra>") if hover else None,
                                hoverinfo=None if hover else "skip", showlegend=False))


def _geom_lines(geom):
    t = geom.geom_type
    if t == "LineString":
        yield list(geom.coords)
    elif t in ("MultiLineString", "GeometryCollection"):
        for g in geom.geoms:
            yield from _geom_lines(g)


def _geom_rings(geom):
    t = geom.geom_type
    if t == "Polygon":
        yield list(geom.exterior.coords)
    elif t in ("MultiPolygon", "GeometryCollection"):
        for g in geom.geoms:
            yield from _geom_rings(g)


def _flatten(parts):
    lon, lat = [], []
    for part in parts:
        lon += [c[0] for c in part] + [None]
        lat += [c[1] for c in part] + [None]
    return lon, lat


# ---------------------------------------------------------------------------- reference points
def add_rings(fig, center: Location, style: str) -> None:
    th = THEMES[style]
    for r in RINGS_KM:
        c = circle_coords(center.lat, center.lon, r)
        fig.add_trace(go.Scattermap(lon=[p[0] for p in c], lat=[p[1] for p in c], mode="lines", line=dict(width=1.5, color=th["ring"]),
                                    hovertemplate=f"{r} km ({r * KM_TO_MI:.0f} mi) from {center.name}<extra></extra>", showlegend=False))


def add_locations(fig, selected: Location, style: str, include_refs: bool = False) -> None:
    th = THEMES[style]
    for l in LOCATIONS.values():
        if l.name == selected.name or l.kind == "primary" or include_refs:
            main = l.name == selected.name
            _dots(fig, [l.lon], [l.lat], [PALETTE["turquoise"] if main else PALETTE["sky"]], 8 if main else 6, th,
                  hover=[f"<b>{l.name}</b><br>{l.lat:.2f}°, {l.lon:.2f}°<br>{l.note}"], text=[l.name], textpos="bottom center", textsize=12, halo=4)


# ---------------------------------------------------------------------------- cyclones
def cat_color(kt) -> str:
    return CATEGORY_COLORS[category_from_wind(kt)]


def add_forecast_pkg(fig, pkg: dict | None, style: str) -> None:
    """NHC cone (translucent), official watches/warnings and forecast track line."""
    if not pkg:
        return
    th = THEMES[style]
    if pkg.get("cone") is not None:
        lon, lat = _flatten(r for g in pkg["cone"].geometry for r in _geom_rings(g))
        fig.add_trace(go.Scattermap(lon=lon, lat=lat, mode="lines", fill="toself", fillcolor=th["cone_fill"], line=dict(width=2, color=th["cone_line"]),
                                    hoverinfo="skip", showlegend=False))
    w = pkg.get("warnings")
    if w is not None and len(w):
        col = next((c for c in w.columns if c.lower() == "tcww"), None)
        for i, g in enumerate(w.geometry):
            code = str(w[col].iloc[i]) if col else ""
            rgba = WW_COLORS.get(code, [255, 255, 255, 230])
            lon, lat = _flatten(_geom_lines(g))
            _line(fig, lon, lat, f"rgba({rgba[0]},{rgba[1]},{rgba[2]},0.95)", 8, hover=f"<b>{WW_LABELS.get(code, code or 'Watch/Warning')}</b><br>Official NOAA NHC product")
    if pkg.get("track_line") is not None:
        lon, lat = _flatten(p for g in pkg["track_line"].geometry for p in _geom_lines(g))
        _line(fig, lon, lat, th["track"], 3, halo=th["halo"])


def add_forecast_points(fig, fc: pd.DataFrame | None, style: str, storm_name: str = "") -> None:
    if fc is None or fc.empty:
        return
    th = THEMES[style]
    d = fc[fc["tau_h"].fillna(0) > 0] if "tau_h" in fc else fc
    if d.empty:
        return
    def hov(r):
        w = f"{r['wind_kt'] * KN_TO_MPH:.0f} mph · {category_from_wind(r['wind_kt']).replace('Cat ', 'Category ')}" if pd.notna(r.get("wind_kt")) else "wind: data unavailable"
        return f"<b>{storm_name} - forecast</b><br>{r.get('label', '')}<br>{w}<br>{r.get('tau_h', float('nan')):+.0f} h from now"
    colors = [cat_color(k) if pd.notna(k) else PALETTE["muted"] for k in d["wind_kt"]]
    _dots(fig, d["lon"], d["lat"], colors, 9, th, hover=[hov(r) for _, r in d.iterrows()], text=list(d["label"].astype(str)), textpos="top center", textsize=11, halo=4)


def add_past_track(fig, pts: pd.DataFrame | None, style: str, storm_name: str = "") -> None:
    if pts is None or len(pts) < 2:
        return
    th = THEMES[style]
    _line(fig, list(pts["lon"]), list(pts["lat"]), th["past"], 3, halo=th["halo"])
    colors = [cat_color(k) if pd.notna(k) else PALETTE["muted"] for k in pts["wind_kt"]]
    def hov(r):
        t = pd.Timestamp(r["time"]).strftime("%d %b %H:%M UTC") if pd.notna(r.get("time")) else ""
        w = f"{r['wind_kt'] * KN_TO_MPH:.0f} mph" if pd.notna(r.get("wind_kt")) else "wind: n/a"
        return f"<b>{storm_name} - past position</b><br>{t}<br>{w}"
    _dots(fig, pts["lon"], pts["lat"], colors, 6, th, hover=[hov(r) for _, r in pts.iterrows()], halo=3)


def storm_hover(r: pd.Series, ref_name: str | None = None) -> str:
    kt = r.get("intensity_kt")
    cat = category_from_wind(kt).replace("Cat ", "Category ") if pd.notna(kt) else "n/a"
    lines = [f"<b>{str(r['name']).upper()}</b>", f"{r.get('classification_label', '')}" + (f" · {cat}" if pd.notna(kt) and cat not in str(r.get('classification_label')) else "")]
    lines.append(f"Wind: {kt * KN_TO_MPH:.0f} mph ({kt:.0f} kt)" if pd.notna(kt) else "Wind: data unavailable")
    if pd.notna(r.get("pressure_mb")):
        lines.append(f"Pressure: {r['pressure_mb']:.0f} mb")
    if pd.notna(r.get("movement_speed_mph")):
        lines.append(f"Moving {cardinal_name(r.get('movement_dir_deg'))} at {r['movement_speed_mph']:.0f} mph")
    if ref_name and pd.notna(r.get("distance_km")):
        lines.append(f"{r['distance_km']:,.0f} km ({r['distance_km'] * KM_TO_MI:,.0f} mi) from {ref_name}")
    lines.append(f"{r.get('basin', '')} · source: {r.get('source', 'NOAA NHC')}")
    lines.append("<i>Tap/click for details below</i>")
    return "<br>".join(str(x) for x in lines if x)


def add_storm_markers(fig, storms: pd.DataFrame, style: str, ref_name: str | None = None) -> None:
    """Large category-coloured marker + name for each storm. customdata[1] = storm id (click selection)."""
    if storms is None or storms.empty:
        return
    th = THEMES[style]
    colors = [cat_color(k) if pd.notna(k) else PALETTE["muted"] for k in storms["intensity_kt"]]
    _dots(fig, storms["lon"], storms["lat"], colors, 19, th, hover=[storm_hover(r, ref_name) for _, r in storms.iterrows()], ids=list(storms["id"]),
          text=[str(n).upper() for n in storms["name"]], textpos="top center", textsize=14, halo=6)


def add_tracks(fig, h: pd.DataFrame, max_tracks: int = 400) -> None:
    """Historical HURDAT2 tracks: one trace per peak category (fast) with name/year on hover."""
    groups: dict[str, list] = {}
    for sid, g in list(h.groupby("storm_id", sort=False))[:max_tracks]:
        groups.setdefault(category_from_wind(g["wind_kt"].max()), []).append(g)
    for cat, items in groups.items():
        lon, lat, text = [], [], []
        for g in items:
            label = f"<b>{g['name'].iloc[0]} {int(g['year'].iloc[0])}</b><br>Peak: {cat.replace('Cat ', 'Category ')}"
            lon += list(g["lon"]) + [None]; lat += list(g["lat"]) + [None]; text += [label] * len(g) + [None]
        fig.add_trace(go.Scattermap(lon=lon, lat=lat, mode="lines", line=dict(width=2, color=CATEGORY_COLORS[cat]), opacity=0.8, text=text,
                                    hovertemplate="%{text}<extra></extra>", showlegend=False))


# ---------------------------------------------------------------------------- legends
_CAT_MPH = [("Tropical Depression", "under 39 mph"), ("Tropical Storm", "39-73 mph"), ("Cat 1", "74-95 mph"), ("Cat 2", "96-110 mph"),
            ("Cat 3", "111-129 mph"), ("Cat 4", "130-156 mph"), ("Cat 5", "157+ mph")]


def category_legend_html() -> str:
    items = [f"<span style='white-space:nowrap;margin-right:12px'><span style='color:{CATEGORY_COLORS[k]};font-size:1.2em'>●</span> "
             f"<b>{k.replace('Cat ', 'Category ')}</b> <span style='opacity:.7'>({v})</span></span>" for k, v in _CAT_MPH]
    return " ".join(items)


def ww_legend_html() -> str:
    return " ".join(f"<span style='color:rgb({','.join(map(str, c[:3]))});font-size:1.2em'>■</span> {WW_LABELS[k]}" for k, c in WW_COLORS.items())
