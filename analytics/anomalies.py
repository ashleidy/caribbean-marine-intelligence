"""Statistical anomaly detection (z-score, rolling z-score, IQR, percentiles) with plain-English output.

Levels: 0 = NORMAL, 1 = ANOMALY, 2 = EXTREME ANOMALY (technical labels).
For general audiences the app also uses: Normal / Unusual / Very unusual.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.statistics import remove_cycle

LEVEL_LABELS = {0: "NORMAL", 1: "ANOMALY", 2: "EXTREME ANOMALY"}
LAY_LABELS = {0: ("Normal", "🟢"), 1: ("Unusual", "🟡"), 2: ("Very unusual", "🔴")}
METHODS = {"zscore": "Compared with the whole record (z-score)", "rolling_z": "Compared with recent weeks (rolling average)",
           "iqr": "Outside the typical spread (IQR)", "percentile": "Among the highest / lowest readings (percentiles)"}


def detect(s: pd.Series, method: str = "rolling_z", *, z_anom: float = 2.0, z_ext: float = 3.0,
           window: int = 168, iqr_k: float = 1.5, iqr_ext: float = 3.0,
           p_anom: float = 2.5, p_ext: float = 0.5, detrend_tide: bool = False) -> pd.DataFrame:
    """DataFrame[value, score, level, label, typical, lower, upper] - lower/upper = the 'normal range'."""
    cols = ["value", "score", "level", "label", "typical", "lower", "upper"]
    s = s.dropna().astype(float)
    if detrend_tide:
        s = remove_cycle(s).dropna()
    if len(s) < 10:
        return pd.DataFrame(columns=cols)
    if method == "zscore":
        mean, std = s.mean(), (s.std(ddof=1) or np.nan)
        score = (s - mean) / std
        typical, lower, upper = pd.Series(mean, s.index), pd.Series(mean - z_anom * std, s.index), pd.Series(mean + z_anom * std, s.index)
        level = np.where(score.abs() >= z_ext, 2, np.where(score.abs() >= z_anom, 1, 0))
    elif method == "rolling_z":
        w = max(10, min(window, len(s)))
        mp = max(5, w // 4)
        mean, std = s.rolling(w, min_periods=mp).mean().shift(1), s.rolling(w, min_periods=mp).std().shift(1)  # no look-ahead
        score = (s - mean) / std.replace(0, np.nan)
        typical, lower, upper = mean, mean - z_anom * std, mean + z_anom * std
        level = np.where(score.abs() >= z_ext, 2, np.where(score.abs() >= z_anom, 1, 0))
    elif method == "iqr":
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = (q3 - q1) or np.nan
        dist = np.maximum(q1 - s, s - q3).clip(lower=0) / iqr
        score = pd.Series(np.where(s > q3, (s - q3) / iqr, np.where(s < q1, (s - q1) / iqr, 0.0)), index=s.index)
        typical, lower, upper = pd.Series(s.median(), s.index), pd.Series(q1 - iqr_k * iqr, s.index), pd.Series(q3 + iqr_k * iqr, s.index)
        level = np.where(dist >= iqr_ext, 2, np.where(dist >= iqr_k, 1, 0))
    elif method == "percentile":
        lo_a, hi_a = s.quantile(p_anom / 100), s.quantile(1 - p_anom / 100)
        lo_e, hi_e = s.quantile(p_ext / 100), s.quantile(1 - p_ext / 100)
        score = s.rank(pct=True) * 100
        typical, lower, upper = pd.Series(s.median(), s.index), pd.Series(lo_a, s.index), pd.Series(hi_a, s.index)
        level = np.where((s <= lo_e) | (s >= hi_e), 2, np.where((s <= lo_a) | (s >= hi_a), 1, 0))
    else:
        raise ValueError(f"Unknown method {method}")
    out = pd.DataFrame({"value": s, "score": score, "level": level, "typical": typical, "lower": lower, "upper": upper}, index=s.index)
    out["level"] = out["level"].astype(int)
    out.loc[out["score"].isna(), "level"] = 0
    out["label"] = out["level"].map(LEVEL_LABELS)
    return out[cols]


def latest_status(s: pd.Series, **kwargs) -> dict | None:
    res = detect(s, **kwargs)
    if res.empty:
        return None
    last = res.iloc[-1]
    return {"time": res.index[-1], "value": float(last["value"]), "score": float(last["score"]) if pd.notna(last["score"]) else None,
            "level": int(last["level"]), "label": str(last["label"])}


_TAIL = {0: "That is inside the normal range - nothing out of the ordinary.",
         1: "That is outside the normal range. Readings like this are uncommon (roughly 1 in 20 or rarer).",
         2: "That is far outside the normal range. Readings like this are rare (roughly 1 in 100 or rarer)."}


def plain_summary(res: pd.DataFrame, label: str, unit: str, decimals: int = 1, detrended: bool = False) -> dict | None:
    """Explain the latest reading in everyday language."""
    if res is None or res.empty:
        return None
    last = res.iloc[-1]
    level = int(last["level"])
    lay, emoji = LAY_LABELS[level]
    diff = float(last["value"] - last["typical"]) if pd.notna(last["typical"]) else None
    side = "above" if (diff or 0) >= 0 else "below"
    if detrended:
        head = (f"Once the normal daily rise and fall of the tide is removed, {label.lower()} is "
                f"{abs(diff):.{decimals + 1}f} {unit} {side} its usual level." if diff is not None else f"{label}: not enough history.")
    else:
        head = (f"{label} is {last['value']:.{decimals}f} {unit}, which is {abs(diff):.{decimals}f} {unit} {side} the usual level."
                if diff is not None else f"{label} is {last['value']:.{decimals}f} {unit} (not enough history to compare).")
    return {"level": level, "lay": lay, "emoji": emoji, "technical": LEVEL_LABELS[level], "text": f"{head} {_TAIL[level]}",
            "value": float(last["value"]), "typical": float(last["typical"]) if pd.notna(last["typical"]) else None, "diff": diff}


def anomaly_summary(frame: pd.DataFrame, variables: dict[str, str], now: pd.Timestamp | None = None,
                    units: dict[str, str] | None = None) -> pd.DataFrame:
    """Latest status per variable (rolling 30-day z-score; sea level is tide-filtered)."""
    now = now or pd.Timestamp.now(tz="UTC")
    units = units or {}
    rows = []
    for col, label in variables.items():
        if frame is None or col not in frame.columns:
            rows.append({"variable": label, "status": "Data unavailable", "lay": "Data unavailable", "emoji": "⚪", "text": "Data unavailable."})
            continue
        det = col == "sea_level_height_msl"
        res = detect(frame.loc[frame.index <= now, col], "rolling_z", window=720, detrend_tide=det)
        ps = plain_summary(res, label, units.get(col, ""), 2 if det else 1, det)
        rows.append({"variable": label, "status": ps["technical"] if ps else "Data unavailable", "lay": ps["lay"] if ps else "Data unavailable",
                     "emoji": ps["emoji"] if ps else "⚪", "text": ps["text"] if ps else "Data unavailable.",
                     "value": ps["value"] if ps else None, "diff": ps["diff"] if ps else None})
    return pd.DataFrame(rows)
