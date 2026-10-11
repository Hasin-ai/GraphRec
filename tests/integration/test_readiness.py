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


def test_public_plans_reflect_operator_edits(client):
    """A-25: the public site reads live plan limits, not a hand-copied table."""
    from graphrec_core.settings import get_settings

    plans = client.get("/v1/plans", headers={"Accept": "application/json"}).json()["items"]
    assert {p["code"] for p in plans} >= {"free", "basic", "pro"}
    operator = {"Accept": "application/json", "Authorization": f"Bearer {get_settings().platform_admin_token}"}
    basic = next(p for p in client.get("/v1/platform/plans", headers=operator).json() if p["code"] == "basic")
    edited = {**basic["limits"], "stored_products": basic["limits"]["stored_products"] + 1}
    assert client.put(f"/v1/platform/plans/{basic['id']}", headers=operator, json={
        "name": basic["name"], "limits": edited, "is_active": True, "acknowledge_below_usage": True}).status_code == 200
    try:
        live = next(p for p in client.get("/v1/plans").json()["items"] if p["code"] == "basic")
        assert live["limits"]["stored_products"] == edited["stored_products"]
    finally:
        client.put(f"/v1/platform/plans/{basic['id']}", headers=operator, json={
            "name": basic["name"], "limits": basic["limits"], "is_active": True, "acknowledge_below_usage": True})
