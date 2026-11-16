"""Meteorological conditions and time series (Open-Meteo Weather)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from analytics.statistics import describe, slice_period
from services.open_meteo_weather import describe_weather_code
from utils.charts import compass, mark_now, zone_line_chart
from utils.config import PALETTE, PERIODS
from utils.coordinates import deg_to_cardinal
from utils.data import SRC_WEATHER, load_weather, snapshot, with_history
from utils.export import download_buttons
from utils.formatting import fmt, to_local
from utils.ui import get_thresholds, glossary, chips, current_location, metric_card, page_title, section, show_df, show_plot, source_note, style_fig, unavailable

loc = current_location()
page_title("⛅", "WEATHER", f"{loc.name} · Open-Meteo Weather")
res = load_weather(loc)
chips([res])
if not res.ok:
    unavailable(res, "Open-Meteo Weather")
    st.stop()
snap = snapshot(res, res)
v = lambda k: (snap.get(k) or {}).get("value")

section("Now")
c = st.columns(5)
with c[0]: metric_card("Air temperature", fmt(v("temperature_2m")) if v("temperature_2m") is not None else None, "°C", "Open-Meteo", f"humidity {fmt(v('relative_humidity_2m'), '%', 0)}", "papaya")
with c[1]: metric_card("Wind", f"{v('wind_speed_10m'):.0f}" if v("wind_speed_10m") is not None else None, "kn", "Open-Meteo", f"gusts {fmt(v('wind_gusts_10m'), 'kn', 0)} · from {deg_to_cardinal(v('wind_direction_10m'))}", "turquoise")
with c[2]: metric_card("Sea-level pressure", f"{v('pressure_msl'):.1f}" if v("pressure_msl") is not None else None, "hPa", "Open-Meteo", f"surface {fmt(v('surface_pressure'), 'hPa', 1)}", "sky")
with c[3]: metric_card("Precipitation", f"{v('precipitation'):.1f}" if v("precipitation") is not None else None, "mm/h", "Open-Meteo", f"rain {fmt(v('rain'), 'mm', 1)}", "lagoon")
with c[4]: metric_card("Sky", describe_weather_code(v("weather_code")) if v("weather_code") is not None else None, "", "Open-Meteo", f"cloud cover {fmt(v('cloud_cover'), '%', 0)}", "sun")

df = with_history(res.data, loc, SRC_WEATHER)
now = pd.Timestamp.now(tz="UTC")
section("Time series")
period = st.select_slider("Period", list(PERIODS), value="7 days")
sub = slice_period(df, PERIODS[period], now)
if st.toggle("Include forecast (next 7 days)", value=True):
    sub = pd.concat([sub, df[df.index > now]])
t = to_local(sub.index)

def vline(fig):
    mark_now(fig, now, sub.index.max() if sub.index.max() > now else None)
    return fig

if "temperature_2m" in sub:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_scatter(x=t, y=sub["temperature_2m"], name="Temperature (°C)", line=dict(color=PALETTE["papaya"]))
    if "relative_humidity_2m" in sub:
        fig.add_scatter(x=t, y=sub["relative_humidity_2m"], name="Humidity (%)", line=dict(color=PALETTE["sky"], width=1), secondary_y=True)
    show_plot(style_fig(vline(fig), "Air temperature and humidity", 300))
if "pressure_msl" in sub:
    fig = go.Figure(go.Scatter(x=t, y=sub["pressure_msl"], name="Sea-level pressure (hPa)", line=dict(color=PALETTE["sky"])))
    show_plot(style_fig(vline(fig), "Air pressure (falling quickly can mean a storm is approaching)", 280, legend=False))
wc = st.columns([3, 1])
with wc[0]:
    f_ = zone_line_chart({"Wind": sub.get("wind_speed_10m"), "Gusts": sub.get("wind_gusts_10m")}, get_thresholds()["wind_speed_10m"]["limits"],
                         ["Comfortable", "Caution", "Difficult", "Dangerous"], "knots", "How strong is the wind?", now, colors=[PALETTE["turquoise"], PALETTE["coral"]])
    show_plot(f_, key="w_wind") if f_ else unavailable(None, "wind")
with wc[1]:
    cp = compass(v("wind_direction_10m"))
    show_plot(cp, key="w_comp") if cp else unavailable(None, "wind direction")
if "precipitation" in sub:
    fig = go.Figure(go.Bar(x=t, y=sub["precipitation"], name="Precipitation (mm/h)", marker_color=PALETTE["lagoon"]))
    if "cloud_cover" in sub:
        fig.add_scatter(x=t, y=sub["cloud_cover"], name="Cloud cover (%)", yaxis="y2", line=dict(color=PALETTE["muted"], width=1))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[0, 100]))
    show_plot(style_fig(vline(fig), "Rain (taller bars = heavier rain) and cloud cover", 280))
source_note("Open-Meteo Weather API (model data). Local time UTC-5.")

section("Statistics (observed part of the selected period)")
obs = sub[sub.index <= now]
rows = [{"variable": c_, **describe(obs[c_])} for c_ in ("temperature_2m", "pressure_msl", "wind_speed_10m", "wind_gusts_10m", "precipitation", "relative_humidity_2m") if c_ in obs and obs[c_].notna().any()]
if rows:
    show_df(pd.DataFrame(rows).round(2))
download_buttons(sub, f"weather_{loc.name.replace(' ', '_')}", "weather")

glossary(['Air pressure', 'Knot (kn)', 'Wind gust'])
