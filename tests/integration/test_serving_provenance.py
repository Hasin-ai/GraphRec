"""ER-F-05, XR-F-09, BRULE-03 (A-19, A-20, A-21b): honest serving provenance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select

from graphrec_core.database.models import Customer
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration


def _seed(client, headers, events):
    products = [{"external_id": p, "title": p} for p in ("old-hit", "new-hit", "quiet")]
    assert client.post("/v1/products:bulk-upsert", json={"products": products}, headers=headers).status_code == 200
    if events:
        assert client.post("/v1/events/batches", json={"events": events}, headers=headers).status_code == 200


def test_xr_f_09_fallback_uses_recent_popularity(client):
    """ER-F-10."""
    _, headers = provision(client)
    latest = datetime(2026, 9, 30, tzinfo=timezone.utc)
    old = latest - timedelta(days=200)
    events = [{"event_id": f"o{i}", "event_type": "view", "user_id": f"u{i}", "external_product_id": "old-hit",
               "occurred_at": (old + timedelta(minutes=i)).isoformat()} for i in range(10)]
    events += [{"event_id": f"n{i}", "event_type": "view", "user_id": f"v{i}", "external_product_id": "new-hit",
                "occurred_at": (latest - timedelta(minutes=i)).isoformat()} for i in range(3)]
    _seed(client, headers, events)
    body = client.post("/v1/recommendations", json={"user_id": "cold-shopper", "top_n": 3}, headers=headers).json()
    assert body["fallback_used"] and body["strategy"] == "popular_fallback"
    # All-time popularity would rank old-hit (10 views, 200 days ago) first.
    assert body["items"][0]["external_product_id"] == "new-hit"


def test_er_f_05_fallback_reports_no_serving_model_version(client):
    _, headers = provision(client)
    _seed(client, headers, [])
    body = client.post("/v1/recommendations", json={"user_id": "anyone", "top_n": 2}, headers=headers).json()
    assert body["fallback_used"] is True
    assert body["model_version_id"] is None
    assert "active_model_version_id" in body


def test_brule_03_recommendation_requests_do_not_create_customers(client):
    tenant, headers = provision(client)
    _seed(client, headers, [])
    for i in range(5):
        assert client.post("/v1/recommendations", json={"user_id": f"random-{i}", "top_n": 1},
                           headers=headers).status_code == 200
    with SessionLocal() as db:
        set_local_tenant(db, UUID(tenant))
        assert db.scalar(select(func.count()).select_from(Customer)) == 0
