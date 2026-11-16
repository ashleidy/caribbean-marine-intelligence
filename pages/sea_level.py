"""Sea level (Open-Meteo model): stats, anomalies, trend."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics.anomalies import latest_status
from analytics.statistics import describe, linear_trend, remove_cycle, slice_period, sudden_changes
from utils.config import PALETTE, PERIODS
from utils.data import (SRC_MARINE, backfill_marine, load_marine, store, with_history)
from utils.export import download_buttons
from utils.formatting import fmt, fmt_dt, to_local
from utils.ui import glossary, plain_box, callout, chips, current_location, metric_card, page_title, section, show_df, show_plot, source_note, style_fig, unavailable

loc = current_location()
page_title("📏", "SEA LEVEL", f"{loc.name} · Open-Meteo Marine (computer model: tide + sea level)")
marine = load_marine(loc)
chips([marine])

series, src = None, None
if marine.ok and "sea_level_height_msl" in marine.data:
    full = with_history(marine.data, loc, SRC_MARINE)
    series, src = full["sea_level_height_msl"].dropna(), "Open-Meteo Marine (model, relative to mean sea level)"
else:
    unavailable(marine if not marine.ok else None, "sea level")

if series is not None and len(series):
    now = pd.Timestamp.now(tz="UTC")
    obs = series[series.index <= now]
    period = st.select_slider("Period", list(PERIODS), value="7 days")
    win = slice_period(obs, PERIODS[period], now)
    cur, cur_t = obs.iloc[-1], obs.index[-1]
    hist_mean = obs.mean()
    filt24 = obs.tail(24).mean()
    stt = latest_status(obs, method="rolling_z", window=720, detrend_tide=True)
    tr = linear_trend(win)
    span = (obs.index[-1] - obs.index[0]).days

    section("Key indicators")
    c = st.columns(4)
    with c[0]: metric_card("CURRENT SEA LEVEL", f"{cur:.3f}", "m", src.split(" · ")[0], fmt_dt(cur_t), "sky")
    with c[1]: metric_card("HISTORICAL MEAN", f"{hist_mean:.3f}", "m", "same series", f"over {span} days available", "lagoon")
    with c[2]: metric_card("ANOMALY (vs. average)", f"{(filt24 - hist_mean) * 100:+.1f}", "cm", "computed", f"24 h mean vs hist. mean · {stt['label'] if stt else 'n/a'}", "papaya")
    with c[3]: metric_card("TREND", f"{tr['slope_per_day'] * 1000:+.2f}" if tr["ok"] else None, "mm/day", "computed (daily means)", f"p={tr['p_value']:.3f}" if tr["ok"] else tr.get("reason", ""), "palm")
    if span < 90:
        callout(f"Only <b>{span} days</b> of history are available, so 'historical mean' and trend are short-term. Use <i>Backfill</i> below to extend the local record.", "info")

    plain_box(f"Sea level right now is **{cur:.2f} m** relative to the average. It goes up and down about twice a day with the **tide**; the yellow line smooths the tide out so you can see slower changes "
              f"(storms, low pressure, warm water). Over the last 24 hours the smoothed level is **{abs(filt24 - hist_mean) * 100:.0f} cm {'above' if filt24 >= hist_mean else 'below'}** the long-term average.")
    section("Tide & sea level")
    show_ma = st.toggle("Show the line with the tide smoothed out", value=True)
    fig = go.Figure()
    fig.add_scatter(x=to_local(win.index), y=win, name="Sea level (m)", line=dict(color=PALETTE["sky"], width=1.5))
    if show_ma and len(win) > 30:
        fig.add_scatter(x=to_local(win.index), y=win.rolling(25, center=True, min_periods=12).mean(), name="Tide removed (25 h average)", line=dict(color=PALETTE["sun"], width=2))
    fig.add_hline(y=hist_mean, line_dash="dash", line_color=PALETTE["coral"], annotation_text="Average")
    fig.update_yaxes(title="m")
    show_plot(style_fig(fig, height=380))
    source_note(src)

    section("Statistics")
    stats = describe(win, (1, 5, 25, 50, 75, 95, 99))
    show_df(pd.DataFrame([stats]).round(3))
    sc = sudden_changes(win)
    st.markdown(f"**Abrupt changes** (3 h change > 4 robust σ): {len(sc)} found")
    if len(sc):
        show_df(sc.assign(time=to_local(pd.DatetimeIndex(sc["time"]))).round(3))
    download_buttons(win.rename("sea_level_m").to_frame(), f"sea_level_{period.replace(' ', '_')}", "sl")

# ------------------------------------------------------------------ data ingestion
section("Extend the record")
with st.expander("Load more history (Open-Meteo)"):
    yrs = st.selectbox("Years back", [1, 2, 3, 5])
    if st.button("Backfill local store"):
        with st.spinner("Downloading…"):
            ok, msg = backfill_marine(loc, yrs)
        (st.success if ok else st.warning)(msg)
        st.cache_data.clear()
    st.caption(f"Local store rows: {store().count():,}. Streamlit Cloud storage is ephemeral; the store rebuilds from the API.")

glossary(['Sea level', 'Anomaly'])
