"""The single GraphRec product version (A-24).

``VERSION`` at the repository root is the source of truth for the API, the
web console build (``web`` reads it at build time) and the Python SDK; a test
fails if any of them drift.
"""
from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    for candidate in (Path(__file__).resolve().parent.parent / "VERSION", Path("/app/VERSION")):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    try:
        from importlib.metadata import version

        return version("graphrec")
    except Exception:  # noqa: BLE001 - metadata absent in a bare checkout
        return "0.0.0+unknown"


__version__ = _read_version()
