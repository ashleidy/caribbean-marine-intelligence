"""CARIBBEAN MARINE INTELLIGENCE - entry point (navigation, theme, sidebar)."""
import streamlit as st

st.set_page_config(page_title="Caribbean Marine Intelligence", page_icon="🌊", layout="wide",
                   initial_sidebar_state="expanded")

from utils.ui import footer, inject_css, sidebar_controls  # noqa: E402  (after set_page_config)

inject_css()
sidebar_controls()

pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="🌊", default=True),
    st.Page("pages/hurricanes.py", title="Tropical Cyclones", icon="🌀"),
    st.Page("pages/ocean.py", title="Ocean & Waves", icon="🌡️"),
    st.Page("pages/weather.py", title="Weather", icon="⛅"),
    st.Page("pages/sea_level.py", title="Sea Level", icon="📏"),
    st.Page("pages/analysis.py", title="Anomalies & Trends", icon="📈"),
    st.Page("pages/historical.py", title="Historical Hurricanes", icon="🗂️"),
    st.Page("pages/about.py", title="Data Sources", icon="🔎"),
]
st.navigation(pages).run()
footer()
