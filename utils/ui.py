"""Look & feel: tropical-blue CSS, cards, chips, Plotly styling, sidebar, width-compat helpers."""
from __future__ import annotations

import copy
import html
import inspect

import plotly.graph_objects as go
import streamlit as st
from packaging.version import Version

from analytics.risk import DEFAULT_THRESHOLDS
from services.base import FetchResult
from utils.config import (APP_NAME, APP_SUBTITLE, COLORWAY, DEFAULT_LOCATION, DISCLAIMER, LOCATIONS, PALETTE,
                          PRIMARY, UNAVAILABLE, Location)

P = PALETTE
_NEW_ST = Version(st.__version__.split("+")[0]) >= Version("1.50.0")

CSS = f"""
<style>
.stApp {{background:
  radial-gradient(1100px 520px at 8% -8%, rgba(20,217,196,.20), transparent 60%),
  radial-gradient(900px 500px at 100% 0%, rgba(56,189,248,.18), transparent 55%),
  radial-gradient(700px 400px at 50% 110%, rgba(255,200,87,.07), transparent 60%),
  linear-gradient(180deg,{P['deep']} 0%,{P['abyss']} 100%);}}
[data-testid="stSidebar"] {{background:linear-gradient(180deg,#073447 0%,{P['abyss']} 100%);border-right:1px solid rgba(125,243,232,.15);}}
#MainMenu, footer {{visibility:hidden;}}
.block-container {{padding-top:1.4rem; max-width:1280px;}}
h1,h2,h3 {{letter-spacing:.2px;}}
.hero {{position:relative;overflow:hidden;border-radius:20px;padding:26px 30px;margin-bottom:14px;
  background:linear-gradient(120deg,{P['ocean']} 0%,{P['lagoon']} 52%,#12B5A6 100%);
  border:1px solid rgba(125,243,232,.35);box-shadow:0 10px 30px rgba(0,0,0,.35);}}
.hero:after {{content:"";position:absolute;right:-60px;top:-70px;width:240px;height:240px;border-radius:50%;
  background:radial-gradient(circle at 35% 35%,{P['sun']} 0%,{P['papaya']} 45%,rgba(255,107,107,0) 72%);opacity:.55;}}
.hero h1 {{margin:0;font-size:1.9rem;font-weight:800;letter-spacing:2.5px;color:#fff;}}
.hero .loc {{font-size:1.15rem;color:{P['aqua']};font-weight:600;margin-top:2px;}}
.hero .sub {{font-size:.86rem;color:#d6f4f4;max-width:760px;margin-top:6px;opacity:.92;}}
.card {{background:rgba(255,255,255,.045);border:1px solid rgba(125,243,232,.16);border-radius:16px;
  padding:14px 16px;min-height:132px;position:relative;overflow:hidden;backdrop-filter:blur(4px);margin-bottom:10px;}}
.card:before {{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent);}}
.card .lbl {{font-size:.72rem;text-transform:uppercase;letter-spacing:1.2px;color:{P['muted']};}}
.card .val {{font-size:1.85rem;font-weight:800;color:#fff;line-height:1.25;}}
.card .val small {{font-size:.9rem;font-weight:500;color:{P['aqua']};margin-left:4px;}}
.card .val.na {{font-size:1.05rem;color:{P['muted']};font-weight:600;padding:.4rem 0;}}
.card .sub {{font-size:.8rem;color:#bcdde4;}}
.card .src {{font-size:.7rem;color:{P['muted']};margin-top:6px;}}
.card .src:before {{content:"● ";color:var(--accent);}}
.chip {{display:inline-block;padding:3px 10px;border-radius:999px;font-size:.74rem;font-weight:600;margin:0 6px 6px 0;border:1px solid;}}
.chip.ok {{color:{P['palm']};border-color:rgba(52,211,153,.5);background:rgba(52,211,153,.10);}}
.chip.bad {{color:{P['coral']};border-color:rgba(255,107,107,.5);background:rgba(255,107,107,.10);}}
.chip.official {{color:{P['sun']};border-color:rgba(255,200,87,.6);background:rgba(255,200,87,.10);}}
.chip.calc {{color:{P['sky']};border-color:rgba(56,189,248,.5);background:rgba(56,189,248,.10);}}
.callout {{border-radius:12px;padding:10px 14px;margin:6px 0 12px;border:1px solid;font-size:.9rem;}}
.callout.info {{border-color:rgba(56,189,248,.5);background:rgba(56,189,248,.09);}}
.callout.warn {{border-color:rgba(255,200,87,.6);background:rgba(255,200,87,.09);}}
.callout.alert {{border-color:rgba(255,107,107,.6);background:rgba(255,107,107,.10);}}
.section {{font-size:.8rem;text-transform:uppercase;letter-spacing:2px;color:{P['aqua']};margin:18px 0 6px;font-weight:700;}}
.srcnote {{font-size:.76rem;color:{P['muted']};margin:-4px 0 8px;}}
.storm {{background:rgba(255,255,255,.05);border:1px solid rgba(125,243,232,.2);border-radius:16px;padding:14px 16px;margin-bottom:10px;border-left:8px solid var(--accent);}}
.storm .sname {{font-size:1.25rem;font-weight:800;letter-spacing:1px;color:#fff;}}
.storm .scat {{font-size:.88rem;font-weight:700;color:var(--accent);margin-bottom:6px;}}
.storm .sgrid {{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px;font-size:.84rem;color:#d4eef2;}}
.storm .sgrid b {{color:#fff;}} .storm .sgrid span.k {{display:block;font-size:.66rem;text-transform:uppercase;letter-spacing:1px;color:{P['muted']};}}
.storm .sfoot {{font-size:.7rem;color:{P['muted']};margin-top:8px;}}
.plain {{border-left:4px solid {P['turquoise']};background:rgba(20,217,196,.07);border-radius:10px;padding:10px 14px;margin:8px 0 12px;font-size:.95rem;}}
.foot {{font-size:.74rem;color:{P['muted']};border-top:1px solid rgba(125,243,232,.15);margin-top:30px;padding-top:10px;}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ---- width-compat wrappers (Streamlit moved from use_container_width to width="stretch") ----
def show_plot(fig: go.Figure, key: str | None = None) -> None:
    cfg = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
    if _NEW_ST:
        st.plotly_chart(fig, width="stretch", key=key, config=cfg)
    else:
        st.plotly_chart(fig, use_container_width=True, key=key, config=cfg)


def show_df(df, **kw) -> None:
    if _NEW_ST:
        st.dataframe(df, width="stretch", hide_index=True, **kw)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True, **kw)


def show_map(fig, key: str | None = None, select: bool = False):
    """Render a Plotly map. With select=True, returns the id (customdata[1]) of the clicked/tapped object, else None."""
    cfg = {"displaylogo": False, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
    kw = {"width": "stretch"} if _NEW_ST else {"use_container_width": True}
    if not select:
        st.plotly_chart(fig, key=key, config=cfg, **kw)
        return None
    try:
        ev = st.plotly_chart(fig, key=key, config=cfg, on_select="rerun", selection_mode="points", **kw)
        for pt in (ev or {}).get("selection", {}).get("points", []) or []:
            cd = pt.get("customdata")
            if isinstance(cd, (list, tuple)) and len(cd) > 1 and cd[1]:
                return str(cd[1])
    except Exception:       # selection is a convenience: hover/tap tooltips and the storm selector still work
        pass
    return None


def style_fig(fig: go.Figure, title: str | None = None, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=P["text"])) if title else None,
        height=height, margin=dict(l=10, r=10, t=44 if title else 12, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.025)",
        font=dict(color=P["text"], size=12), colorway=COLORWAY, hovermode="x unified", showlegend=legend,
        legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(gridcolor="rgba(125,243,232,.10)", zeroline=False, showline=False)
    fig.update_yaxes(gridcolor="rgba(125,243,232,.10)", zeroline=False)
    return fig


# ---- building blocks ----
def hero(loc: Location) -> None:
    st.markdown(f"""<div class="hero"><h1>{html.escape(APP_NAME)}</h1>
    <div class="loc">📍 {html.escape(loc.name)}  ·  {loc.lat:.2f}°, {loc.lon:.2f}°</div>
    <div class="sub">{html.escape(APP_SUBTITLE)}</div></div>""", unsafe_allow_html=True)


def page_title(icon: str, title: str, subtitle: str = "") -> None:
    st.markdown(f"## {icon} {title}")
    if subtitle:
        st.caption(subtitle)


def section(text: str) -> None:
    st.markdown(f'<div class="section">{html.escape(text)}</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str | None, unit: str = "", source: str = "", sub: str = "", accent: str = "turquoise") -> None:
    na = value is None or value == UNAVAILABLE
    val = f'<div class="val na">{UNAVAILABLE}</div>' if na else f'<div class="val">{html.escape(str(value))}<small>{html.escape(unit)}</small></div>'
    st.markdown(f"""<div class="card" style="--accent:{P.get(accent, accent)}"><div class="lbl">{html.escape(label)}</div>{val}
    <div class="sub">{html.escape(sub) if sub else "&nbsp;"}</div><div class="src">Source: {html.escape(source)}</div></div>""", unsafe_allow_html=True)


def chips(results: list[FetchResult]) -> None:
    out = []
    for r in results:
        cls, mark = ("ok", "✓") if r.ok else ("bad", "✕")
        tip = html.escape((r.message or "")[:140], quote=True)
        out.append(f'<span class="chip {cls}" title="{tip}">{mark} {html.escape(r.source or "Source")}</span>')
    st.markdown("".join(out), unsafe_allow_html=True)


def badge(kind: str, text: str) -> str:
    return f'<span class="chip {kind}">{html.escape(text)}</span>'


def callout(text: str, kind: str = "info") -> None:
    st.markdown(f'<div class="callout {kind}">{text}</div>', unsafe_allow_html=True)


def source_note(text: str) -> None:
    st.markdown(f'<div class="srcnote">Source: {html.escape(text)}</div>', unsafe_allow_html=True)


def unavailable(res: FetchResult | None = None, what: str = "") -> None:
    msg = f" - {res.message}" if res is not None and res.message else ""
    callout(f"<b>{UNAVAILABLE}</b>{(' for ' + html.escape(what)) if what else ''}.{html.escape(msg[:220])}", "warn")


# ---- sidebar / state ----
def current_location() -> Location:
    return LOCATIONS.get(st.session_state.get("location_name", DEFAULT_LOCATION), PRIMARY)


def get_thresholds() -> dict:
    return st.session_state.get("risk_thresholds") or copy.deepcopy(DEFAULT_THRESHOLDS)


def sidebar_controls() -> None:
    with st.sidebar:
        st.markdown(f"### 🌊 {APP_NAME.title()}")
        st.selectbox("Location", list(LOCATIONS), key="location_name",
                     help="Open-Meteo is queried at these coordinates. Add more in utils/config.py.")
        if st.button("↻ Refresh data now"):
            st.cache_data.clear()
            st.rerun()
        with st.expander("⚙ Marine-conditions rules"):
            st.caption("Lower bounds of 🟡 / 🟠 / 🔴. Rule-based, editable, NOT official.")
            th = copy.deepcopy(DEFAULT_THRESHOLDS)
            for key, cfg in th.items():
                cols = st.columns(3)
                cfg["limits"] = [cols[i].number_input(f"{cfg['label']} {c} ({cfg['unit']})", value=float(v), min_value=0.0,
                                                       step=0.5, key=f"th_{key}_{i}", label_visibility="visible" if i == 0 else "collapsed")
                                 for i, (c, v) in enumerate(zip("🟡🟠🔴", cfg["limits"]))]
            st.session_state["risk_thresholds"] = th
        st.caption(DISCLAIMER)


def storm_card(name: str, kind: str, color: str, rows: list[tuple[str, str]], foot: str = "") -> None:
    grid = "".join(f"<div><span class='k'>{html.escape(k)}</span><b>{html.escape(v)}</b></div>" for k, v in rows)
    st.markdown(f"<div class='storm' style='--accent:{color}'><div class='sname'>{html.escape(name)}</div>"
                f"<div class='scat'>{html.escape(kind)}</div><div class='sgrid'>{grid}</div>"
                f"<div class='sfoot'>{html.escape(foot)}</div></div>", unsafe_allow_html=True)


def plain_box(markdown_text: str) -> None:
    """Highlighted 'in plain words' explanation (rendered markdown inside a styled container)."""
    with st.container(border=True):
        st.markdown("💬 **In plain words**  \n" + markdown_text)


def glossary(terms: list[str] | None = None, title: str = "📖 What do these terms mean?") -> None:
    from utils.plain import GLOSSARY
    with st.expander(title):
        for k in terms or GLOSSARY:
            if k in GLOSSARY:
                st.markdown(f"**{k}** - {GLOSSARY[k]}")


def footer() -> None:
    st.markdown(f'<div class="foot">⚠ {html.escape(DISCLAIMER)}<br>Data: Open-Meteo · NOAA NHC · NOAA NCEI ERDDAP · DIMAR/CECOLDO</div>',
                unsafe_allow_html=True)
