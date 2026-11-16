"""Unit conversion and display formatting."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from utils.config import DISPLAY_TZ, UNAVAILABLE

MPH_TO_KT = 0.868976
KMH_TO_KT = 0.539957
MS_TO_KT = 1.943844
KT_TO_MS = 0.514444
KT_TO_KMH = 1.852


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def fmt(value: Any, unit: str = "", decimals: int = 1) -> str:
    """Format a number with unit, or the standard 'Data unavailable' text."""
    if is_missing(value):
        return UNAVAILABLE
    try:
        text = f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)
    return f"{text} {unit}".strip()


def to_local(ts, tz: str = DISPLAY_TZ):
    """Convert timestamps / indexes / Series (UTC or naive-UTC) to local time."""
    obj = pd.to_datetime(ts, utc=True) if not isinstance(ts, pd.DatetimeIndex) else ts
    if isinstance(obj, pd.DatetimeIndex):
        if obj.tz is None:
            obj = obj.tz_localize("UTC")
        return obj.tz_convert(tz)
    if isinstance(obj, pd.Series):
        return obj.dt.tz_convert(tz)
    return obj.tz_convert(tz)


def fmt_dt(ts, tz: str = DISPLAY_TZ, with_tz: bool = True) -> str:
    if is_missing(ts):
        return "—"
    t = to_local(pd.Timestamp(ts))
    return t.strftime("%d %b %Y %H:%M") + (" (UTC-5)" if with_tz and tz == DISPLAY_TZ else "")


CLASSIFICATION_LABELS = {
    "TD": "Tropical Depression", "STD": "Subtropical Depression", "TS": "Tropical Storm",
    "HU": "Hurricane", "STS": "Subtropical Storm", "PTC": "Post-tropical Cyclone / Remnants",
    "PC": "Potential Tropical Cyclone", "TY": "Typhoon",
}
