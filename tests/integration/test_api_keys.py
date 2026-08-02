from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError

from apps.api.routes.api_keys import api_key_limiter, settings as route_settings
from graphrec_core.api_keys.crypto import api_key_digest
from graphrec_core.auth.passwords import hash_password
from graphrec_core.database.models import ApiKey, AuditLog, TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import get_settings

pytestmark = pytest.mark.integration


def provision_user(
    client: TestClient, *, role: str = "tenant_administrator"
) -> tuple[UUID, UUID, str]:
    suffix = uuid4().hex[:12]
    registration = client.post(
        "/v1/tenants",
        json={
            "name": f"API Key Tenant {suffix}",
            "admin_email": f"invited-{suffix}@example.org",
        },
        headers={"Idempotency-Key": str(uuid4()), "Accept": "application/json"},
    )
    assert registration.status_code == 201
    tenant_id = UUID(registration.json()["id"])
    user_id = uuid4()
    email = f"key-user-{suffix}@example.org"
    password = "api key lifecycle test password"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                display_name="API Key Test User",
                credential_digest=hash_password(password),
                role=role,
                status="active",
                created_at=datetime.now(timezone.utc),
                last_authenticated_at=None,
            )
        )
    login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Accept": "application/json"},
    )
    assert login.status_code == 200
    return tenant_id, user_id, login.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def api_key(secret: str) -> dict[str, str]:
    return {"Authorization": f"ApiKey {secret}", "Accept": "application/json"}


def create_key(
    client: TestClient,
    token: str,
    *,
    name: str = "production-store",
    scopes: list[str] | None = None,
    expires_at: str | None = None,
):
    body: dict[str, object] = {
        "name": name,
        "scopes": scopes or ["catalog:read", "events:write"],
    }
    if expires_at is not None:
        body["expires_at"] = expires_at
    return client.post("/v1/api-keys", json=body, headers=bearer(token))


def test_empty_list_and_redacted_create_list_detail_are_exact(
    client: TestClient,
) -> None:
    tenant_id, user_id, token = provision_user(client)
    assert client.get("/v1/api-keys", headers=bearer(token)).json() == {"items": []}

    correlation_id = str(uuid4())
    created = client.post(
        "/v1/api-keys",
        json={
            "name": " production-store ",
            "scopes": ["catalog:read", "catalog:write", "events:write"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
        headers={**bearer(token), "X-Correlation-ID": correlation_id},
    )
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {
        "id",
        "name",
        "prefix",
        "scopes",
        "status",
        "expires_at",
        "created_at",
        "last_used_at",
        "revoked_at",
        "grace_expires_at",
        "secret",
    }
    assert body["name"] == "production-store"
    assert body["secret"].startswith("gr_live_")
    assert len(body["secret"]) == 51
    assert body["prefix"] == body["secret"][:16]

    listed = client.get("/v1/api-keys", headers=bearer(token))
    detail = client.get(f"/v1/api-keys/{body['id']}", headers=bearer(token))
    assert listed.status_code == detail.status_code == 200
    assert listed.json()["items"] == [detail.json()]
    assert "secret" not in listed.text.lower()
    assert "hash" not in listed.text.lower()
    assert "secret" not in detail.text.lower()
    assert "hash" not in detail.text.lower()

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        row = session.scalar(select(ApiKey).where(ApiKey.id == UUID(body["id"])))
        assert row is not None
        assert row.key_hash == api_key_digest(
            body["secret"], get_settings().api_key_hmac_pepper
        )
        assert body["secret"] not in row.key_hash
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action_type == "api_key_created",
                AuditLog.actor_reference == user_id,
            )
        )
        assert audit is not None
        assert audit.correlation_reference == UUID(correlation_id)
        assert body["secret"] not in str(audit.redacted_details)
        assert "hash" not in str(audit.redacted_details).lower()


def test_scope_delegation_validation_duplicate_and_expiry(
    client: TestClient,
) -> None:
    _, _, developer_token = provision_user(client, role="tenant_developer")
    allowed = create_key(
        client,
        developer_token,
        name="developer-catalog",
        scopes=["catalog:read", "events:write"],
    )
    assert allowed.status_code == 201
    denied = create_key(
        client,
        developer_token,
        name="developer-usage",
        scopes=["usage:read"],
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "insufficient_scope"

    duplicate = create_key(
        client,
        developer_token,
        name="developer-catalog",
        scopes=["catalog:read"],
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_resource"

    duplicate_scopes = create_key(
        client,
        developer_token,
        name="duplicate-scopes",
        scopes=["catalog:read", "catalog:read"],
    )
    unknown_scope = create_key(
        client,
        developer_token,
        name="unknown-scope",
        scopes=["keys:write"],
    )
    expired = create_key(
        client,
        developer_token,
        name="expired",
        scopes=["catalog:read"],
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )
    assert duplicate_scopes.status_code == 422
    assert unknown_scope.status_code == 422
    assert expired.status_code == 422



def test_active_quota_and_administrative_rate_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, token = provision_user(client)
    monkeypatch.setattr(route_settings, "max_active_api_keys_per_tenant", 1)
    assert create_key(client, token, name="first").status_code == 201
    quota = create_key(client, token, name="second")
    assert quota.status_code == 429
    assert quota.json()["error"]["code"] == "quota_exceeded"

    api_key_limiter.clear()
    monkeypatch.setattr(api_key_limiter, "limit", 1)
    assert client.get("/v1/api-keys", headers=bearer(token)).status_code == 200
    limited = client.get("/v1/api-keys", headers=bearer(token))
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(limited.headers["retry-after"]) >= 1


def test_rotation_grace_api_authentication_and_last_use(client: TestClient) -> None:
    tenant_id, _, token = provision_user(client)
    created = create_key(
        client,
        token,
        name="usage-monitor",
        scopes=["usage:read", "billing:read"],
    )
    assert created.status_code == 201
    original = created.json()

    rotated = client.post(
        f"/v1/api-keys/{original['id']}/rotate",
        json={
            "grace_period_seconds": 3600,
            "reason": f"Scheduled rotation {original['secret']}",
        },
        headers=bearer(token),
    )
    assert rotated.status_code == 200
    replacement = rotated.json()
    assert replacement["secret"] != original["secret"]
    assert replacement["prefix"] != original["prefix"]
    assert replacement["grace_expires_at"] is not None

    assert client.get("/v1/usage", headers=api_key(original["secret"])).status_code == 200
    assert client.get("/v1/subscription", headers=api_key(original["secret"])).status_code == 200
    assert client.get("/v1/usage", headers=api_key(replacement["secret"])).status_code == 200
    concurrent = client.post(
        f"/v1/api-keys/{original['id']}/rotate",
        json={"grace_period_seconds": 0, "reason": "Blind retry"},
        headers=bearer(token),
    )
    assert concurrent.status_code == 409
    assert concurrent.json()["error"]["code"] == "state_conflict"

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        row = session.scalar(select(ApiKey).where(ApiKey.id == UUID(original["id"])))
        assert row is not None and row.last_used_at is not None
        rotation_audit = session.scalar(
            select(AuditLog).where(AuditLog.action_type == "api_key_rotated")
        )
        assert rotation_audit is not None
        assert original["secret"] not in str(rotation_audit.redacted_details)
        assert "<redacted>" in str(rotation_audit.redacted_details)
        key_access_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action_type == "subscription_read",
                AuditLog.actor_type == "api_key",
                AuditLog.actor_reference == row.id,
            )
        )
        assert key_access_audit is not None
        row.grace_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    rejected_old = client.get("/v1/usage", headers=api_key(original["secret"]))
    assert rejected_old.status_code == 401
    assert rejected_old.json()["error"]["code"] == "authentication_failed"
    assert client.get("/v1/usage", headers=api_key(replacement["secret"])).status_code == 200


def test_revoke_is_repeat_safe_and_disables_current_and_predecessor(
    client: TestClient,
) -> None:
    _, _, token = provision_user(client)
    original = create_key(
        client, token, name="revoked-monitor", scopes=["usage:read"]
    ).json()
    replacement = client.post(
        f"/v1/api-keys/{original['id']}/rotate",
        json={"grace_period_seconds": 3600, "reason": "Pre-revocation rotation"},
        headers=bearer(token),
    ).json()

    first = client.delete(f"/v1/api-keys/{original['id']}", headers=bearer(token))
    second = client.delete(f"/v1/api-keys/{original['id']}", headers=bearer(token))
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "revoked"
    assert first.json()["revoked_at"] == second.json()["revoked_at"]
    assert client.get("/v1/usage", headers=api_key(original["secret"])).status_code == 401
    assert client.get("/v1/usage", headers=api_key(replacement["secret"])).status_code == 401


def test_api_key_scope_and_bearer_only_management(client: TestClient) -> None:
    _, _, token = provision_user(client)
    key = create_key(
        client, token, name="catalog-only", scopes=["catalog:read"]
    ).json()
    usage = client.get("/v1/usage", headers=api_key(key["secret"]))
    management = client.get("/v1/api-keys", headers=api_key(key["secret"]))
    assert usage.status_code == 403
    assert usage.json()["error"]["code"] == "insufficient_scope"
    assert management.status_code == 401
    assert management.json()["error"]["code"] == "authentication_failed"


def test_foreign_ids_are_hidden_and_rls_blocks_cross_tenant_reads_and_deletes(
    client: TestClient,
) -> None:
    tenant_a, _, token_a = provision_user(client)
    tenant_b, _, token_b = provision_user(client)
    key_id = UUID(create_key(client, token_a, name="tenant-a").json()["id"])

    missing_id = uuid4()
    foreign = client.get(f"/v1/api-keys/{key_id}", headers=bearer(token_b))
    missing = client.get(f"/v1/api-keys/{missing_id}", headers=bearer(token_b))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_b)
        assert session.scalar(select(func.count()).select_from(ApiKey)) == 0

    with pytest.raises(DBAPIError), SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        session.execute(delete(ApiKey).where(ApiKey.id == key_id))


def test_query_selectors_and_invalid_credentials_fail_safely(client: TestClient) -> None:
    _, _, token = provision_user(client)
    for suffix in ("?tenant_id=foreign", "?status=active", "?cursor=next"):
        response = client.get(f"/v1/api-keys{suffix}", headers=bearer(token))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"

    for authorization in (None, "", "ApiKey invalid", "Bearer invalid"):
        headers = {"Accept": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        response = client.get("/v1/api-keys", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_failed"
