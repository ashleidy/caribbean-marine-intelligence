"""Local persistence: SQLite observation store (dedupe on write) + Parquet helpers.

Streamlit Community Cloud has an *ephemeral* file system: files survive reruns
but are wiped when the app is rebuilt/rebooted. The store therefore acts as a
warm cache that grows while the app is awake; every source can re-seed it.
All methods degrade gracefully (return empty frames) if the disk is read-only.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd

from services.base import get_logger
from utils.config import STORE_PATH

log = get_logger("cache")
_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


class ObservationStore:
    """Long-format time-series table: (source, location, variable, ts) -> value."""

    def __init__(self, path: Path = STORE_PATH):
        self.path = Path(path)
        self.enabled = True
        try:
            with self._connect() as con:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS obs ("
                    "source TEXT NOT NULL, location TEXT NOT NULL, variable TEXT NOT NULL, "
                    "ts INTEGER NOT NULL, value REAL, "
                    "PRIMARY KEY (source, location, variable, ts)) WITHOUT ROWID"
                )
        except (sqlite3.Error, OSError) as exc:
            log.warning("Observation store disabled: %s", exc)
            self.enabled = False

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30)
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return con

    def upsert_wide(self, df: pd.DataFrame, location: str, source: str) -> int:
        """Insert/replace rows from a wide frame (UTC DatetimeIndex, one column per variable).

        The (source, location, variable, ts) primary key makes this idempotent, i.e.
        duplicates are impossible and re-fetched hours simply overwrite older values.
        """
        if not self.enabled or df is None or df.empty:
            return 0
        wide = df.select_dtypes("number").copy()
        wide.index = pd.DatetimeIndex(wide.index).tz_convert("UTC")
        wide.index.name = "time"
        long = wide.reset_index().melt(id_vars="time", var_name="variable", value_name="value").dropna(subset=["value"])
        if long.empty:
            return 0
        ts = ((long["time"] - _EPOCH) // pd.Timedelta(seconds=1)).astype("int64")
        rows = list(zip([source] * len(long), [location] * len(long),
                        long["variable"].astype(str), ts.tolist(), long["value"].astype(float)))
        try:
            with self._connect() as con:
                con.executemany("INSERT OR REPLACE INTO obs VALUES (?,?,?,?,?)", rows)
            return len(rows)
        except sqlite3.Error as exc:
            log.warning("Store write failed: %s", exc)
            return 0

    def read_wide(self, location: str, source: str, start: pd.Timestamp | None = None,
                  variables: list[str] | None = None) -> pd.DataFrame:
        if not self.enabled:
            return pd.DataFrame()
        sql = "SELECT variable, ts, value FROM obs WHERE source=? AND location=?"
        params: list = [source, location]
        if start is not None:
            sql += " AND ts>=?"
            params.append(int((pd.Timestamp(start).tz_convert("UTC") - _EPOCH).total_seconds()))
        if variables:
            sql += f" AND variable IN ({','.join('?' * len(variables))})"
            params += list(variables)
        try:
            with self._connect() as con:
                long = pd.read_sql_query(sql, con, params=params)
        except (sqlite3.Error, pd.errors.DatabaseError) as exc:
            log.warning("Store read failed: %s", exc)
            return pd.DataFrame()
        if long.empty:
            return pd.DataFrame()
        long["time"] = pd.to_datetime(long["ts"], unit="s", utc=True)
        wide = long.pivot(index="time", columns="variable", values="value").sort_index()
        wide.columns.name = None
        return wide

    def count(self) -> int:
        if not self.enabled:
            return 0
        try:
            with self._connect() as con:
                return int(con.execute("SELECT COUNT(*) FROM obs").fetchone()[0])
        except sqlite3.Error:
            return 0


def is_fresh(path: Path, max_age_s: float) -> bool:
    try:
        return path.exists() and (time.time() - path.stat().st_mtime) < max_age_s
    except OSError:
        return False


def safe_write_parquet(df: pd.DataFrame, path: Path) -> bool:
    try:
        df.to_parquet(path, index=False)
        return True
    except Exception as exc:  # pyarrow missing / read-only fs
        log.warning("Parquet write failed for %s: %s", path.name, exc)
        return False
