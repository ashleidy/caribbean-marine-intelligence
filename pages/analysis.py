"""Is today unusual? Anomaly detection explained for everyone + simple, interpretable estimates."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics.anomalies import LAY_LABELS, LEVEL_LABELS, METHODS as AM, detect, plain_summary
from analytics.forecasting import METHODS as FM, backtest, forecast_series
from analytics.statistics import slice_period
from utils.charts import anomaly_chart
from utils.config import ANALYSIS_VARIABLES, PALETTE, PERIODS, VARIABLES
from utils.data import load_marine, load_weather, unified_frame
from utils.export import download_buttons
from utils.formatting import to_local
from utils.ui import callout, chips, current_location, glossary, metric_card, page_title, plain_box, section, show_df, show_plot, style_fig, unavailable

loc = current_location()
page_title("📈", "ANOMALIES & TRENDS", f"{loc.name} · Is today's weather and sea unusual? · Open-Meteo data plus locally stored history")
marine, weather = load_marine(loc), load_weather(loc)
chips([marine, weather])
frame = unified_frame(loc, marine, weather)
avail = [v for v in ANALYSIS_VARIABLES if frame is not None and v in frame and frame[v].notna().any()]
if not avail:
    unavailable(None, "analysis variables"); st.stop()
now = pd.Timestamp.now(tz="UTC")

with st.expander("🧭 New here? What is an anomaly?", expanded=False):
    st.markdown("""
An **anomaly** is simply a reading that is **unusual for this place**. The app learns what is normal from the recent past
(for example, the last 7 days of wave heights) and draws that as a **green band**. Then it checks the newest reading:

* 🟢 **Normal** - the line is inside the green band. Nothing out of the ordinary.
* 🟡 **Unusual** - the line is outside the band. Readings like this happen only about 1 time in 20 or less.
* 🔴 **Very unusual** - far outside the band. Readings like this are rare (about 1 in 100 or less).

Being unusual does **not** automatically mean danger - a very calm sea can be unusual too. Official warnings come only from agencies such as the NHC, IDEAM and DIMAR.
""")

col = st.selectbox("What would you like to check?", avail, format_func=lambda v: VARIABLES[v]["label"])
unit, label = VARIABLES[col]["unit"], VARIABLES[col]["label"]
obs = frame.loc[frame.index <= now, col].dropna()
is_sl = col == "sea_level_height_msl"

tab_a, tab_f = st.tabs(["🔎 Is it unusual?", "📉 Where is it heading?"])
with tab_a:
    c = st.columns([1, 1])
    period = c[0].selectbox("Time window to show", list(PERIODS), index=1)
    with st.expander("⚙ Advanced settings (method and sensitivity)"):
        a = st.columns(4)
        method = a[0].selectbox("Method", list(AM), format_func=AM.get)
        z_a = a[1].number_input("'Unusual' from (std. deviations)", 1.0, 6.0, 2.0, 0.5, help="Higher = fewer readings flagged")
        z_e = a[2].number_input("'Very unusual' from", 1.5, 8.0, 3.0, 0.5)
        win = a[3].number_input("Recent-weeks window (hours)", 24, 2160, 168, 24) if method == "rolling_z" else 168
        b = st.columns(2)
        tide = b[0].checkbox("Remove the daily tide first (recommended for sea level)", value=is_sl)
        p_a = b[1].number_input("Percentile tail %", 0.5, 10.0, 2.5, 0.5) if method == "percentile" else 2.5
    res_full = detect(obs, method, z_anom=z_a, z_ext=z_e, window=int(win), p_anom=p_a, p_ext=p_a / 5, detrend_tide=tide)
    if res_full.empty:
        unavailable(None, "enough data for anomaly detection")
    else:
        ps = plain_summary(res_full, label, unit, 2 if is_sl else 1, detrended=tide)
        kind = {0: "info", 1: "warn", 2: "alert"}[ps["level"]]
        cc = st.columns([1, 2])
        with cc[0]:
            metric_card("Right now", f"{ps['emoji']} {ps['lay']}", "", f"Source: {VARIABLES[col]['source']}", f"technical label: {ps['technical']}",
                        {0: "palm", 1: "sun", 2: "coral"}[ps["level"]])
        with cc[1]:
            plain_box(ps["text"])
        res = slice_period(res_full, PERIODS[period], now)
        show_plot(anomaly_chart(res, ("Sea level (tide removed)" if tide and is_sl else label), unit), key="an_chart")
        st.caption("Green band = normal range · dashed line = usual level · yellow dots = unusual · red dots = very unusual. Hover over the line to read values.")
        counts = res["level"].value_counts().reindex([0, 1, 2], fill_value=0)
        total = max(int(counts.sum()), 1)
        st.markdown(" · ".join(f"{LAY_LABELS[k][1]} **{LAY_LABELS[k][0]}**: {int(v):,} hours ({v / total:.0%})" for k, v in counts.items()))
        flagged = res[res["level"] > 0].tail(200)
        if len(flagged):
            with st.expander(f"See the {len(flagged)} most recent unusual readings"):
                t = flagged.reset_index().rename(columns={"time": "When (UTC)", "value": f"{label} ({unit})", "typical": "Usual level", "label": "Technical label"})
                t["How unusual"] = flagged["level"].map(lambda k: LAY_LABELS[k][0]).to_numpy()
                show_df(t[["When (UTC)", f"{label} ({unit})", "Usual level", "How unusual", "Technical label"]].round(3))
        download_buttons(res, f"anomalies_{col}", "an")
        st.caption(f"Source: {VARIABLES[col]['source']} · statistics calculated by this app, not an official product.")

with tab_f:
    callout("⚠ These lines are <b>simple statistical estimates made by this app</b>. They are <b>not official forecasts</b>. "
            "For real forecasts use the model data on the other pages and your national weather and marine services.", "warn")
    c = st.columns(3)
    method_f = c[0].selectbox("Estimation model", list(FM), format_func=FM.get, index=1)
    hor = c[1].slider("How far ahead (hours)", 6, 120, 48, 6)
    look = c[2].slider("Learn from the last (days)", 3, 60, 14)
    try:
        fc = forecast_series(obs, hor, method_f, look * 24)
        bt = backtest(obs, min(hor, 48), method_f, look * 24)
        hist = obs.tail(24 * 7)
        fig = go.Figure()
        fig.add_scatter(x=to_local(hist.index), y=hist, name="Recent readings", line=dict(color=PALETTE["sky"], width=2.5))
        fig.add_scatter(x=to_local(fc.index), y=fc["upper"], line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=to_local(fc.index), y=fc["lower"], fill="tonexty", fillcolor="rgba(255,200,87,0.20)", line=dict(width=0), name="Likely range (≈95 %)")
        fig.add_scatter(x=to_local(fc.index), y=fc["yhat"], name="Estimate", line=dict(color=PALETTE["sun"], dash="dash", width=3))
        fig.update_yaxes(title=unit)
        show_plot(style_fig(fig, f"{label}: recent readings and a simple estimate", 360), key="fc_chart")
        if bt["ok"]:
            sk = bt["skill_vs_persistence"]
            verdict = ("better than simply assuming nothing changes" if sk is not None and sk > 0.05 else
                       "no better than assuming nothing changes - treat it with caution")
            plain_box(f"When tested on the past {min(hor, 48)} hours, this estimate was off by about **{bt['mae']:.2f} {unit}** on average, which is {verdict}.")
        else:
            st.caption(bt["reason"])
        download_buttons(fc, f"estimate_{col}_{method_f}", "fc")
    except Exception as exc:
        callout(f"<b>Data unavailable</b> for this estimate: {exc}", "warn")
glossary(["Anomaly", "Normal range (green band)", "Sea level"])
