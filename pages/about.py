"""Data sources, methodology, limits, licensing and live source checks."""
import streamlit as st

from services import noaa_nhc
from utils.config import DISCLAIMER
from utils.data import load_all_storms, load_marine, load_weather, store
from utils.ui import glossary, callout, chips, current_location, page_title, section

page_title("🔎", "DATA SOURCES", "Provenance, methods and limits of every number shown")
callout(f"<b>{DISCLAIMER}</b>", "warn")

section("Sources")
st.markdown("""
| Source | Used for | Access mechanism | Links |
|---|---|---|---|
| **Open-Meteo Marine** | waves, swell, SST, currents, modelled sea level | REST `marine-api.open-meteo.com/v1/marine` | [docs](https://open-meteo.com/en/docs/marine-weather-api) |
| **Open-Meteo Weather** | temperature, humidity, rain, pressure, wind, clouds | REST `api.open-meteo.com/v1/forecast` (+ ERA5 archive endpoint for history) | [docs](https://open-meteo.com/en/docs) |
| **NOAA NHC** | active storms in the Atlantic, East & Central Pacific: cone, track, warnings, wind radii, best track, HURDAT2 | `CurrentStorms.json` + GIS zip files + HURDAT2 text | [GIS](https://www.nhc.noaa.gov/gis/) · [data](https://www.nhc.noaa.gov/data/) |
| **NOAA NCEI ERDDAP** | SST, currents, waves, salinity, buoys, satellite | HTTP (search / tabledap / griddap → CSV) | [ERDDAP](https://www.ncei.noaa.gov/erddap/) · [REST](https://www.ncei.noaa.gov/erddap/rest.html) |
| **GDACS** (UN / European Commission) | tropical cyclones in every other ocean basin (Asia, Indian Ocean, Oceania) | REST `gdacs.org/gdacsapi/api` (relays JTWC & NOAA data) | [GDACS](https://www.gdacs.org) · [API docs](https://www.gdacs.org/gdacsapi/swagger/index.html) |
| **NASA GIBS** | real satellite imagery used as the map background (VIIRS true colour, updated daily) | WMTS tiles `gibs.earthdata.nasa.gov` | [GIBS](https://earthdata.nasa.gov/gibs) |
""")

section("Live status")
loc = current_location()
if st.button("Check sources now"):
    _, nhc_r, gd_r = load_all_storms(loc)
    chips([load_marine(loc), load_weather(loc), nhc_r, gd_r])
st.caption(f"Local observation store: {store().count():,} rows · NHC GeoPandas support: {'yes' if noaa_nhc.HAS_GEO else 'no'}")

section("Method notes")
st.markdown("""
* **Official vs computed.** NHC positions, intensity, cone, track and watches/warnings are reproduced from NOAA/NHC. Distances, bearings, closest approach, trends, categories derived from wind, anomalies, risk levels and estimates are **computed by this app** and are never presented as alerts.
* **Marine-conditions indicator.** Worst level among wave height, wind, gusts and rain rate against editable thresholds (sidebar). Transparent rules, not maritime safety advice.
* **Anomalies.** Z-score, rolling z-score (look-ahead free), IQR fences and percentiles; levels NORMAL / ANOMALY / EXTREME ANOMALY. Sea level can be tide-filtered with a 25 h centred mean.
* **Estimates.** Moving average, linear regression, Holt-Winters, ARIMA - always shown with a backtest against persistence. Not forecasts.
* **Sea level.** The Open-Meteo series is a computer-model estimate (tide + sea level), not a tide-gauge measurement.
* **Closest approach (HURDAT2).** 6-hourly fixes linearly interpolated to ~1 h; real storms curve, so treat as an estimate.
* **Missing data** are shown as *Data unavailable* and never filled or invented. A failing source never stops the others.
* **Timestamps** are stored in UTC and displayed in Colombia time (UTC-5).
""")

section("Licensing & operations")
st.markdown("""
* Open-Meteo's free API is intended for **non-commercial use**; a commercial deployment needs their paid plan (the code is ready for a key via `st.secrets`). Attribution: Open-Meteo.com (CC BY 4.0).
* NOAA/NHC and NCEI data are U.S. Government works, publicly available; cite NOAA as the source.
* GDACS and NASA GIBS data are free to use with attribution (GDACS: UN OCHA / European Commission JRC; imagery: NASA GIBS / EOSDIS).
* Streamlit Community Cloud storage is ephemeral: the SQLite store and Parquet files rebuild after a reboot.
""")

section('Glossary')
glossary(title='📖 Plain-English glossary')
