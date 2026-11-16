"""Descriptive statistics, trends and abrupt-change detection (interpretable, no ML)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def slice_period(obj, days: int | None, now: pd.Timestamp | None = None):
    """Observed window: (now - days, now]. days=None -> everything up to now."""
    now = now or pd.Timestamp.now(tz="UTC")
    obj = obj[obj.index <= now]
    return obj if days is None else obj[obj.index > now - pd.Timedelta(days=days)]


def describe(s: pd.Series, percentiles=(5, 25, 50, 75, 95)) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    out = {"count": int(s.size), "mean": float(s.mean()), "min": float(s.min()), "max": float(s.max()),
           "std": float(s.std(ddof=1)) if s.size > 1 else 0.0}
    out.update({f"p{p}": float(np.percentile(s, p)) for p in percentiles})
    return out


def linear_trend(s: pd.Series) -> dict:
    """OLS trend of daily means (removes tidal/diurnal cycles). Needs >= 3 days of data."""
    daily = s.dropna().resample("1D").mean().dropna()
    if len(daily) < 3:
        return {"ok": False, "reason": "needs >= 3 days of data"}
    x = (daily.index - daily.index[0]).total_seconds() / 86400.0
    r = stats.linregress(x, daily.to_numpy())
    return {"ok": True, "slope_per_day": float(r.slope), "slope_per_year": float(r.slope * 365.25),
            "p_value": float(r.pvalue), "r2": float(r.rvalue ** 2), "n_days": int(len(daily))}


def sudden_changes(s: pd.Series, window: str = "3h", k: float = 4.0) -> pd.DataFrame:
    """Flag windows whose change exceeds k robust standard deviations (MAD-based)."""
    s = s.dropna()
    if len(s) < 24:
        return pd.DataFrame(columns=["time", "change", "z"])
    ch = s.diff(periods=max(1, int(pd.Timedelta(window) / (s.index.to_series().diff().median() or pd.Timedelta("1h")))))
    mad = (ch - ch.median()).abs().median() * 1.4826
    if not mad or np.isnan(mad):
        return pd.DataFrame(columns=["time", "change", "z"])
    z = (ch - ch.median()) / mad
    flagged = z[z.abs() >= k].dropna()
    return pd.DataFrame({"time": flagged.index, "change": ch.loc[flagged.index].to_numpy(), "z": flagged.to_numpy()})


def remove_cycle(s: pd.Series, hours: int = 25) -> pd.Series:
    """Subtract a centred 25 h mean: removes diurnal/semi-diurnal tide so anomalies show weather/ocean signal."""
    return s - s.rolling(hours, center=True, min_periods=hours // 2).mean()
