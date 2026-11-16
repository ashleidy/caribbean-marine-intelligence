"""Shared HTTP client, logging and result containers for every data service.

* One pooled `requests.Session` with automatic retries (exponential back-off,
  honours Retry-After) on 429/5xx.
* Explicit (connect, read) timeouts on every call.
* Optional hard cap on response size so a bad query can never exhaust the
  1 GB memory of Streamlit Community Cloud.
* Failures are raised as `SourceError`; the UI layer converts them into a
  `FetchResult(ok=False)` so one broken source never takes the app down.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils.config import USER_AGENT

DEFAULT_TIMEOUT = (5, 30)  # (connect, read) seconds
_LOG_READY = False


def get_logger(name: str) -> logging.Logger:
    global _LOG_READY
    if not _LOG_READY:
        logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        _LOG_READY = True
    return logging.getLogger(f"cmi.{name}")


log = get_logger("http")


class SourceError(Exception):
    """A data source could not be reached or returned an error."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class DataValidationError(SourceError):
    """The source answered but the payload does not look like what the docs promise."""


@dataclass
class FetchResult:
    """Uniform wrapper returned to the UI: data + provenance + status."""

    data: Any = None
    ok: bool = False
    source: str = ""
    message: str = ""
    url: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_data(self) -> bool:
        if not self.ok or self.data is None:
            return False
        try:
            return len(self.data) > 0
        except TypeError:
            return True


_SESSION: requests.Session | None = None


def get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        retry = Retry(total=3, connect=3, read=2, backoff_factor=0.8,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET"}), respect_retry_after_header=True,
                      raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, */*"})
        _SESSION = s
    return _SESSION


def _reason(resp: requests.Response) -> str:
    try:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("reason"):
            return str(payload["reason"])
    except ValueError:
        pass
    return (resp.text or "")[:200].strip() or resp.reason or "unknown error"


def http_get(url: str, params: dict | None = None, timeout: tuple[float, float] = DEFAULT_TIMEOUT,
             max_bytes: int | None = None, headers: dict | None = None) -> requests.Response:
    """GET with retries/timeouts. Raises SourceError on any failure."""
    log.info("GET %s %s", url, params or "")
    try:
        resp = get_session().get(url, params=params, timeout=timeout, headers=headers,
                                 stream=max_bytes is not None)
    except requests.RequestException as exc:
        raise SourceError(f"Network error contacting {url}: {exc}") from exc
    if resp.status_code >= 400:
        raise SourceError(f"HTTP {resp.status_code} from {url}: {_reason(resp)}", status=resp.status_code)
    if max_bytes is not None:
        buf = bytearray()
        for chunk in resp.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                resp.close()
                raise SourceError(f"Response exceeds the {max_bytes / 1e6:.0f} MB safety limit; narrow the query.")
        resp._content = bytes(buf)  # type: ignore[attr-defined]
        resp._content_consumed = True  # type: ignore[attr-defined]
    return resp


def http_get_json(url: str, params: dict | None = None, timeout: tuple[float, float] = DEFAULT_TIMEOUT) -> Any:
    resp = http_get(url, params, timeout)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise DataValidationError(f"{url} did not return valid JSON") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise SourceError(f"{url}: {payload.get('reason', 'API error')}")
    return payload
