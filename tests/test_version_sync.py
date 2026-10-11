"""A-24: one product version for the API, the web console and the Python SDK."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import app
from graphrec_core.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_file_is_the_single_source():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == version == app.version
    sdk = (ROOT / "sdks/python/src/graphrec_sdk/_version.py").read_text(encoding="utf-8")
    assert re.search(r'__version__ = "([^"]+)"', sdk).group(1) == version
    for name in ("web", "web"):
        package = ROOT / name / "package.json"
        if package.is_file():
            assert json.loads(package.read_text(encoding="utf-8"))["version"] == version


def test_meta_reports_version_and_environment():
    with TestClient(app) as client:
        body = client.get("/v1/meta", headers={"Accept": "application/json"}).json()
    assert body["version"] == __version__
    assert body["environment"] in {"development", "production"}
    assert body["features"]["development_placeholders"] is (body["environment"] == "development")
