"""UC-27 (members), UC-29 (cross-tenant usage), UC-31 (tenant audit)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from graphrec_core.settings import get_settings
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def _member(client, admin, role="tenant_developer"):
    email = f"m-{uuid4().hex[:10]}@example.org"
    invited = client.post("/v1/tenant/users", json={"email": email, "role": role}, headers=admin).json()
    password = f"Member-{uuid4().hex}"
    session = client.post("/v1/auth/setup-password", json={"setup_token": invited["setup_token"], "password": password},
                          headers=JSON).json()
    return invited["id"], email, password, {**JSON, "Authorization": f"Bearer {session['access_token']}"}


def test_uc_27_admin_changes_role_locks_unlocks_and_disables_members(client):
    _, admin = provision(client)
    member, email, password, member_headers = _member(client, admin)
    promoted = client.patch(f"/v1/tenant/users/{member}", json={"role": "tenant_administrator", "reason": "Lead"}, headers=admin)
    assert promoted.status_code == 200 and promoted.json()["role"] == "tenant_administrator"
    # The change ends the member's sessions.
    assert client.get("/v1/products", headers=member_headers).status_code == 401
    assert client.patch(f"/v1/tenant/users/{member}", json={"status": "locked"}, headers=admin).json()["status"] == "locked"
    assert client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON).status_code == 401
    assert client.patch(f"/v1/tenant/users/{member}", json={"status": "active"}, headers=admin).json()["status"] == "active"
    assert client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON).status_code == 200
    assert client.patch(f"/v1/tenant/users/{member}", json={"status": "disabled"}, headers=admin).status_code == 200
    reenable = client.patch(f"/v1/tenant/users/{member}", json={"status": "active"}, headers=admin)
    assert reenable.status_code == 409


def test_uc_27_last_admin_and_self_changes_are_refused(client):
    _, admin = provision(client)
    me = next(u for u in client.get("/v1/tenant/users", headers=admin).json()["items"] if u["role"] == "tenant_administrator")
    assert client.patch(f"/v1/tenant/users/{me['id']}", json={"role": "tenant_developer"}, headers=admin).status_code == 409
    other, _, _, other_headers = _member(client, admin, role="tenant_administrator")
    # other admin tries to demote the original: allowed while two admins remain active
    assert client.patch(f"/v1/tenant/users/{me['id']}", json={"role": "tenant_developer"}, headers=other_headers).status_code == 200
    # 'other' is now the only administrator; its own change is refused (self-change rule,
    # which also keeps the last-administrator invariant, re-checked server-side).
    refused = client.patch(f"/v1/tenant/users/{other}", json={"status": "locked"}, headers=other_headers)
    assert refused.status_code == 409 and "your own" in refused.json()["error"]["message"]


def test_uc_27_resend_invitation_replaces_the_link(client):
    _, admin = provision(client)
    invited = client.post("/v1/tenant/users", json={"email": f"r-{uuid4().hex[:8]}@example.org"}, headers=admin).json()
    resent = client.post(f"/v1/tenant/users/{invited['id']}/invitation:resend", headers=admin)
    assert resent.status_code == 200 and resent.json()["setup_token"] != invited["setup_token"]
    old = client.post("/v1/auth/setup-password", json={"setup_token": invited["setup_token"], "password": "x" * 16}, headers=JSON)
    assert old.status_code == 401
    assert client.post("/v1/auth/setup-password", json={"setup_token": resent.json()["setup_token"], "password": "y" * 16},
                       headers=JSON).status_code == 200


def test_nr_nf_01_members_of_one_tenant_cannot_manage_another(client):
    _, admin_a = provision(client)
    _, admin_b = provision(client)
    member_b, _, _, _ = _member(client, admin_b)
    assert client.patch(f"/v1/tenant/users/{member_b}", json={"status": "locked"}, headers=admin_a).status_code == 404
    assert client.get(f"/v1/tenant/users/{member_b}", headers=admin_a).status_code == 404


def test_uc_31_tenant_audit_is_own_tenant_redacted_and_filterable(client):
    tenant, admin = provision(client)
    _, admin_b = provision(client)
    member, _, _, developer = _member(client, admin)
    client.patch(f"/v1/tenant/users/{member}", json={"role": "tenant_administrator", "reason": "Needs access"}, headers=admin)
    operator = {**JSON, "Authorization": f"Bearer {get_settings().platform_admin_token}"}
    client.post(f"/v1/platform/tenants/{tenant}/quotas", json={"overrides": {"training_jobs": 5}, "reason": "Pilot"}, headers=operator)
    items = client.get("/v1/audit", headers=admin).json()["items"]
    assert any(i["action_type"] == "tenant_user_updated" and i["reason"] == "Needs access" for i in items)
    platform_rows = [i for i in items if i["actor_type"] == "platform_operator"]
    assert platform_rows and all(i["actor_reference"] is None for i in platform_rows)
    filtered = client.get("/v1/audit", params={"action": "tenant_user_updated"}, headers=admin).json()["items"]
    assert filtered and all(i["action_type"] == "tenant_user_updated" for i in filtered)
    # Other tenants see none of it; developers cannot read the audit trail.
    assert all(i["action_type"] != "tenant_user_updated" for i in client.get("/v1/audit", headers=admin_b).json()["items"])
    assert client.get("/v1/audit", headers=developer).status_code in {401, 403}


def test_uc_29_platform_usage_lists_every_tenant_without_payloads(client):
    tenant, headers = provision(client)
    client.put("/v1/products/p1", json={"external_id": "p1", "title": "P1"}, headers=headers)
    operator = {**JSON, "Authorization": f"Bearer {get_settings().platform_admin_token}"}
    body = client.get("/v1/platform/usage", headers=operator).json()
    mine = next(i for i in body["items"] if i["tenant_id"] == tenant)
    products = next(d for d in mine["dimensions"] if d["type"] == "stored_products")
    assert products["used"] == 1 and mine["plan_code"] == "free"
    assert "events" not in str(body).lower().replace("accepted_events", "")
