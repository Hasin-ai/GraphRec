"""A-27 / ER-NF-09: readiness reports each dependency from a live check."""
from __future__ import annotations

import pytest

from graphrec_core.usage.admission import AdmissionController, get_admission, set_admission

pytestmark = pytest.mark.integration


def test_readyz_reports_every_dependency(client):
    response = client.get("/readyz")
    body = response.json()
    assert set(body["checks"]) == {"database", "redis", "vector_store"}
    assert body["checks"]["database"]["status"] == "ok"
    assert response.status_code == 200 and body["status"] in {"ready", "degraded"}
    assert all(isinstance(c["latency_ms"], float) for c in body["checks"].values())


def test_readyz_is_degraded_not_down_when_redis_is_unreachable(client):
    previous = get_admission()
    set_admission(AdmissionController("redis://127.0.0.1:1/0", timeout_ms=20))
    try:
        body = client.get("/readyz").json()
    finally:
        set_admission(previous)
    assert body["checks"]["redis"]["status"] == "unavailable"
    assert body["status"] == "degraded"
