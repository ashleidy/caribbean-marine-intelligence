"""Worldwide tropical cyclone tracker: NOAA NHC (Atlantic / E & C Pacific, full detail) + GDACS (all other basins)."""
import pandas as pd
import streamlit as st

from analytics.cyclones import CATEGORY_COLORS, category_from_wind, closest_approach, intensity_trend, movement_from_points
from services.noaa_nhc import WW_LABELS, normalize_best_track_points, normalize_forecast_points
from utils import maps
from utils.charts import intensity_chart
from utils.config import MAP_REGIONS
from utils.data import load_all_storms, load_best_track, load_forecast_package, load_gdacs_track
from utils.export import download_buttons
from utils.formatting import fmt_dt
from utils.plain import KM_TO_MI, KN_TO_MPH, cardinal_name
from utils.ui import (badge, callout, chips, current_location, glossary, page_title, plain_box, section, show_df, show_map, show_plot,
                      storm_card, unavailable)

loc = current_location()
page_title("🌀", "TROPICAL CYCLONES - WORLDWIDE", "Live tracker for hurricanes, typhoons and tropical cyclones in every ocean basin · tap or hover over a storm for its name and data")
combined, nhc_res, gd_res = load_all_storms(loc)
chips([nhc_res, gd_res])
st.markdown(badge("official", "OFFICIAL · NOAA/NHC (Americas)") + badge("official", "GDACS · JTWC / NOAA data (rest of the world)") + badge("calc", "CALCULATED · this app"),
            unsafe_allow_html=True)

c = st.columns([2.2, 1.6, 1.2])
region = c[0].selectbox("Map region", list(MAP_REGIONS), help="'Auto' frames wherever the active storms are right now. Pick 'World' to see every basin at once.")
style = c[1].radio("Map style", maps.STYLES, horizontal=True)
rings = c[2].toggle(f"Distance rings", value=False, help=f"250 / 500 / 1,000 km around {loc.name}")

if not combined.ok:
    unavailable(combined, "active storms")
    st.stop()
df = combined.data


def category_text(r) -> tuple[str, str]:
    """(plain type name, accent colour)."""
    cat = category_from_wind(r["intensity_kt"])
    color = CATEGORY_COLORS[cat]
    label = str(r["classification_label"])
    if str(r["classification"]) == "HU":
        n = cat.replace("Cat ", "")
        return f"Hurricane · Category {n}" + (" (major hurricane)" if n in ("3", "4", "5") else ""), color
    if r["source"] != "NOAA NHC" and cat.startswith("Cat"):
        return f"{label} · ≈ Category {cat.replace('Cat ', '')} equivalent", color
    return label, color


def mph(kt):
    return f"{kt * KN_TO_MPH:.0f} mph ({kt:.0f} kt)" if pd.notna(kt) else "Data unavailable"


if df.empty:
    callout("✅ <b>No active tropical cyclones are being reported anywhere in the world right now</b> (NOAA NHC + GDACS). The map will fill in as soon as a system is "
            "named. Seasons: Atlantic Jun 1 - Nov 30 · East Pacific May 15 - Nov 30 · West Pacific, mostly Jun - Dec but possible all year · "
            "South Indian / Australia / South Pacific Nov - Apr · North Indian Apr - Jun and Oct - Dec.", "info")
    cfg = MAP_REGIONS[region] or MAP_REGIONS["World (all active storms)"]
    fig = maps.base_fig(style, cfg["lat"], cfg["lon"], cfg["zoom"], 600, region)
    if rings:
        maps.add_rings(fig, loc, style)
    maps.add_locations(fig, loc, style)
    show_map(fig, key="storm_map_empty")
    glossary(["Cone of uncertainty", "Saffir-Simpson category", "Watch vs. warning"])
    st.stop()

# --------------------------------------------------------------------------- load map products for every storm
fcs, pasts, pk, notes = {}, {}, {}, []
with st.spinner(f"Loading tracks for {len(df)} active storm(s)…"):
    for i, r in df.iterrows():
        sid = r["id"]
        if r["source"] == "NOAA NHC":
            p = load_forecast_package(r["forecast_zip"])
            pk[sid] = p.data if p.ok else None
            fcs[sid] = normalize_forecast_points(p.data["points"]) if p.ok and p.data.get("points") is not None else pd.DataFrame()
            b = load_best_track(r["best_track_zip"])
            pasts[sid] = normalize_best_track_points(b.data["points"]) if b.ok and b.data.get("points") is not None else pd.DataFrame()
            if not p.ok:
                notes.append(f"{r['name']}: forecast cone/track unavailable ({p.message[:80]})")
        else:
            t = load_gdacs_track(r["eventid"], r["intensity_kt"] * 1.852 if pd.notna(r["intensity_kt"]) else None)
            pk[sid] = None
            fcs[sid] = t.data["forecast"] if t.ok else pd.DataFrame()
            pasts[sid] = t.data["observed"] if t.ok else pd.DataFrame()
            if t.ok:                                  # movement from the observed positions (calculated)
                mv = movement_from_points(pasts[sid])
                if mv:
                    df.loc[i, "movement_dir_deg"], df.loc[i, "movement_speed_kt"] = mv["direction_deg"], mv["speed_kt"]
                    df.loc[i, "movement_speed_mph"] = mv["speed_kt"] * KN_TO_MPH
            else:
                notes.append(f"{r['name']}: GDACS track unavailable ({t.message[:80]})")

by_basin = df["basin"].value_counts()
section(f"{len(df)} active system{'s' if len(df) > 1 else ''} worldwide · " + ", ".join(f"{n} in {b}" for b, n in by_basin.items()))

# --------------------------------------------------------------------------- map
cfg = MAP_REGIONS[region]
if cfg is None:
    lats = list(df["lat"]) + [v for f in fcs.values() for v in f.get("lat", [])]
    lons = list(df["lon"]) + [v for f in fcs.values() for v in f.get("lon", [])]
    lat0, lon0, zoom = maps.fit_view(lats, lons)
else:
    lat0, lon0, zoom = cfg["lat"], cfg["lon"], cfg["zoom"]
fig = maps.base_fig(style, lat0, lon0, zoom, 640, region)
if rings:
    maps.add_rings(fig, loc, style)
for sid, name in zip(df["id"], df["name"]):
    maps.add_forecast_pkg(fig, pk.get(sid), style)
    maps.add_past_track(fig, pasts.get(sid), style, str(name).upper())
    maps.add_forecast_points(fig, fcs.get(sid), style, str(name).upper())
maps.add_locations(fig, loc, style)
maps.add_storm_markers(fig, df, style, loc.name)

ids = list(df["id"])
if st.session_state.get("storm_sel") not in ids:
    st.session_state["storm_sel"] = ids[0]
clicked = show_map(fig, key="storm_map", select=True)
if clicked in ids:
    st.session_state["storm_sel"] = clicked
if style.startswith("Satellite"):
    st.caption(f"Background: real NASA VIIRS satellite image from {maps.satellite_date()} (UTC) - the white swirls are clouds. Zoom with the scroll wheel or pinch; drag to move.")
st.markdown("**Storm strength:** " + maps.category_legend_html(), unsafe_allow_html=True)
st.markdown("**Watches & warnings (official NHC):** " + maps.ww_legend_html() +
            " &nbsp;·&nbsp; **White area** = cone of uncertainty (NHC storms) &nbsp;·&nbsp; **Line with dots** = forecast path &nbsp;·&nbsp; **Grey line** = where it has been", unsafe_allow_html=True)
for n in notes:
    st.caption("⚠ " + n)
with st.expander("How to read this map"):
    st.markdown("""
* The **large coloured circle with a name** is the storm's current centre; colour = strength (see legend). **Hover (or tap on a phone) to see its name and data.**
* The **white cone** (NHC storms) shows where the *centre* is likely to travel (about 2 out of 3 times). **It does not show how big the storm is** - rain, wind and surge reach well outside it.
* **Dots on the forecast line** are future positions with day/time; their colour is the expected strength.
* **Thick coloured coastal lines** are official watches and warnings issued by the NHC.
* Storms outside the Americas come from **GDACS** (UN / European Commission), which relays JTWC and NOAA data. They have no cone or official warnings here; for those use your national agency (JMA, IMD, BoM, Fiji Met, Météo-France La Réunion, PAGASA...).
""")

# --------------------------------------------------------------------------- cards
section("All active storms")
cols = st.columns(3)
for i, (_, r) in enumerate(df.iterrows()):
    kind, color = category_text(r)
    with cols[i % 3]:
        storm_card(str(r["name"]).upper(), kind, color, [
            ("Wind (sustained)", mph(r["intensity_kt"])),
            ("Pressure", f"{r['pressure_mb']:.0f} mb" if pd.notna(r["pressure_mb"]) else "Data unavailable"),
            ("Moving", f"{cardinal_name(r['movement_dir_deg'])} at {r['movement_speed_mph']:.0f} mph" if pd.notna(r["movement_speed_mph"]) else "Data unavailable"),
            (f"Distance to {loc.name.split(' &')[0]}", f"{r['distance_km']:,.0f} km ({r['distance_km'] * KM_TO_MI:,.0f} mi)"),
        ], f"{r['basin']} · {r['source']} · updated {fmt_dt(r['last_update'])}")

section(f"Closest storms to {loc.name}")
rank = pd.DataFrame({"Storm": df["name"].str.upper(), "Ocean basin": df["basin"], "Type": df.apply(lambda r: category_text(r)[0], axis=1),
                     "Wind (mph)": (df["intensity_kt"] * KN_TO_MPH).round(0), "Distance (km)": df["distance_km"].round(0),
                     "Distance (mi)": (df["distance_km"] * KM_TO_MI).round(0), "Direction": df["direction_from_ref"], "Source": df["source"]})
show_df(rank)
st.caption("Position, wind and type come from the listed source. Distance and direction are calculated by this app - not an official alert.")
download_buttons(rank, "active_storms_worldwide", "storms")

# --------------------------------------------------------------------------- one storm in detail
section("Storm details")
sel = st.selectbox("Choose a storm (or tap one on the map)", ids, key="storm_sel", format_func=lambda i: f"{df.set_index('id').loc[i, 'name'].upper()} - {df.set_index('id').loc[i, 'basin']}")
s = df.set_index("id").loc[sel]
is_nhc = s["source"] == "NOAA NHC"
kind, color = category_text(s)
fc, bt = fcs[sel], pasts[sel]
links = [(l, s[k]) for l, k in (("Public advisory", "public_advisory_url"), ("Forecast advisory", "forecast_advisory_url"),
                                ("Forecast discussion", "discussion_url"), ("Graphics", "graphics_url")) if isinstance(s[k], str)]
st.markdown(f"**{str(s['name']).upper()} - {kind}** · source: {s['source']} · " + (" · ".join(f"[{l}]({u})" for l, u in links) if links else ""))
if not is_nhc:
    st.caption(f"GDACS impact alert level: **{s.get('alert_level') or 'n/a'}** (GDACS's own humanitarian-impact colour, not a wind category)"
               + (f" · affected area: {s['country']}" if isinstance(s.get("country"), str) and s["country"] else ""))

tr = intensity_trend(bt) if not bt.empty else {}
trend_txt = ""
if tr:
    trend_txt = {"Intensifying": "It is **getting stronger**", "Weakening": "It is **weakening**", "Steady": "Its strength is **about steady**"}[tr["label"]] + \
                f" (winds changed {tr['wind_change_kt'] * KN_TO_MPH:+.0f} mph over the last {tr['window_h']:.0f} hours). "
ca = closest_approach(fc["lat"], fc["lon"], None, loc.lat, loc.lon) if not fc.empty else None
ca_txt = (f"Along the forecast track its centre comes within about **{ca['min_km']:,.0f} km ({ca['min_km'] * KM_TO_MI:,.0f} mi)** of {loc.name} (calculated by this app)." if ca else "")
plain_box(f"{str(s['name']).title()} is a **{kind.lower()}** with sustained winds of {mph(s['intensity_kt'])}, currently about **{s['distance_km']:,.0f} km** "
          f"to the {cardinal_name(s['bearing_from_ref'])} of {loc.name}. {trend_txt}{ca_txt}")

cc = st.columns(2)
with cc[0]:
    f_ = intensity_chart(fc["tau_h"], fc["wind_kt"], "Forecast strength", "Hours from now") if not fc.empty and fc["wind_kt"].notna().sum() >= 2 else None
    show_plot(f_, key="fc_int") if f_ else unavailable(None, "forecast strength")
with cc[1]:
    f_ = intensity_chart(bt["time"], bt["wind_kt"], "Strength so far", "Date") if not bt.empty and bt["wind_kt"].notna().sum() >= 2 else None
    show_plot(f_, key="bt_int") if f_ else unavailable(None, "past strength")

if is_nhc:
    st.markdown("**Official watches & warnings (NHC)**")
    w = pk[sel].get("warnings") if pk.get(sel) else None
    if w is not None and len(w):
        col = next((c_ for c_ in w.columns if c_.lower() == "tcww"), None)
        if col:
            show_df(pd.DataFrame({"Code": w[col], "Official product (NHC)": w[col].map(lambda x: WW_LABELS.get(str(x), str(x)))}).drop_duplicates())
    else:
        st.write("None in the current NHC advisory package. For Colombian waters follow IDEAM, DIMAR and UNGRD; elsewhere, your national agency.")
    st.markdown("**Storm surge:** " + (f"[NHC storm-surge watch/warning (KML)]({s['surge_ww_kml']})" if isinstance(s["surge_ww_kml"], str) else "no storm-surge product listed by the NHC for this storm")
                + (f" · [potential surge flooding (GIS)]({s['surge_flooding_zip']})" if isinstance(s["surge_flooding_zip"], str) else ""))
else:
    st.info("Official warnings for this basin come from the local national agency (for example JMA, IMD, BoM, Fiji Met Service, Météo-France La Réunion, PAGASA). "
            "Use the GDACS link above for the international summary.")

if not fc.empty:
    section("Forecast positions")
    t = pd.DataFrame({"When": fc["label"], "Hours ahead": fc["tau_h"], "Wind (mph)": (fc["wind_kt"] * KN_TO_MPH).round(0),
                      "Category": fc["wind_kt"].map(category_from_wind).str.replace("Cat ", "Category "), "Latitude": fc["lat"].round(1), "Longitude": fc["lon"].round(1)})
    show_df(t)
    download_buttons(t, f"{sel}_forecast", "fc")
glossary(["Cone of uncertainty", "Saffir-Simpson category", "Watch vs. warning", "Air pressure", "Knot (kn)"])
