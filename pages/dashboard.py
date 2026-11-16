"""Main dashboard: current state -> alerts -> map -> short time series -> comparison -> report."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics.anomalies import anomaly_summary
from analytics.report import build_report
from utils.charts import compass, gauge, mark_now, zone_line_chart
from utils.plain import KN_TO_MPH, M_TO_FT, conditions_sentence
from analytics.risk import evaluate
from services.base import FetchResult
from services.open_meteo_weather import describe_weather_code
from utils import maps
from services.noaa_nhc import normalize_forecast_points
from utils.config import LOCATIONS, PALETTE, VARIABLES
from utils.coordinates import deg_to_cardinal
from utils.data import (latest_obs, load_all_storms, load_forecast_package, load_marine,
                        load_weather, snapshot, unified_frame)
from utils.export import json_bytes
from utils.formatting import fmt, fmt_dt, to_local
from utils.ui import (callout, chips, current_location, get_thresholds, glossary, hero, plain_box, section, show_df, show_map, show_plot,
                      style_fig, metric_card, unavailable)

loc = current_location()
hero(loc)

with st.spinner("Loading public data sources…"):
    marine, weather = load_marine(loc), load_weather(loc)
    storms, nhc_res, gd_res = load_all_storms(loc)
chips([marine, weather, nhc_res, gd_res])

snap = snapshot(marine, weather)
val = lambda k: (snap.get(k) or {}).get("value")

# ---- sea level (Open-Meteo model) ----
sea = None
if val("sea_level_height_msl") is not None:
    sea = {"value": val("sea_level_height_msl"), "source": "Open-Meteo Marine (model)", "time": snap["sea_level_height_msl"]["time"],
           "sub": "tide + model, relative to mean sea level"}

# ---- risk ----
risk = evaluate({"wave_height": val("wave_height"), "wind_speed_10m": val("wind_speed_10m"),
                 "wind_gusts_10m": val("wind_gusts_10m"), "precipitation": val("precipitation")}, get_thresholds())

# ---- Section 1: current state cards ----
section("Current state")
c = st.columns(4)
with c[0]:
    metric_card("🌊 Sea Level", fmt(sea["value"], decimals=2) if sea else None, "m", sea["source"] if sea else "Open-Meteo Marine", sea["sub"] if sea else "", "sky")
with c[1]:
    metric_card("🌡️ Sea Surface Temperature", fmt(val("sea_surface_temperature"), decimals=1) if val("sea_surface_temperature") is not None else None,
                "°C", "Open-Meteo Marine", "", "papaya")
with c[2]:
    wp, wd = val("wave_period"), val("wave_direction")
    metric_card("🌊 Wave Height", f"{val('wave_height'):.2f}" if val("wave_height") is not None else None, "m", "Open-Meteo Marine",
                (f"{val('wave_height') * M_TO_FT:.1f} ft · every {wp:.0f} s · from {deg_to_cardinal(wd)}" if wp is not None and val("wave_height") is not None else ""), "turquoise")
with c[3]:
    g = val("wind_gusts_10m")
    metric_card("💨 Wind Speed", f"{val('wind_speed_10m'):.0f}" if val("wind_speed_10m") is not None else None, "kn", "Open-Meteo Weather",
                (f"{val('wind_speed_10m') * KN_TO_MPH:.0f} mph · gusts {g:.0f} kn" if g is not None and val("wind_speed_10m") is not None else ""), "palm")
c = st.columns(4)
with c[0]:
    d_ = val("wind_direction_10m")
    metric_card("🧭 Wind Direction", f"{d_:.0f}° {deg_to_cardinal(d_)}" if d_ is not None else None, "", "Open-Meteo Weather", "direction wind blows FROM", "sky")
with c[1]:
    w = weather.data if weather.ok else None
    nxt = None
    if w is not None and "precipitation" in w:
        now = pd.Timestamp.now(tz="UTC")
        nxt = float(w.loc[(w.index > now) & (w.index <= now + pd.Timedelta(hours=24)), "precipitation"].sum())
    metric_card("🌧️ Rain", f"{val('precipitation'):.1f}" if val("precipitation") is not None else None, "mm/h", "Open-Meteo Weather",
                f"next 24 h: {nxt:.1f} mm" if nxt is not None else "", "lagoon")
with c[2]:
    if not storms.ok:
        metric_card("🌀 Tropical Cyclones", None, "", "NOAA NHC + GDACS", "", "coral")
    elif storms.data.empty:
        metric_card("🌀 Tropical Cyclones", "0", "active worldwide", "NOAA NHC + GDACS", "No active systems reported", "coral")
    else:
        n0 = storms.data.iloc[0]
        metric_card("🌀 Tropical Cyclones", str(len(storms.data)), "active worldwide", "NOAA NHC + GDACS",
                    f"nearest: {str(n0['name']).upper()} · {n0['distance_km']:,.0f} km away", "coral")
with c[3]:
    metric_card("⚠️ Marine Risk", f"{risk.meta['emoji']} {risk.meta['label']}", "", "This app · rule-based estimate",
                risk.reasons[0][:60], risk.meta["color"])

# ---- plain-words summary + at-a-glance gauges ----
th = get_thresholds()
plain_box(conditions_sentence({k: val(k) for k in ("wave_height", "wave_period", "wave_direction", "wind_speed_10m", "wind_gusts_10m",
                                                   "wind_direction_10m", "sea_surface_temperature")}))
g1, g2, g3 = st.columns(3)
with g1:
    f_ = gauge(val("wave_height"), th["wave_height"]["limits"], "m", "How high are the waves?", max(4.0, th["wave_height"]["limits"][2] * 1.3), 2)
    show_plot(f_, key="g_wave") if f_ else unavailable(None, "wave height")
with g2:
    f_ = gauge(val("wind_speed_10m"), th["wind_speed_10m"]["limits"], "kn", "How strong is the wind?", max(45.0, th["wind_speed_10m"]["limits"][2] * 1.3), 0)
    show_plot(f_, key="g_wind") if f_ else unavailable(None, "wind speed")
with g3:
    f_ = compass(val("wind_direction_10m"))
    show_plot(f_, key="g_dir") if f_ else unavailable(None, "wind direction")
st.caption("Green = comfortable, yellow = use caution, orange = difficult, red = dangerous. These colour limits are simple, adjustable rules (sidebar) - not official marine warnings.")

# ---- Section 2: alerts / important info ----
if storms.ok and not storms.data.empty:
    near = storms.data[storms.data["distance_km"] <= 1500]
    if len(near):
        n0 = near.iloc[0]
        callout(f"🌀 <b>{n0['source']}</b> reports <b>{n0['classification_label']} {n0['name']}</b>, about <b>{n0['distance_km']:.0f} km</b> "
                f"{n0['direction_from_ref']} of {loc.name} (position: {n0['source']}; distance: calculated by this app). "
                "Follow <a href='https://www.nhc.noaa.gov' target='_blank'>official NHC advisories</a> and local authorities.", "alert")
if risk.level is not None and risk.level >= 2:
    callout(f"{risk.meta['emoji']} Indicator: <b>{risk.meta['label']}</b> - {'; '.join(risk.reasons)}. System estimate, not an official maritime warning.", "warn")
for res in (marine, weather):
    if not res.ok:
        unavailable(res, res.source)

# ---- Section 3: map ----
section("Regional map")
mc = st.columns([2, 3])
mstyle = mc[0].radio("Map style", maps.STYLES, horizontal=True, key="dash_style")
fig = maps.base_fig(mstyle, loc.lat, loc.lon, 4.6, 560, "dash")
maps.add_rings(fig, loc, mstyle)
n_out = 0
if storms.ok and not storms.data.empty:
    near = storms.data[storms.data["distance_km"] < 3500]
    n_out = len(storms.data) - len(near)
    for _, s_ in near.iterrows():
        if s_["source"] == "NOAA NHC":
            pkg = load_forecast_package(s_["forecast_zip"])
            if pkg.ok:
                maps.add_forecast_pkg(fig, pkg.data, mstyle)
                if pkg.data.get("points") is not None:
                    maps.add_forecast_points(fig, normalize_forecast_points(pkg.data["points"]), mstyle, str(s_["name"]).upper())
    maps.add_storm_markers(fig, near, mstyle, loc.name)
maps.add_locations(fig, loc, mstyle)
show_map(fig, key="dash_map")
st.markdown(maps.category_legend_html(), unsafe_allow_html=True)
st.caption("Hover or tap a storm for its name and data. Circles around the islands mark 250, 500 and 1,000 km. "
           + (f"{n_out} more active storm(s) are far from this view - open the **Tropical Cyclones** page for the worldwide map. " if n_out else "")
           + "Storm data: NOAA NHC and GDACS.")

# ---- Section 4: next 72 h ----
section("Next 3 days")
now = pd.Timestamp.now(tz="UTC")
tabs = st.tabs(["🌊 Waves", "💨 Wind", "🌧️ Rain & air pressure"])
def window(res):
    return res.data[(res.data.index >= now - pd.Timedelta(hours=12)) & (res.data.index <= now + pd.Timedelta(hours=72))] if res.ok else None
mw, ww = window(marine), window(weather)
with tabs[0]:
    f_ = zone_line_chart({"Wave height": mw["wave_height"]} if mw is not None and "wave_height" in mw else {}, th["wave_height"]["limits"],
                         ["Comfortable", "Caution", "Difficult", "Dangerous"], "metres", "Wave height: now and the next 3 days", now)
    show_plot(f_, key="d_wave") if f_ else unavailable(None, "waves")
with tabs[1]:
    ser = {}
    if ww is not None:
        ser = {"Wind": ww["wind_speed_10m"], "Gusts": ww["wind_gusts_10m"]} if "wind_speed_10m" in ww and "wind_gusts_10m" in ww else {}
    f_ = zone_line_chart(ser, th["wind_speed_10m"]["limits"], ["Comfortable", "Caution", "Difficult", "Dangerous"], "knots", "Wind and gusts: now and the next 3 days", now,
                         colors=[PALETTE["turquoise"], PALETTE["coral"]])
    show_plot(f_, key="d_wind") if f_ else unavailable(None, "wind")
with tabs[2]:
    if ww is not None and "precipitation" in ww:
        fig = go.Figure(go.Bar(x=to_local(ww.index), y=ww["precipitation"], marker_color=PALETTE["sky"], name="Rain (mm per hour)"))
        mark_now(fig, now, ww.index.max())
        fig.update_yaxes(title="mm per hour")
        show_plot(style_fig(fig, "Rain: taller bars = heavier rain", 280, legend=False), key="d_rain")
    else:
        unavailable(None, "rain")
st.caption("Source: Open-Meteo Marine / Weather (computer-model output, local time UTC-5). The dotted line is now; the shaded part is forecast.")

# ---- Is today unusual? ----
section("Is today unusual?")
frame_u = unified_frame(loc, marine, weather)
lab = {c_: VARIABLES[c_]["label"] for c_ in ("sea_surface_temperature", "wave_height", "wind_speed_10m", "pressure_msl", "sea_level_height_msl")}
units_u = {c_: VARIABLES[c_]["unit"] for c_ in lab}
anom_u = anomaly_summary(frame_u, lab, units=units_u) if frame_u is not None else pd.DataFrame()
if anom_u.empty:
    unavailable(None, "anomaly analysis")
else:
    cols_u = st.columns(len(anom_u))
    for col_u, (_, r_) in zip(cols_u, anom_u.iterrows()):
        with col_u:
            metric_card(r_["variable"], f"{r_['emoji']} {r_['lay']}", "", "Compared with the last 30 days", "", {"Normal": "palm", "Unusual": "sun", "Very unusual": "coral"}.get(r_["lay"], "muted"))
    with st.expander("What does this mean?"):
        for _, r_ in anom_u.iterrows():
            st.markdown(f"{r_['emoji']} {r_['text']}")
        st.caption("An 'unusual' reading is one that falls outside the normal range for this place and season. It is not a warning by itself. See the **Anomalies & Trends** page for charts.")

# ---- Section 5: comparison (lazy) ----
section("Compare locations")
if st.toggle("Load comparison (one API call per location)", value=False):
    rows = []
    for name in st.multiselect("Locations", list(LOCATIONS), default=[n for n in ("Providencia", "San Andrés") if n in LOCATIONS]):
        l = LOCATIONS[name]
        s = snapshot(load_marine(l), load_weather(l))
        g_ = lambda k: (s.get(k) or {}).get("value")
        rows.append({"Location": name, "Wave height (m)": g_("wave_height"), "SST (°C)": g_("sea_surface_temperature"),
                     "Wind (kn)": g_("wind_speed_10m"), "Gusts (kn)": g_("wind_gusts_10m"), "Rain (mm/h)": g_("precipitation"),
                     "Pressure (hPa)": g_("pressure_msl")})
    if rows:
        show_df(pd.DataFrame(rows).round(2))
        st.caption("Source: Open-Meteo. Empty cell = variable unavailable at that point (never estimated).")

# ---- Section 6: report ----
section("Report")
if st.button("GENERATE MARINE REPORT", type="primary"):
    frame = unified_frame(loc, marine, weather)
    labels = {c: VARIABLES[c]["label"] for c in ("sea_level_height_msl", "sea_surface_temperature", "pressure_msl", "wind_speed_10m", "wave_height")}
    anom = anomaly_summary(frame, labels) if frame is not None else None
    sl_ctx = None
    if sea:
        sl_ctx = {"value": sea["value"], "source": sea["source"], "anomaly": None}
        if frame is not None and "sea_level_height_msl" in frame :
            hist = frame.loc[frame.index <= now, "sea_level_height_msl"].dropna()
            if len(hist) > 24:
                sl_ctx["anomaly"] = float(hist.tail(24).mean() - hist.mean())
    rep = build_report({"location": {"name": loc.name, "lat": loc.lat, "lon": loc.lon}, "snapshot": snap, "sea_level": sl_ctx,
                        "risk": risk, "storms": storms.data if storms.ok else None, "storm_error": storms.message,
                        "anomalies": anom, "sources": [{"source": r.source, "ok": r.ok, "message": r.message} for r in (marine, weather, nhc_res, gd_res)]})
    st.session_state["report"] = rep
rep = st.session_state.get("report")
if rep:
    with st.expander("Marine report", expanded=True):
        st.markdown(rep["markdown"])
    a, b, c_ = st.columns([1, 1, 4])
    a.download_button("⬇ HTML", rep["html"].encode(), "marine_report.html", "text/html")
    b.download_button("⬇ JSON", json_bytes(rep["json"]), "marine_report.json", "application/json")
    c_.download_button("⬇ Markdown", rep["markdown"].encode(), "marine_report.md", "text/markdown")

glossary(['Wave height', 'Time between waves (period)', 'Swell', 'Sea level', 'Anomaly', 'Knot (kn)', 'Wind gust', 'Air pressure'])
