"""Plan change requests (migration 0039): GraphRec takes no payments, so a tenant
administrator requests a plan and a platform operator approves or rejects it.
Approval activates the plan in the same transaction."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from graphrec_core.database.models import AuditLog
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from tests.integration.test_operators import bootstrap, make_operator
from tests.integration.test_xr_features import developer, provision

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def plan(client, headers):
    return client.get("/v1/subscription", headers=headers).json()


def request_plan(client, headers, code, message=None):
    return client.post("/v1/subscription/requests", headers=headers,
                       json={"plan_code": code, **({"message": message} if message else {})})


def pending(client, operator, tenant):
    body = client.get("/v1/platform/plan-requests?status=pending", headers=operator).json()
    return [r for r in body["items"] if r["tenant_id"] == tenant]


def test_request_approve_activates_the_plan_and_is_visible_to_both_sides(client):
    tenant, admin = provision(client)
    assert plan(client, admin)["plan_code"] == "free"
    assert client.get("/v1/subscription/requests", headers=admin).json() == {"items": [], "pending": None}

    created = request_plan(client, admin, "basic", "Launching the store next week")
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["status"] == "pending" and req["current_plan_code"] == "free" and req["requested_plan_code"] == "basic"
    assert req["requested_plan_name"] == "Basic" and req["message"] == "Launching the store next week"
    listed = client.get("/v1/subscription/requests", headers=admin).json()
    assert listed["pending"]["id"] == req["id"] and len(listed["items"]) == 1

    # One open request at a time; the current plan cannot be requested.
    again = request_plan(client, admin, "pro")
    assert again.status_code == 409 and again.json()["error"]["code"] == "plan_request_pending"
    assert plan(client, admin)["plan_code"] == "free"   # nothing changes before approval

    monitoring_info, monitoring, _ = make_operator(client, ["monitoring"])
    manager_info, manager, _ = make_operator(client, ["plan_management"])
    queue = client.get("/v1/platform/plan-requests", headers=monitoring)
    assert queue.status_code == 200 and queue.json()["pending_count"] >= 1
    row = next(r for r in queue.json()["items"] if r["id"] == req["id"])
    assert row["tenant_id"] == tenant and row["active_plan_code"] == "free" and row["status"] == "pending"
    # Monitoring may look but not decide.
    refused = client.post(f"/v1/platform/plan-requests/{req['id']}:approve", headers=monitoring,
                          json={"reason": "looks fine"})
    assert refused.status_code == 403

    approved = client.post(f"/v1/platform/plan-requests/{req['id']}:approve", headers=manager,
                           json={"reason": "Approved for launch"})
    assert approved.status_code == 200, approved.text
    decided = approved.json()["request"]
    assert decided["status"] == "approved" and decided["decision_reason"] == "Approved for launch"
    assert decided["decided_by"] == manager_info["id"] and decided["decided_by_email"] == manager_info["email"]
    assert decided["active_plan_code"] == "basic" and approved.json()["warnings"] == []

    # The tenant is on Basic now, with Basic's limits, and sees the decision.
    sub = plan(client, admin)
    plans = {p["code"]: p for p in client.get("/v1/plans").json()["items"]}
    assert sub["plan_code"] == "basic" and sub["limits"] == plans["basic"]["limits"]
    mine = client.get("/v1/subscription/requests", headers=admin).json()
    assert mine["pending"] is None and mine["items"][0]["status"] == "approved"
    assert mine["items"][0]["decision_reason"] == "Approved for launch"
    assert client.get(f"/v1/platform/tenants/{tenant}/quotas", headers=bootstrap()).json()["plan_code"] == "basic"

    # A decided request cannot be decided again.
    twice = client.post(f"/v1/platform/plan-requests/{req['id']}:reject", headers=manager, json={"reason": "not now"})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "plan_request_closed"

    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        actions = set(db.scalars(select(AuditLog.action_type).where(AuditLog.tenant_id == UUID(tenant))))
    assert {"plan_request.created", "plan_request.approved", "tenant.plan_changed"} <= actions

    # Every tier can be requested from any other: Basic -> Pro, then back to Free demo.
    for code in ("pro", "free"):
        nxt = request_plan(client, admin, code).json()
        assert nxt["current_plan_code"] == plan(client, admin)["plan_code"]
        ok = client.post(f"/v1/platform/plan-requests/{nxt['id']}:approve", headers=manager, json={"reason": "approved"})
        assert ok.status_code == 200, ok.text
        assert plan(client, admin)["plan_code"] == code
    same = request_plan(client, admin, "free")
    assert same.status_code == 409 and same.json()["error"]["code"] == "plan_already_active"


def test_reject_keeps_the_plan_and_tells_the_tenant_why(client):
    tenant, admin = provision(client)
    req = request_plan(client, admin, "pro").json()
    rejected = client.post(f"/v1/platform/plan-requests/{req['id']}:reject", headers=bootstrap(),
                           json={"reason": "Please start with Basic"})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["request"]["status"] == "rejected"
    assert plan(client, admin)["plan_code"] == "free"
    mine = client.get("/v1/subscription/requests", headers=admin).json()
    assert mine["pending"] is None and mine["items"][0]["decision_reason"] == "Please start with Basic"
    # A new request can follow a rejection.
    assert request_plan(client, admin, "basic").status_code == 201


def test_tenant_can_cancel_its_pending_request(client):
    tenant, admin = provision(client)
    req = request_plan(client, admin, "basic").json()
    cancelled = client.post(f"/v1/subscription/requests/{req['id']}:cancel", headers=admin)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = client.post(f"/v1/subscription/requests/{req['id']}:cancel", headers=admin)
    assert again.status_code == 409 and again.json()["error"]["code"] == "plan_request_closed"
    late = client.post(f"/v1/platform/plan-requests/{req['id']}:approve", headers=bootstrap(), json={"reason": "late"})
    assert late.status_code == 409 and plan(client, admin)["plan_code"] == "free"
    assert pending(client, bootstrap(), tenant) == []
    assert request_plan(client, admin, "pro").status_code == 201


def test_only_administrators_request_and_tenants_are_isolated(client):
    tenant, admin = provision(client)
    other_tenant, other = provision(client)
    dev = developer(client, tenant)
    assert request_plan(client, dev, "basic").status_code == 403
    key = client.post("/v1/api-keys", headers=admin,
                      json={"name": f"k-{uuid4().hex[:6]}", "scopes": ["billing:read", "catalog:read"]})
    assert key.status_code in (200, 201), key.text
    api_key = {**JSON, "Authorization": f"ApiKey {key.json()['secret']}"}
    assert request_plan(client, api_key, "basic").status_code == 403       # billing:write is console-only
    assert client.get("/v1/subscription/requests", headers=api_key).status_code == 200

    req = request_plan(client, admin, "basic").json()
    assert client.get("/v1/subscription/requests", headers=other).json()["items"] == []
    assert client.post(f"/v1/subscription/requests/{req['id']}:cancel", headers=other).status_code == 404
    assert request_plan(client, admin, "enterprise").status_code == 422
    assert pending(client, bootstrap(), other_tenant) == []


def test_approval_below_usage_needs_acknowledgement_and_rolls_back_otherwise(client, monkeypatch):
    tenant, admin = provision(client)
    req = request_plan(client, admin, "basic").json()
    conflict = [{"limit_name": "stored_products", "limit": 1, "used": 5, "over_by": 4}]
    monkeypatch.setattr("apps.api.routes.platform.limits_below_inventory", lambda db, tenant_id, limits: conflict)
    refused = client.post(f"/v1/platform/plan-requests/{req['id']}:approve", headers=bootstrap(), json={"reason": "go ahead"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "limit_below_usage"
    # Rolled back: still pending, plan unchanged.
    assert plan(client, admin)["plan_code"] == "free" and len(pending(client, bootstrap(), tenant)) == 1
    forced = client.post(f"/v1/platform/plan-requests/{req['id']}:approve", headers=bootstrap(),
                         json={"reason": "go ahead", "acknowledge_below_usage": True})
    assert forced.status_code == 200 and forced.json()["warnings"] == conflict
    assert plan(client, admin)["plan_code"] == "basic"


def test_platform_list_validates_status(client):
    assert client.get("/v1/platform/plan-requests?status=weird", headers=bootstrap()).status_code == 422
    assert client.get("/v1/platform/plan-requests").status_code == 401


def test_direct_assignment_of_the_requested_plan_closes_the_request(client):
    tenant, admin = provision(client)
    req = request_plan(client, admin, "pro").json()
    plans = {p["code"]: p["id"] for p in client.get("/v1/platform/plans", headers=bootstrap()).json()}
    assigned = client.post(f"/v1/platform/tenants/{tenant}/plan", headers=bootstrap(),
                           json={"plan_id": plans["pro"], "reason": "Moved during onboarding call"})
    assert assigned.status_code == 200, assigned.text
    mine = client.get("/v1/subscription/requests", headers=admin).json()
    assert mine["pending"] is None and mine["items"][0]["id"] == req["id"]
    assert mine["items"][0]["status"] == "approved" and plan(client, admin)["plan_code"] == "pro"
    # Assigning a different plan leaves an open request alone.
    req2 = request_plan(client, admin, "basic").json()
    client.post(f"/v1/platform/tenants/{tenant}/plan", headers=bootstrap(), json={"plan_id": plans["free"]})
    assert client.get("/v1/subscription/requests", headers=admin).json()["pending"]["id"] == req2["id"]
    assert pending(client, bootstrap(), tenant)[0]["active_plan_code"] == "free"
