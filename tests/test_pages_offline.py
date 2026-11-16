"""Smoke test: every page must render without exceptions when ALL sources are unreachable."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["dashboard", "hurricanes", "ocean", "weather", "sea_level", "analysis", "historical", "about"]


@pytest.mark.parametrize("page", PAGES)
def test_page_degrades_gracefully(page, monkeypatch):
    import services.base as base
    monkeypatch.setattr(base, "http_get", lambda *a, **k: (_ for _ in ()).throw(base.SourceError("offline test")))
    at = AppTest.from_file(str(ROOT / "pages" / f"{page}.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
