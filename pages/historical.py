"""Historical Atlantic hurricanes (NHC HURDAT2) relative to the selected point."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics.cyclones import CATEGORY_COLORS, CATEGORY_ORDER, storm_summary, storms_in_bbox
from utils import maps
from utils.config import PALETTE
from utils.coordinates import haversine_km
from utils.data import load_hurdat
from utils.export import download_buttons
from utils.ui import glossary, callout, chips, current_location, page_title, section, show_df, show_map, show_plot, source_note, style_fig, unavailable

REGIONS = {"Entire Atlantic basin": None, "Caribbean Sea": (8, 23, -90, -59), "Western Caribbean": (8, 22, -90, -75),
           "Gulf of Mexico": (18, 31, -98, -80)}
loc = current_location()
page_title("🗂️", "HISTORICAL HURRICANES", f"NOAA NHC HURDAT2 (Atlantic best track) · distances relative to {loc.name}")
res = load_hurdat()
chips([res])
if not res.ok:
    unavailable(res, "HURDAT2"); st.stop()
h = res.data


@st.cache_data(show_spinner="Computing closest approach for every storm…")
def summary(lat: float, lon: float, n_rows: int) -> pd.DataFrame:
    return storm_summary(h, lat, lon)


S = summary(loc.lat, loc.lon, len(h))
source_note(f"NOAA NHC HURDAT2 - {res.url.rsplit('/', 1)[-1]} (6-hourly fixes; closest approach uses linear interpolation = computed estimate)")

section("Filters")
c = st.columns(4)
y0, y1 = c[0].slider("Years", int(S["year"].min()), int(S["year"].max()), (1950, int(S["year"].max())))
region = c[1].selectbox("Region (storm passed through)", list(REGIONS))
dmax = c[2].number_input("Max. min-distance (km)", 50, 20000, 1000, 50)
dmin = c[3].number_input("Min. min-distance (km)", 0, 20000, 0, 50)
c = st.columns(2)
cats = c[0].multiselect("How strong did they get? (peak category)", CATEGORY_ORDER[1:], default=CATEGORY_ORDER[1:])
q = c[1].text_input("Storm name contains", "")

f = S[S["year"].between(y0, y1) & S["max_category"].isin(cats) & S["min_distance_km"].between(dmin, dmax)]
if REGIONS[region]:
    f = f[f["storm_id"].isin(storms_in_bbox(h, REGIONS[region]))]
if q:
    f = f[f["name"].str.contains(q, case=False, na=False)]

section("Overview")
c = st.columns(4)
c[0].metric("Storms found", f"{len(f):,}")
c[1].metric("Hurricanes (Category 1+)", f"{f['max_category'].str.startswith('Cat').sum():,}")
c[2].metric("Peak wind", f"{f['max_wind_kt'].max():.0f} kt" if len(f) else "Data unavailable")
c[3].metric("Lowest pressure", f"{f['min_pressure_mb'].min():.0f} mb" if len(f) and f["min_pressure_mb"].notna().any() else "Data unavailable")
if f.empty:
    callout("No storms match these filters.", "warn"); st.stop()

cc = st.columns(2)
with cc[0]:
    by_year = f.groupby("year").size().reindex(range(y0, y1 + 1), fill_value=0)
    fig = go.Figure(go.Bar(x=by_year.index, y=by_year.values, marker_color=PALETTE["turquoise"]))
    show_plot(style_fig(fig, f"How many storms passed within {dmax:,} km of {loc.name}, each year", 300, legend=False))
with cc[1]:
    cnt = f["max_category"].value_counts().reindex(CATEGORY_ORDER[1:], fill_value=0)
    fig = go.Figure(go.Bar(x=cnt.index, y=cnt.values, marker_color=[CATEGORY_COLORS[c_] for c_ in cnt.index]))
    show_plot(style_fig(fig, "How strong did they get? (peak category)", 300, legend=False))
cc = st.columns(2)
with cc[0]:
    fig = px.scatter(f, x="min_distance_km", y="max_wind_kt", color="max_category", color_discrete_map=CATEGORY_COLORS,
                     hover_data=["name", "year", "min_pressure_mb"], category_orders={"max_category": CATEGORY_ORDER})
    show_plot(style_fig(fig, "How close vs. how strong (each dot is a storm)", 340))
with cc[1]:
    dec = f.assign(decade=(f["year"] // 10) * 10).groupby("decade").size()
    fig = go.Figure(go.Bar(x=dec.index.astype(str) + "s", y=dec.values, marker_color=PALETTE["sky"]))
    show_plot(style_fig(fig, "Storms per decade", 340, legend=False))

section("Storm paths")
show_n = min(len(f), 300)
st.caption(f"Showing {show_n} of {len(f)} storm paths. Colour = strongest the storm became (see legend).")
sub = h[h["storm_id"].isin(f.sort_values("min_distance_km")["storm_id"].head(show_n))]
hstyle = st.radio("Map style", maps.STYLES, horizontal=True, key="hist_style")
fig = maps.base_fig(hstyle, loc.lat + 6, loc.lon + 4, 3.4, 620, "hist")
maps.add_rings(fig, loc, hstyle)
maps.add_tracks(fig, sub, show_n)
maps.add_locations(fig, loc, hstyle)
show_map(fig, key="hist_map")
st.markdown(maps.category_legend_html(), unsafe_allow_html=True)
st.caption("Hover or tap a path to see the storm's name, year and peak strength.")

section("Storm list (closest first)")
tbl = f.sort_values("min_distance_km")[["name", "year", "max_category", "max_wind_kt", "min_pressure_mb", "min_distance_km", "closest_time", "wind_at_closest_kt", "start", "end"]]
show_df(tbl.round(1))
download_buttons(tbl, "historical_storms", "hs")

section("Look at one storm")
pick = st.selectbox("Storm", f.sort_values("min_distance_km")["storm_id"], format_func=lambda i: f"{S.set_index('storm_id').loc[i, 'name']} {S.set_index('storm_id').loc[i, 'year']} ({i})")
g = h[h["storm_id"] == pick].assign(distance_km=lambda d: haversine_km(d["lat"], d["lon"], loc.lat, loc.lon))
fig = go.Figure()
fig.add_scatter(x=g["time"], y=g["wind_kt"], name="Wind (kt)", line=dict(color=PALETTE["coral"]))
fig.add_scatter(x=g["time"], y=g["pressure_mb"], name="Pressure (mb)", yaxis="y2", line=dict(color=PALETTE["sky"]))
fig.add_scatter(x=g["time"], y=g["distance_km"], name="Distance (km)", yaxis="y3", line=dict(color=PALETTE["sun"], dash="dot"))
fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False), yaxis3=dict(overlaying="y", visible=False))
show_plot(style_fig(fig, height=320))
fig1 = maps.base_fig(hstyle, g["lat"].mean(), g["lon"].mean(), 4, 480, f"one_{pick}")
maps.add_tracks(fig1, g, 1)
maps.add_locations(fig1, loc, hstyle)
show_map(fig1, key="hist_one")
download_buttons(g, f"hurdat_{pick}", "hg")

glossary(['Saffir-Simpson category', 'Knot (kn)', 'Air pressure'])
