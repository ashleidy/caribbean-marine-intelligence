"""Download helpers: CSV / Excel / JSON for any DataFrame."""
from __future__ import annotations

import io
import json

import pandas as pd
import streamlit as st

MAX_EXCEL_ROWS = 100_000


def _flat(df: pd.DataFrame) -> pd.DataFrame:
    """Make index a column and strip timezones (Excel cannot store tz-aware values)."""
    out = df.reset_index() if (df.index.name or isinstance(df.index, pd.DatetimeIndex)) else df.copy()
    for col in out.columns:
        if isinstance(out[col].dtype, pd.DatetimeTZDtype):
            out[col] = out[col].dt.tz_convert("UTC").dt.tz_localize(None)
    return out


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return _flat(df).to_csv(index=False).encode("utf-8")


def to_json_bytes(df: pd.DataFrame) -> bytes:
    return _flat(df).to_json(orient="records", date_format="iso", indent=2).encode("utf-8")


@st.cache_data(show_spinner=False, max_entries=8)
def to_excel_bytes(df: pd.DataFrame, sheet: str = "data") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        _flat(df).to_excel(xw, index=False, sheet_name=sheet[:31])
    return buf.getvalue()


def download_buttons(df: pd.DataFrame | None, basename: str, key: str) -> None:
    """CSV / Excel / JSON download row. No-ops with a note if there is nothing to export."""
    if df is None or len(df) == 0:
        st.caption("Nothing to export - Data unavailable.")
        return
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    c1.download_button("⬇ CSV", to_csv_bytes(df), f"{basename}.csv", "text/csv", key=f"{key}_csv")
    if len(df) <= MAX_EXCEL_ROWS:
        c2.download_button(
            "⬇ Excel", to_excel_bytes(df, basename), f"{basename}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{key}_xlsx")
    else:
        c2.caption("Excel: too many rows")
    c3.download_button("⬇ JSON", to_json_bytes(df), f"{basename}.json", "application/json", key=f"{key}_json")


def json_bytes(obj) -> bytes:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False).encode("utf-8")
