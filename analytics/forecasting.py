"""Simple, interpretable time-series estimates (system estimates, NOT official forecasts)."""
from __future__ import annotations

import numpy as np
import pandas as pd

METHODS = {"moving_average": "Moving average (24 h)", "linear": "Linear regression",
           "holt": "Exponential smoothing (Holt-Winters)", "arima": "ARIMA(2,1,1)"}
MIN_POINTS = 48


def _prep(series: pd.Series) -> pd.Series:
    s = series.dropna().sort_index()
    s = s[~s.index.duplicated()]
    return s.resample("1h").mean().interpolate(limit=6).dropna()


def _fit_predict(s: pd.Series, horizon: int, method: str, lookback: int):
    train = s.iloc[-lookback:] if len(s) > lookback else s
    if method == "moving_average":
        k = min(24, len(train))
        yhat = np.full(horizon, train.iloc[-k:].mean())
        sigma = float((train - train.rolling(k).mean()).std())
        band = np.full(horizon, 1.96 * sigma)
    elif method == "linear":
        x = np.arange(len(train))
        slope, icpt = np.polyfit(x, train.to_numpy(), 1)
        yhat = slope * (len(train) + np.arange(horizon)) + icpt
        sigma = float(np.std(train.to_numpy() - (slope * x + icpt)))
        band = np.full(horizon, 1.96 * sigma)
    elif method == "holt":
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        seasonal = "add" if len(train) >= 72 else None
        fit = ExponentialSmoothing(train, trend="add", damped_trend=True, seasonal=seasonal,
                                   seasonal_periods=24 if seasonal else None,
                                   initialization_method="estimated").fit()
        yhat = np.asarray(fit.forecast(horizon))
        band = np.full(horizon, 1.96 * float(np.std(fit.resid)))
    elif method == "arima":
        from statsmodels.tsa.arima.model import ARIMA

        fit = ARIMA(train, order=(2, 1, 1)).fit()
        fc = fit.get_forecast(horizon)
        yhat = np.asarray(fc.predicted_mean)
        ci = np.asarray(fc.conf_int(alpha=0.05))
        band = (ci[:, 1] - ci[:, 0]) / 2
    else:
        raise ValueError(f"Unknown method {method}")
    return yhat, band


def forecast_series(series: pd.Series, horizon: int = 48, method: str = "linear", lookback: int = 24 * 14) -> pd.DataFrame:
    """Hourly estimate with ~95 % band. Raises ValueError if history is too short."""
    s = _prep(series)
    if len(s) < MIN_POINTS:
        raise ValueError(f"Insufficient history: {len(s)} hourly points (need >= {MIN_POINTS})")
    yhat, band = _fit_predict(s, horizon, method, lookback)
    if not (np.isfinite(yhat).all() and np.isfinite(band).all()):
        raise ValueError(f"{method} did not converge on this series; try another model")
    idx = pd.date_range(s.index[-1] + pd.Timedelta("1h"), periods=horizon, freq="1h")
    return pd.DataFrame({"yhat": yhat, "lower": yhat - band, "upper": yhat + band}, index=idx)


def backtest(series: pd.Series, horizon: int = 24, method: str = "linear", lookback: int = 24 * 14) -> dict:
    """Hold out the last `horizon` hours; compare against the naive 'persistence' baseline."""
    s = _prep(series)
    if len(s) < MIN_POINTS + horizon:
        return {"ok": False, "reason": "not enough history for a backtest"}
    train, test = s.iloc[:-horizon], s.iloc[-horizon:]
    yhat, _ = _fit_predict(train, horizon, method, lookback)
    err = test.to_numpy() - yhat
    naive = test.to_numpy() - train.iloc[-1]
    mae, base = float(np.mean(np.abs(err))), float(np.mean(np.abs(naive)))
    return {"ok": True, "mae": mae, "rmse": float(np.sqrt(np.mean(err ** 2))), "baseline_mae": base,
            "skill_vs_persistence": (1 - mae / base) if base else None}
