"""Storefront tests run against in-process state only.

Settings read ``REDIS_URL`` from the environment; on a machine that also runs the
GraphRec stack (or its CI env), that would point the tests at a real, shared Redis,
and rate-limit counters and shelf lists would leak between tests and runs.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_shared_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("REDIS_URL", "REEL_REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
