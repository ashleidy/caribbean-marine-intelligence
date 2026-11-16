"""Plain-English helpers so non-scientists can read the numbers (units, words, glossary)."""
from __future__ import annotations

import math

from utils.formatting import is_missing

M_TO_FT = 3.28084
KN_TO_MPH = 1.15078
KN_TO_KMH = 1.852
KM_TO_MI = 0.621371

CARDINAL_NAMES = ["north", "north-northeast", "northeast", "east-northeast", "east", "east-southeast", "southeast",
                  "south-southeast", "south", "south-southwest", "southwest", "west-southwest", "west", "west-northwest",
                  "northwest", "north-northwest"]


def cardinal_name(deg) -> str:
    if is_missing(deg):
        return "unknown direction"
    return CARDINAL_NAMES[int((float(deg) % 360) / 22.5 + 0.5) % 16]


# (upper bound in metres, description) - Douglas sea scale
_SEA = [(0.1, "glassy calm"), (0.5, "calm"), (1.25, "slight"), (2.5, "moderate"), (4.0, "rough"),
        (6.0, "very rough"), (9.0, "high"), (math.inf, "very high")]
# (upper bound in knots, description) - Beaufort scale
_WIND = [(1, "calm"), (3, "light air"), (6, "a light breeze"), (10, "a gentle breeze"), (16, "a moderate breeze"),
         (21, "a fresh breeze"), (27, "a strong breeze"), (33, "a near gale"), (40, "a gale"), (47, "a strong gale"),
         (55, "storm-force wind"), (63, "violent storm-force wind"), (math.inf, "hurricane-force wind")]


def sea_state_word(h_m) -> str:
    return next(w for lim, w in _SEA if h_m < lim)


def wind_word(kn) -> str:
    return next(w for lim, w in _WIND if kn < lim)


def wave_units(h_m: float) -> str:
    return f"{h_m:.1f} m ({h_m * M_TO_FT:.1f} ft)"


def wind_units(kn: float) -> str:
    return f"{kn:.0f} kn ({kn * KN_TO_MPH:.0f} mph, {kn * KN_TO_KMH:.0f} km/h)"


def conditions_sentence(vals: dict) -> str:
    """One readable paragraph describing the sea and wind right now."""
    parts = []
    h, per, wdir = vals.get("wave_height"), vals.get("wave_period"), vals.get("wave_direction")
    if not is_missing(h):
        s = f"The sea is **{sea_state_word(h)}**, with waves about {wave_units(h)} high"
        if not is_missing(wdir):
            s += f" coming from the {cardinal_name(wdir)}"
        if not is_missing(per):
            s += f", arriving about every {per:.0f} seconds"
        parts.append(s + ".")
    w, g, d = vals.get("wind_speed_10m"), vals.get("wind_gusts_10m"), vals.get("wind_direction_10m")
    if not is_missing(w):
        s = f"The wind is **{wind_word(w)}** at {wind_units(w)}"
        if not is_missing(d):
            s += f" from the {cardinal_name(d)}"
        if not is_missing(g):
            s += f", with gusts up to {g:.0f} kn"
        parts.append(s + ".")
    t = vals.get("sea_surface_temperature")
    if not is_missing(t):
        parts.append(f"The sea water is {t:.1f} °C ({t * 9 / 5 + 32:.0f} °F).")
    return " ".join(parts) if parts else "Data unavailable."


GLOSSARY = {
    "Wave height": "The average height of the highest third of the waves, from trough to crest. Individual waves can be up to about twice as high.",
    "Time between waves (period)": "Seconds between one wave crest and the next. Longer periods (10 s or more) mean powerful, long-travelled waves.",
    "Swell": "Long, smooth waves created by storms far away. They can arrive even when local weather is calm.",
    "Sea level": "The height of the sea surface. It rises and falls with the tide every ~12 hours and is also pushed up by low pressure and strong onshore wind.",
    "Anomaly": "A reading that is unusual compared with what is normal for this place. 'Unusual' means it only happens a small share of the time; 'Very unusual' means it is rare.",
    "Normal range (green band)": "The band where most readings fall. A line leaving the band is what the app calls an anomaly.",
    "Knot (kn)": "One nautical mile per hour. 1 kn = 1.15 mph = 1.85 km/h.",
    "Wind gust": "A brief peak of wind, stronger than the average wind.",
    "Air pressure": "Low pressure usually means stormy weather; falling pressure can warn of an approaching system. Hurricanes have very low pressure at their centre.",
    "Cone of uncertainty": "The white area on a hurricane map shows where the CENTRE of the storm may travel (about 2 out of 3 times). It does NOT show the size of the storm, and dangerous weather can occur far outside it.",
    "Saffir-Simpson category": "A 1-5 scale for hurricanes based on wind speed: Cat 1 (74-95 mph) up to Cat 5 (157 mph or more). Tropical storms are 39-73 mph.",
    "Watch vs. warning": "A WATCH means hazardous conditions are possible within about 48 hours. A WARNING means they are expected within about 36 hours. Only official agencies issue them.",
}
