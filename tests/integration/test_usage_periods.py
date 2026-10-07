"""UC-24: usage for a chosen monthly period."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from graphrec_core.database.models import UsageEvent
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration


def _previous_month(now: datetime) -> datetime:
    return datetime(now.year - 1, 12, 15, tzinfo=timezone.utc) if now.month == 1 else datetime(now.year, now.month - 1, 15, tzinfo=timezone.utc)


def _used(body, kind):
    return next(d for d in body["dimensions"] if d["type"] == kind)


def test_uc_24_past_period_sums_only_that_month_and_marks_gauges(client):
    tenant, headers = provision(client)
    past = _previous_month(datetime.now(timezone.utc))
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        db.add(UsageEvent(id=uuid4(), tenant_id=UUID(tenant), usage_type="accepted_events", quantity=Decimal(7),
                          source_id="test", idempotency_key=f"past-{uuid4()}", occurred_at=past))
    client.put("/v1/products/p1", json={"external_id": "p1", "title": "P1"}, headers=headers)
    current = client.get("/v1/usage", headers=headers).json()
    assert current["current_period"] is True and _used(current, "accepted_events")["used"] == 0
    month = f"{past.year:04d}-{past.month:02d}"
    previous = client.get("/v1/usage", params={"period": month}, headers=headers)
    assert previous.status_code == 200, previous.text
    body = previous.json()
    assert body["current_period"] is False and body["period_start"].startswith(month)
    assert _used(body, "accepted_events") == {**_used(body, "accepted_events"), "used": 7, "scope": "period"}
    # Inventory is point-in-time: the product stored now, labelled as such.
    assert _used(body, "stored_products")["used"] == 1 and _used(body, "stored_products")["scope"] == "current"


@pytest.mark.parametrize("period", ["2999-01", "1999-01", "2026-13", "26-01"])
def test_uc_24_future_old_or_malformed_periods_are_refused(client, period):
    _, headers = provision(client)
    response = client.get("/v1/usage", params={"period": period}, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_failed"


def test_uc_24_other_query_parameters_are_still_refused(client):
    _, headers = provision(client)
    assert client.get("/v1/usage", params={"tenant_id": str(uuid4())}, headers=headers).status_code == 422
