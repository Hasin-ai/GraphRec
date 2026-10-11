"""D-04 / UC-27–31 / ER-F-11: named operators, roles, and attributed audits."""
from __future__ import annotations

from uuid import uuid4

import pytest

from graphrec_core.settings import get_settings
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def bootstrap():
    return {**JSON, "Authorization": f"Bearer {get_settings().platform_admin_token}"}


def make_operator(client, roles):
    email, password = f"op-{uuid4().hex[:10]}@example.org", f"Operator-{uuid4().hex}"
    created = client.post("/v1/platform/operators", headers=bootstrap(),
                          json={"email": email, "display_name": "Test Operator", "password": password, "roles": roles})
    assert created.status_code == 201, created.text
    session = client.post("/v1/platform/auth/login", headers=JSON, json={"email": email, "password": password})
    assert session.status_code == 200, session.text
    return created.json(), {**JSON, "Authorization": f"Bearer {session.json()['access_token']}"}, password


def test_uc_27_operator_actions_are_attributed_to_the_operator(client):
    operator, headers, _ = make_operator(client, ["platform", "audit"])
    tenant, _ = provision(client)
    changed = client.post(f"/v1/platform/tenants/{tenant}/status", headers=headers,
                          json={"status": "suspended", "reason": "Attribution test"})
    assert changed.status_code == 200, changed.text
    audit = client.get("/v1/platform/audit", params={"tenant_id": tenant, "action": "tenant.status_changed"},
                       headers=headers).json()["items"]
    assert audit[0]["actor_reference"] == operator["id"]
    assert audit[0]["reason"] == "Attribution test"


def test_d_04_roles_limit_what_an_operator_can_do(client):
    _, monitoring, _ = make_operator(client, ["monitoring"])
    tenant, _ = provision(client)
    assert client.get("/v1/platform/status", headers=monitoring).status_code == 200
    assert client.get(f"/v1/platform/tenants/{tenant}/usage", headers=monitoring).status_code == 200
    denied = client.post(f"/v1/platform/tenants/{tenant}/status", headers=monitoring,
                         json={"status": "suspended", "reason": "Not allowed"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "insufficient_scope"
    assert client.get("/v1/platform/audit", headers=monitoring).status_code == 403
    assert client.get("/v1/platform/operators", headers=monitoring).status_code == 403
    me = client.get("/v1/platform/me", headers=monitoring).json()
    assert me["roles"] == ["monitoring"] and me["kind"] == "operator"


def test_d_04_disabling_or_changing_roles_ends_sessions_and_wrong_passwords_fail(client):
    operator, headers, password = make_operator(client, ["platform"])
    assert client.post("/v1/platform/auth/login", headers=JSON,
                       json={"email": operator["email"], "password": "wrong-password"}).status_code == 401
    assert client.patch(f"/v1/platform/operators/{operator['id']}", headers=bootstrap(),
                        json={"roles": ["monitoring"]}).status_code == 200
    assert client.get("/v1/platform/tenants", headers=headers).status_code == 401
    assert client.patch(f"/v1/platform/operators/{operator['id']}", headers=bootstrap(),
                        json={"status": "disabled"}).status_code == 200
    assert client.post("/v1/platform/auth/login", headers=JSON,
                       json={"email": operator["email"], "password": password}).status_code == 401


def test_d_04_tenant_credentials_and_tampered_tokens_never_open_the_platform(client):
    _, tenant_headers = provision(client)
    assert client.get("/v1/platform/tenants", headers=tenant_headers).status_code == 401
    assert client.get("/v1/platform/tenants", headers={**JSON, "Authorization": "Bearer a.b.c"}).status_code == 401


def test_d_04_in_production_the_bootstrap_token_only_creates_the_first_operator(client, monkeypatch):
    from graphrec_core.auth import platform as platform_auth

    monkeypatch.setattr(get_settings(), "graphrec_env", "production")
    assert client.get("/v1/platform/tenants", headers=bootstrap()).status_code == 401
    monkeypatch.setattr(platform_auth, "active_operator_exists", lambda db: False)
    created = client.post("/v1/platform/operators", headers=bootstrap(), json={
        "email": f"first-{uuid4().hex[:8]}@example.org", "display_name": "First", "password": "x" * 16, "roles": ["operator_admin"]})
    assert created.status_code == 201
    monkeypatch.setattr(platform_auth, "active_operator_exists", lambda db: True)
    again = client.post("/v1/platform/operators", headers=bootstrap(), json={
        "email": f"second-{uuid4().hex[:8]}@example.org", "display_name": "Second", "password": "x" * 16, "roles": ["audit"]})
    assert again.status_code == 401


def test_every_platform_route_declares_its_roles():
    from apps.api.main import app
    from graphrec_core.auth.platform import ROUTE_ROLES

    routes = {(m, r.path) for r in app.routes if getattr(r, "path", "").startswith("/v1/platform")
              and not r.path.startswith("/v1/platform/auth") for m in r.methods - {"HEAD", "OPTIONS"}}
    assert routes <= set(ROUTE_ROLES), sorted(routes - set(ROUTE_ROLES))
