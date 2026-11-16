"""Reader-friendly charts: colour-coded zones, 'Now' marker, gauges, compass, normal-range bands."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from analytics.cyclones import CATEGORY_COLORS
from utils.config import PALETTE
from utils.coordinates import deg_to_cardinal
from utils.formatting import to_local
from utils.plain import KN_TO_MPH, cardinal_name
from utils.ui import style_fig

ZONE_COLORS = [PALETTE["palm"], PALETTE["sun"], PALETTE["papaya"], PALETTE["coral"]]


def rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def _py(ts):
    return pd.Timestamp(ts).to_pydatetime()


def mark_now(fig: go.Figure, now, x_end=None) -> None:
    """Dotted 'Now' line + soft shading for the forecast part of the chart."""
    x = _py(to_local(now))
    fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper", line=dict(color=PALETTE["sun"], width=2, dash="dot"))
    fig.add_annotation(x=x, y=1.0, yref="paper", text="Now", showarrow=False, yanchor="bottom", font=dict(color=PALETTE["sun"], size=12))
    if x_end is not None:
        fig.add_shape(type="rect", x0=x, x1=_py(x_end), y0=0, y1=1, yref="paper", fillcolor="rgba(255,255,255,0.05)", line_width=0, layer="below")
        fig.add_annotation(x=x, y=0.0, yref="paper", text=" Forecast →", showarrow=False, xanchor="left", yanchor="bottom",
                           font=dict(color=PALETTE["muted"], size=11))


def add_zones(fig: go.Figure, limits: list[float], labels: list[str], ymax: float) -> None:
    """Coloured horizontal bands (green/yellow/orange/red) with plain labels on the right edge."""
    edges = [0.0] + list(limits) + [max(ymax, limits[-1] * 1.2)]
    for i in range(4):
        lo, hi = edges[i], edges[i + 1]
        fig.add_hrect(y0=lo, y1=hi, fillcolor=rgba(ZONE_COLORS[i], 0.13), line_width=0, layer="below")
        if lo < ymax:
            mid = (lo + min(hi, ymax)) / 2
            fig.add_annotation(xref="paper", x=1.005, y=mid, text=labels[i], showarrow=False, xanchor="left",
                               font=dict(color=ZONE_COLORS[i], size=11))


def zone_line_chart(series: dict[str, pd.Series], limits: list[float], labels: list[str], unit: str, title: str, now=None,
                    height: int = 340, colors: list[str] | None = None) -> go.Figure | None:
    """Line chart over colour-coded zones so anybody can see 'calm / caution / rough / dangerous'."""
    series = {k: v.dropna() for k, v in series.items() if v is not None and v.notna().any()}
    if not series:
        return None
    colors = colors or [PALETTE["sky"], PALETTE["aqua"]]
    fig = go.Figure()
    for (name, s), c in zip(series.items(), colors):
        fig.add_scatter(x=to_local(s.index), y=s, name=name, mode="lines", line=dict(color=c, width=3 if name == next(iter(series)) else 2))
    top = max(float(s.max()) for s in series.values()) * 1.25
    ymax = max(top, limits[1] * 1.15)
    add_zones(fig, limits, labels, ymax)
    fig.update_yaxes(range=[0, ymax], title=unit)
    fig.update_layout(margin=dict(r=110))
    if now is not None:
        x_end = max(s.index.max() for s in series.values())
        mark_now(fig, now, x_end if x_end > pd.Timestamp(now) else None)
    return style_fig(fig, title, height)


def gauge(value: float | None, limits: list[float], unit: str, title: str, vmax: float, decimals: int = 1) -> go.Figure | None:
    if value is None or pd.isna(value):
        return None
    edges = [0.0] + list(limits) + [vmax]
    steps = [{"range": [edges[i], edges[i + 1]], "color": rgba(ZONE_COLORS[i], 0.55)} for i in range(4)]
    fig = go.Figure(go.Indicator(mode="gauge+number", value=float(value), number=dict(suffix=f" {unit}", valueformat=f".{decimals}f", font=dict(size=30)),
                                 title=dict(text=title, font=dict(size=14)),
                                 gauge=dict(axis=dict(range=[0, vmax], tickcolor=PALETTE["muted"]), bar=dict(color="#ffffff", thickness=0.28),
                                            steps=steps, borderwidth=0)))
    fig.update_layout(height=210, margin=dict(l=20, r=20, t=50, b=5), paper_bgcolor="rgba(0,0,0,0)", font=dict(color=PALETTE["text"]))
    return fig


def compass(direction: float | None, title: str = "Wind comes from") -> go.Figure | None:
    if direction is None or pd.isna(direction):
        return None
    fig = go.Figure(go.Barpolar(r=[1], theta=[float(direction)], width=[26], marker=dict(color=PALETTE["turquoise"], line=dict(color="white", width=1)),
                                hovertemplate=f"{deg_to_cardinal(direction)} ({direction:.0f}°)<extra></extra>"))
    fig.update_layout(height=210, margin=dict(l=30, r=30, t=50, b=15), paper_bgcolor="rgba(0,0,0,0)", font=dict(color=PALETTE["text"]),
                      title=dict(text=f"{title}<br><b>{cardinal_name(direction)}</b> ({direction:.0f}°)", font=dict(size=14)),
                      polar=dict(bgcolor="rgba(255,255,255,0.04)", radialaxis=dict(visible=False, range=[0, 1]),
                                 angularaxis=dict(direction="clockwise", rotation=90, tickmode="array", tickvals=[0, 90, 180, 270],
                                                  ticktext=["N", "E", "S", "W"], gridcolor="rgba(125,243,232,.25)")))
    return fig


# Saffir-Simpson zones in mph (NHC)
CAT_ZONES = [(0, 39, "Tropical Depression"), (39, 74, "Tropical Storm"), (74, 96, "Category 1"), (96, 111, "Category 2"),
             (111, 130, "Category 3"), (130, 157, "Category 4"), (157, 220, "Category 5")]
_CAT_KEYS = ["Tropical Depression", "Tropical Storm", "Cat 1", "Cat 2", "Cat 3", "Cat 4", "Cat 5"]


def add_category_zones(fig: go.Figure, ymax_mph: float) -> None:
    for (lo, hi, label), key in zip(CAT_ZONES, _CAT_KEYS):
        if lo > ymax_mph:
            break
        c = CATEGORY_COLORS[key]
        fig.add_hrect(y0=lo, y1=min(hi, ymax_mph), fillcolor=rgba(c, 0.14), line_width=0, layer="below")
        fig.add_annotation(xref="paper", x=1.005, y=(lo + min(hi, ymax_mph)) / 2, text=label, showarrow=False, xanchor="left", font=dict(color=c, size=10))


def intensity_chart(x, wind_kt, title: str, xtitle: str, height: int = 320) -> go.Figure | None:
    w = pd.Series(list(wind_kt), dtype=float) * KN_TO_MPH
    if w.notna().sum() < 2:
        return None
    fig = go.Figure(go.Scatter(x=list(x), y=w, mode="lines+markers", line=dict(color="#ffffff", width=3), marker=dict(size=8), name="Max sustained wind"))
    ymax = max(120.0, float(w.max()) * 1.15)
    add_category_zones(fig, ymax)
    fig.update_yaxes(range=[0, ymax], title="Wind speed (mph)")
    fig.update_xaxes(title=xtitle)
    fig.update_layout(margin=dict(r=120))
    return style_fig(fig, title, height, legend=False)


def anomaly_chart(res: pd.DataFrame, label: str, unit: str, height: int = 380) -> go.Figure:
    """Line inside a green 'normal range' band; yellow/red dots mark unusual readings."""
    t = to_local(res.index)
    fig = go.Figure()
    fig.add_scatter(x=t, y=res["upper"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=t, y=res["lower"], line=dict(width=0), fill="tonexty", fillcolor=rgba(PALETTE["palm"], 0.20), name="Normal range", hoverinfo="skip")
    fig.add_scatter(x=t, y=res["typical"], line=dict(color=PALETTE["palm"], width=1, dash="dash"), name="Usual level")
    fig.add_scatter(x=t, y=res["value"], line=dict(color=PALETTE["sky"], width=2.5), name=label)
    for lv, name, c, size in ((1, "Unusual", PALETTE["sun"], 8), (2, "Very unusual", PALETTE["coral"], 11)):
        m = res[res["level"] == lv]
        fig.add_scatter(x=to_local(m.index), y=m["value"], mode="markers", name=name, marker=dict(color=c, size=size, line=dict(color="white", width=1)))
    fig.update_yaxes(title=unit)
    return style_fig(fig, f"{label}: is it inside the normal range?", height)
