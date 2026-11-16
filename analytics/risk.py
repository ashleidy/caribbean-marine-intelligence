"""Transparent, configurable marine-conditions indicator.

NOT official maritime safety information. Each factor is mapped to a level by
simple thresholds (editable in the sidebar); the overall level is the worst factor.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from utils.config import PALETTE

LEVELS = [
    {"emoji": "🟢", "label": "Favorable conditions", "color": PALETTE["palm"]},
    {"emoji": "🟡", "label": "Caution", "color": PALETTE["sun"]},
    {"emoji": "🟠", "label": "Difficult conditions", "color": PALETTE["papaya"]},
    {"emoji": "🔴", "label": "Dangerous conditions", "color": PALETTE["coral"]},
]

# limits = lower bounds of levels 1, 2, 3 (yellow, orange, red). Roughly Beaufort-inspired; adjust to your fleet.
DEFAULT_THRESHOLDS = {
    "wave_height": {"label": "Wave height", "unit": "m", "limits": [1.0, 2.0, 3.0]},
    "wind_speed_10m": {"label": "Wind speed", "unit": "kn", "limits": [15.0, 22.0, 34.0]},
    "wind_gusts_10m": {"label": "Wind gusts", "unit": "kn", "limits": [22.0, 34.0, 48.0]},
    "precipitation": {"label": "Rain rate", "unit": "mm/h", "limits": [2.5, 7.6, 20.0]},
}


@dataclass
class RiskAssessment:
    level: int | None
    factors: list[dict] = field(default_factory=list)

    @property
    def meta(self) -> dict:
        return LEVELS[self.level] if self.level is not None else {"emoji": "⚪", "label": "Data unavailable", "color": PALETTE["muted"]}

    @property
    def reasons(self) -> list[str]:
        if self.level is None:
            return ["No marine/weather variables available"]
        return [f"{f['label']} {f['value']:.1f} {f['unit']} → {LEVELS[f['level']]['label']}"
                for f in self.factors if f["level"] == self.level and self.level > 0] or ["All available factors below caution limits"]


def level_for(value: float, limits: list[float]) -> int:
    return sum(value >= lim for lim in sorted(limits))


def evaluate(values: dict, thresholds: dict | None = None) -> RiskAssessment:
    th = thresholds or DEFAULT_THRESHOLDS
    factors = []
    for key, cfg in th.items():
        v = values.get(key)
        if v is None or pd.isna(v):
            continue
        factors.append({"key": key, "label": cfg["label"], "unit": cfg["unit"], "value": float(v),
                        "level": level_for(float(v), cfg["limits"])})
    return RiskAssessment(max((f["level"] for f in factors), default=None), factors)
