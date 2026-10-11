"""D-13 / UC-27: members of a suspended tenant get a status-only session."""
from __future__ import annotations

from uuid import uuid4

import pytest

from graphrec_core.settings import get_settings

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def _tenant(client):
    tag = uuid4().hex
    email, password = f"{tag}@example.org", f"Gate-{tag}!"
    created = client.post("/v1/tenants", json={"name": f"Gate {tag}", "admin_email": email},
                          headers={**JSON, "Idempotency-Key": tag}).json()
    client.post("/v1/auth/setup-password", json={"setup_token": created["setup_token"], "password": password}, headers=JSON)
    return created["id"], email, password


def _status(client, tenant, status):
    operator = {**JSON, "Authorization": f"Bearer {get_settings().platform_admin_token}"}
    assert client.post(f"/v1/platform/tenants/{tenant}/status", json={"status": status, "reason": "Gate test"},
                       headers=operator).status_code == 200


def test_uc_27_suspended_member_signs_in_to_a_status_only_session(client):
    tenant, email, password = _tenant(client)
    active = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON).json()
    _status(client, tenant, "suspended")
    # Full sessions issued before the suspension stop working.
    assert client.get("/v1/products", headers={**JSON, "Authorization": f"Bearer {active['access_token']}"}).status_code == 401

    session = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON)
    assert session.status_code == 200
    assert session.json()["scopes"] == ["account:status"]
    headers = {**JSON, "Authorization": f"Bearer {session.json()['access_token']}"}
    status = client.get("/v1/tenant/status", headers=headers).json()
    assert status["status"] == "suspended" and status["restricted_session"] is True
    for path in ("/v1/products", "/v1/usage", "/v1/api-keys", "/v1/model-versions"):
        denied = client.get(path, headers=headers)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "tenant_inactive", path
    assert client.post("/v1/auth/refresh", json={"refresh_token": session.json()["refresh_token"]}, headers=JSON).status_code == 401
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204


def test_uc_27_wrong_password_and_reactivation(client):
    tenant, email, password = _tenant(client)
    _status(client, tenant, "suspended")
    assert client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"}, headers=JSON).status_code == 401
    restricted = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON).json()
    _status(client, tenant, "active")
    # A restricted token never becomes a full session, even after reactivation.
    assert client.get("/v1/tenant/status", headers={**JSON, "Authorization": f"Bearer {restricted['access_token']}"}).status_code == 401
    full = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON).json()
    assert "account:status" not in full["scopes"]
    body = client.get("/v1/tenant/status", headers={**JSON, "Authorization": f"Bearer {full['access_token']}"}).json()
    assert body["status"] == "active" and body["restricted_session"] is False


def test_uc_27_deleted_tenants_cannot_sign_in(client):
    tenant, email, password = _tenant(client)
    _status(client, tenant, "deleted")
    assert client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON).status_code == 401
