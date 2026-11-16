"""Marine report builder (Markdown + HTML + JSON from one structure). Never invents data."""
from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd

from utils.config import DISCLAIMER, UNAVAILABLE
from utils.formatting import fmt, fmt_dt, is_missing


def _row(label, value, unit="", source="", decimals=1, note=""):
    return {"label": label, "value": fmt(value, unit, decimals), "source": source or "—", "note": note}


def build_report(ctx: dict) -> dict:
    """ctx: location, snapshot, sea_level, risk, storms (DataFrame|None), storm_error, anomalies, sources."""
    snap, loc = ctx.get("snapshot", {}), ctx["location"]

    def g(key, label, unit, dec=1):
        s = snap.get(key) or {}
        return _row(label, s.get("value"), unit, s.get("source", ""), dec)

    sl = ctx.get("sea_level")
    sections = [("Current conditions", [
        _row("Sea level", sl["value"], "m", sl["source"], 2, f"anomaly vs hist. mean: {fmt(sl.get('anomaly'), 'm', 2)}") if sl else _row("Sea level", None),
        g("sea_surface_temperature", "Sea surface temperature", "°C"),
        g("wave_height", "Wave height", "m", 2), g("wave_period", "Wave period", "s"),
        g("wave_direction", "Wave direction", "°", 0), g("swell_wave_height", "Swell height", "m", 2),
        g("wind_speed_10m", "Wind speed", "kn"), g("wind_gusts_10m", "Wind gusts", "kn"),
        g("wind_direction_10m", "Wind direction", "°", 0), g("pressure_msl", "Sea-level pressure", "hPa"),
        g("temperature_2m", "Air temperature", "°C"), g("precipitation", "Rain (last hour)", "mm", 1),
    ])]
    r = ctx.get("risk")
    if r is not None:
        sections.append(("Marine conditions indicator (rule-based system estimate - not official)", [
            {"label": "Overall", "value": f"{r.meta['emoji']} {r.meta['label']}", "source": "This app (configurable rules)", "note": "; ".join(r.reasons)}]))
    storms = ctx.get("storms")
    rows = []
    if storms is None:
        rows.append({"label": "Active cyclones", "value": UNAVAILABLE + ".", "source": "NOAA NHC", "note": ctx.get("storm_error") or ""})
    elif storms.empty:
        rows.append({"label": "Active cyclones", "value": "None reported by NHC", "source": "NOAA NHC", "note": ""})
    else:
        for _, s in storms.head(5).iterrows():
            rows.append({"label": f"{s['name']} ({s['classification_label']})",
                         "value": f"{fmt(s['distance_km'], 'km', 0)} {s['direction_from_ref']} of {loc['name']}",
                         "source": "NOAA NHC position; distance computed by this app",
                         "note": f"{fmt(s['intensity_kt'], 'kt', 0)}, {fmt(s['pressure_mb'], 'mb', 0)}"})
    sections.append(("Tropical cyclones", rows))
    an = ctx.get("anomalies")
    sections.append(("Is it unusual? (compared with the last 30 days)", [
        {"label": a["variable"], "value": a["status"], "source": "This app", "note": ""} for _, a in an.iterrows()]
        if an is not None and not an.empty else [{"label": "Anomalies", "value": UNAVAILABLE + ".", "source": "—", "note": ""}]))
    sections.append(("Source status", [{"label": s["source"], "value": "OK" if s["ok"] else UNAVAILABLE, "source": "", "note": s.get("message", "")}
                                       for s in ctx.get("sources", [])]))

    now = ctx.get("generated_at") or datetime.now(timezone.utc)
    title = f"Marine Report - {loc['name']} ({loc['lat']:.2f}, {loc['lon']:.2f})"
    md = [f"# {title}", f"*Generated: {fmt_dt(now)}*", ""]
    for name, rows in sections:
        md += [f"## {name}", "", "| Item | Value | Source | Note |", "|---|---|---|---|"]
        md += [f"| {r['label']} | {r['value']} | {r['source']} | {r['note']} |" for r in rows] + [""]
    md += [f"> {DISCLAIMER}"]

    h = [f"<html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>"
         "body{font-family:Segoe UI,Arial,sans-serif;max-width:900px;margin:2rem auto;color:#06222F}"
         "h1{color:#0E7490}h2{color:#0B3A4F;border-bottom:2px solid #14D9C4}table{border-collapse:collapse;width:100%}"
         "td,th{border:1px solid #cfe9ee;padding:6px 8px;text-align:left;font-size:14px}th{background:#e6f7fa}"
         ".d{background:#fff6e0;border-left:4px solid #FFC857;padding:8px;margin-top:1rem}</style></head><body>",
         f"<h1>{html.escape(title)}</h1><p><i>Generated: {html.escape(fmt_dt(now))}</i></p>"]
    for name, rows in sections:
        h.append(f"<h2>{html.escape(name)}</h2><table><tr><th>Item</th><th>Value</th><th>Source</th><th>Note</th></tr>")
        h += [f"<tr><td>{html.escape(str(r['label']))}</td><td>{html.escape(str(r['value']))}</td>"
              f"<td>{html.escape(str(r['source']))}</td><td>{html.escape(str(r['note']))}</td></tr>" for r in rows]
        h.append("</table>")
    h.append(f"<div class='d'>{html.escape(DISCLAIMER)}</div></body></html>")
    return {"markdown": "\n".join(md), "html": "".join(h),
            "json": {"title": title, "generated_at": now.isoformat(), "sections": {n: r for n, r in sections}, "disclaimer": DISCLAIMER}}
