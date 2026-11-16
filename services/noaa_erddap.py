"""NOAA NCEI ERDDAP client (search, metadata, tabledap & griddap -> DataFrame).

Docs: https://www.ncei.noaa.gov/erddap/rest.html
Pattern used (all plain HTTP GET, CSV responses):
  search   : /erddap/search/index.csv?page=1&itemsPerPage=N&searchFor=<terms>
  metadata : /erddap/info/<datasetID>/index.csv
  tabledap : /erddap/tabledap/<datasetID>.csv?<vars>&<constraints>
  griddap  : /erddap/griddap/<datasetID>.csv?<var>[(t0):stride:(t1)][(lat0):1:(lat1)][(lon0):1:(lon1)]
Dataset IDs are never hard-coded: users discover them through search, so
nothing here can silently go stale.
"""
from __future__ import annotations

import io
from urllib.parse import quote

import pandas as pd

from services.base import DataValidationError, SourceError, get_logger, http_get

log = get_logger("noaa_erddap")

ERDDAP_BASE = "https://www.ncei.noaa.gov/erddap"
MAX_BYTES = 15 * 1024 * 1024     # protect Streamlit Cloud memory
TIMEOUT = (5, 90)

SEARCH_PRESETS = {
    "Sea surface temperature": "sea surface temperature",
    "Ocean currents": "ocean currents",
    "Wave data": "wave height",
    "Salinity": "salinity",
    "Ocean temperature profile": "ocean temperature",
    "Buoy observations": "buoy",
    "Satellite": "satellite sea surface",
}


def search_datasets(query: str, per_page: int = 25, page: int = 1) -> pd.DataFrame:
    """Full-text dataset search. Returns datasetID, title, type, institution, summary, urls."""
    url = f"{ERDDAP_BASE}/search/index.csv"
    resp = http_get(url, {"page": page, "itemsPerPage": per_page, "searchFor": query}, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    df = pd.read_csv(io.StringIO(resp.text))
    if "Dataset ID" not in df.columns:
        raise DataValidationError("ERDDAP search: unexpected columns " + ", ".join(map(str, df.columns[:6])))
    df["type"] = df.apply(lambda r: "griddap" if isinstance(r.get("griddap"), str) and r["griddap"] else
                          ("tabledap" if isinstance(r.get("tabledap"), str) and r["tabledap"] else "other"), axis=1)
    keep = [c for c in ("Dataset ID", "Title", "type", "Institution", "Summary", "Info") if c in df.columns]
    return df[keep].rename(columns={"Dataset ID": "dataset_id", "Title": "title", "Institution": "institution",
                                    "Summary": "summary", "Info": "info_url"})


def dataset_info(dataset_id: str) -> pd.DataFrame:
    """Raw metadata table (Row Type / Variable Name / Attribute Name / Data Type / Value)."""
    resp = http_get(f"{ERDDAP_BASE}/info/{quote(dataset_id)}/index.csv", timeout=TIMEOUT, max_bytes=MAX_BYTES)
    return pd.read_csv(io.StringIO(resp.text))


def dataset_variables(dataset_id: str) -> pd.DataFrame:
    """Variables/dimensions with their data type, units and (if present) actual_range."""
    info = dataset_info(dataset_id)
    vars_ = info[info["Row Type"].isin(["variable", "dimension"])][["Row Type", "Variable Name", "Data Type"]]
    vars_ = vars_.rename(columns={"Row Type": "kind", "Variable Name": "name", "Data Type": "dtype"}).reset_index(drop=True)
    attr = info[info["Row Type"] == "attribute"]
    for key, col in (("units", "units"), ("actual_range", "actual_range"), ("long_name", "long_name")):
        sub = attr[attr["Attribute Name"] == key].set_index("Variable Name")["Value"]
        vars_[col] = vars_["name"].map(sub)
    return vars_


def _read_erddap_csv(text: str) -> pd.DataFrame:
    # ERDDAP CSV: row 1 = names, row 2 = units. Drop the units row, keep them in attrs.
    df = pd.read_csv(io.StringIO(text), skiprows=[1])
    units = {}
    try:
        units = dict(zip(df.columns, pd.read_csv(io.StringIO(text), nrows=1, header=None, skiprows=1).iloc[0].tolist()))
    except Exception:
        pass
    for col in df.columns:
        if col.lower() == "time":
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    df.attrs["units"] = units
    return df


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if col.lower() != "time" and df[col].dtype == object:
            conv = pd.to_numeric(df[col], errors="coerce")
            if conv.notna().sum() >= 0.5 * df[col].notna().sum():
                df[col] = conv
    return df


def fetch_tabledap(dataset_id: str, variables: list[str], start: str, end: str,
                   bbox: tuple[float, float, float, float] | None = None) -> pd.DataFrame:
    """Time-bounded (and optionally lat/lon-bounded) tabledap query -> DataFrame.

    bbox = (lat_min, lat_max, lon_min, lon_max). Variables must exist in the dataset.
    """
    cons = [f"time>={start}", f"time<={end}"]
    if bbox:
        cons += [f"latitude>={bbox[0]}", f"latitude<={bbox[1]}", f"longitude>={bbox[2]}", f"longitude<={bbox[3]}"]
    query = ",".join(variables) + "".join("&" + c for c in cons)
    url = f"{ERDDAP_BASE}/tabledap/{quote(dataset_id)}.csv?{query}"
    resp = http_get(url, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    df = _numeric(_read_erddap_csv(resp.text))
    df = df.drop_duplicates()
    return df


def _lon_for_dataset(lon: float, lon_range: str | None) -> float:
    """Convert -180..180 to 0..360 if the dataset uses that convention (from actual_range)."""
    try:
        hi = float(str(lon_range).split(",")[1])
        if hi > 180 and lon < 0:
            return lon % 360
    except Exception:
        pass
    return lon


def fetch_griddap(dataset_id: str, variable: str, start: str, end: str,
                  bbox: tuple[float, float, float, float], stride: int = 1) -> pd.DataFrame:
    """Small spatial/time subset of a gridded dataset -> long DataFrame (time, lat, lon, value).

    Dimension order is read from the dataset metadata (never assumed); any extra
    dimension (e.g. depth/altitude) is pinned to its first index.
    """
    vars_ = dataset_variables(dataset_id)
    dims = vars_[vars_["kind"] == "dimension"]["name"].tolist()
    if not dims:
        raise DataValidationError(f"{dataset_id} has no dimensions; it is not a griddap dataset")
    lon_range = vars_.set_index("name")["actual_range"].get("longitude")
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    lon_lo, lon_hi = _lon_for_dataset(lon_lo, lon_range), _lon_for_dataset(lon_hi, lon_range)
    if lon_lo > lon_hi:
        lon_lo, lon_hi = lon_hi, lon_lo
    parts = []
    for d in dims:
        dl = d.lower()
        if dl == "time":
            parts.append(f"[({start}):{stride}:({end})]")
        elif dl in ("latitude", "lat"):
            parts.append(f"[({lat_lo}):1:({lat_hi})]")
        elif dl in ("longitude", "lon"):
            parts.append(f"[({lon_lo}):1:({lon_hi})]")
        else:
            parts.append("[0:1:0]")
    url = f"{ERDDAP_BASE}/griddap/{quote(dataset_id)}.csv?{quote(variable)}{''.join(parts)}"
    resp = http_get(url, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    return _numeric(_read_erddap_csv(resp.text))
