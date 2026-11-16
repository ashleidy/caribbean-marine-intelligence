"""Waves, swell, SST, currents + NOAA ERDDAP dataset explorer."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics.risk import LEVELS, evaluate
from analytics.statistics import slice_period
from services.noaa_erddap import SEARCH_PRESETS
from utils.charts import gauge, mark_now, zone_line_chart
from utils.config import PALETTE, PERIODS, VARIABLES
from utils.plain import M_TO_FT, conditions_sentence
from utils.coordinates import deg_to_cardinal
from utils.data import (erddap_grid, erddap_search, erddap_table, erddap_variables, load_marine, snapshot, with_history, SRC_MARINE)
from utils.export import download_buttons
from utils.formatting import fmt, to_local
from utils.ui import (glossary, plain_box, callout, chips, current_location, get_thresholds, metric_card, page_title, section, show_df, show_plot,
                      source_note, style_fig, unavailable)

loc = current_location()
page_title("🌡️", "OCEAN & WAVES", f"{loc.name} · Open-Meteo Marine + NOAA ERDDAP")
marine = load_marine(loc)
chips([marine])
if not marine.ok:
    unavailable(marine, "Open-Meteo Marine")
else:
    df = with_history(marine.data, loc, SRC_MARINE)
    q = marine.data.attrs.get("query_point")
    if q and marine.data.attrs.get("offset_used"):
        callout(f"The model grid is land-masked at the exact point; values come from the nearest sea point ({q[0]:.2f}, {q[1]:.2f}).", "info")
    snap = snapshot(marine, marine)
    v = lambda k: (snap.get(k) or {}).get("value")
    risk = evaluate({"wave_height": v("wave_height")}, {"wave_height": get_thresholds()["wave_height"]})

    section("Sea state now")
    plain_box(conditions_sentence({k: v(k) for k in ("wave_height", "wave_period", "wave_direction", "sea_surface_temperature")}))
    c = st.columns(5)
    with c[0]: metric_card("Wave height", f"{v('wave_height'):.2f}" if v("wave_height") is not None else None, "m", "Open-Meteo Marine", "", "turquoise")
    with c[1]: metric_card("Direction", f"{v('wave_direction'):.0f}° {deg_to_cardinal(v('wave_direction'))}" if v("wave_direction") is not None else None, "", "Open-Meteo Marine", "waves coming FROM", "sky")
    with c[2]: metric_card("Time between waves", fmt(v("wave_period"), decimals=1) if v("wave_period") is not None else None, "s", "Open-Meteo Marine", f"peak {fmt(v('wave_peak_period'), 's')}", "lagoon")
    with c[3]: metric_card("Swell", f"{v('swell_wave_height'):.2f}" if v("swell_wave_height") is not None else None, "m", "Open-Meteo Marine", f"{fmt(v('swell_wave_period'), 's')} · from {deg_to_cardinal(v('swell_wave_direction'))}", "palm")
    with c[4]: metric_card("Sea comfort", f"{risk.meta['emoji']} {risk.meta['label']}", "", "This app · configurable rule", "waves only", risk.meta["color"])
    st.caption("Indicator thresholds are editable in the sidebar and are NOT official maritime safety information.")

    section("Time series")
    period = st.select_slider("Period", list(PERIODS), value="7 days")
    now = pd.Timestamp.now(tz="UTC")
    sub = slice_period(df, PERIODS[period], now)
    hz = st.toggle("Include next 7 days (forecast)", value=True)
    if hz:
        sub = pd.concat([sub, df[df.index > now]])
    tabs = st.tabs(["Wave height", "Time between waves", "Sea temperature", "Ocean currents"])
    def plot(tab, cols, ylab, kind="line"):
        with tab:
            fig = go.Figure()
            for col in cols:
                if col in sub and sub[col].notna().any():
                    (fig.add_scatter(x=to_local(sub.index), y=sub[col], name=VARIABLES[col]["label"], mode="markers" if kind == "dots" else "lines", marker=dict(size=4)))
            if not fig.data:
                unavailable(None, ", ".join(VARIABLES[c]["label"] for c in cols)); return
            mark_now(fig, now, sub.index.max() if sub.index.max() > now else None); fig.update_yaxes(title=ylab)
            show_plot(style_fig(fig, height=340), key=f"oc_{cols[0]}")
    with tabs[0]:
        zl = get_thresholds()["wave_height"]["limits"]
        f_ = zone_line_chart({"Wave height": sub.get("wave_height"), "Swell height": sub.get("swell_wave_height")}, zl,
                             ["Comfortable", "Caution", "Difficult", "Dangerous"], "metres", "How high are the waves?", now)
        show_plot(f_, key="oc_waves") if f_ else unavailable(None, "waves")
        st.caption("Swell = long smooth waves from distant storms. Colours are adjustable rules, not an official warning. 1 m is about 3.3 ft.")
    plot(tabs[1], ["wave_period", "wave_peak_period", "swell_wave_period"], "seconds between waves")
    plot(tabs[2], ["sea_surface_temperature"], "°C")
    plot(tabs[3], ["ocean_current_velocity"], marine.data.attrs.get("units", {}).get("ocean_current_velocity", "km/h"))
    source_note("Open-Meteo Marine (model data; past values accumulate in the local store)")
    download_buttons(sub, f"ocean_{loc.name.replace(' ', '_')}", "ocean")

# ------------------------------------------------------------------ ERDDAP
glossary(["Wave height", "Time between waves (period)", "Swell"])
section("NOAA scientific data explorer (ERDDAP)")
st.caption("Source: NOAA NCEI ERDDAP (https://www.ncei.noaa.gov/erddap). Datasets are discovered live through ERDDAP's search API; nothing is hard-coded.")
c1, c2 = st.columns([1, 2])
preset = c1.selectbox("Topic", list(SEARCH_PRESETS))
query = c2.text_input("Search terms", SEARCH_PRESETS[preset])
if st.button("Search ERDDAP"):
    st.session_state["erddap_q"] = query
if q_ := st.session_state.get("erddap_q"):
    try:
        res = erddap_search(q_)
        show_df(res[["dataset_id", "title", "type", "institution"]])
        ds = st.selectbox("Dataset", res["dataset_id"], format_func=lambda i: f"{i} · {res.set_index('dataset_id').loc[i, 'title'][:80]}")
        vars_ = erddap_variables(ds)
        show_df(vars_)
        dtype = res.set_index("dataset_id").loc[ds, "type"]
        data_vars = vars_[vars_["kind"] == "variable"]["name"].tolist()
        pick = st.multiselect("Variables", data_vars, default=data_vars[:1])
        d1, d2 = st.columns(2)
        end = d2.date_input("End", pd.Timestamp.now(tz="UTC").date())
        start = d1.date_input("Start", (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).date())
        r = st.slider("Box half-width (°)", 0.25, 5.0, 1.5, 0.25)
        bbox = (loc.lat - r, loc.lat + r, loc.lon - r, loc.lon + r)
        st.caption(f"Type: {dtype}. Request is bounded by time and by a lat/lon box and capped at 15 MB.")
        if st.button("Fetch subset") and pick:
            with st.spinner("Querying ERDDAP…"):
                t0, t1 = f"{start}T00:00:00Z", f"{end}T23:59:59Z"
                out = erddap_table(ds, tuple(["time", "latitude", "longitude"] + pick if dtype == "tabledap" else pick), t0, t1, bbox) \
                    if dtype == "tabledap" else erddap_grid(ds, pick[0], t0, t1, bbox, 1)
            st.session_state["erddap_out"] = (ds, out)
    except Exception as exc:
        callout(f"<b>Data unavailable</b> from ERDDAP: {exc}", "warn")
if "erddap_out" in st.session_state:
    ds, out = st.session_state["erddap_out"]
    st.write(f"{len(out):,} rows from `{ds}`")
    show_df(out.head(500))
    num = out.select_dtypes("number").columns.difference(["latitude", "longitude"])
    if "time" in out and len(num):
        fig = go.Figure()
        fig.add_scatter(x=out["time"], y=out[num[0]], mode="markers", marker=dict(size=4, color=PALETTE["turquoise"]), name=num[0])
        show_plot(style_fig(fig, height=300))
    download_buttons(out, f"erddap_{ds}", "erddap")
