from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.routes.auth import login_limiter
from graphrec_core.auth.passwords import hash_password
from graphrec_core.database.models import RefreshSession, TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import get_settings

pytestmark = pytest.mark.integration


def register_tenant(client: TestClient) -> tuple[UUID, str]:
    suffix = uuid4().hex[:12]
    email = f"invited-{suffix}@example.org"
    response = client.post(
        "/v1/tenants",
        json={"name": f"Login Tenant {suffix}", "admin_email": email},
        headers={"Idempotency-Key": str(uuid4()), "Accept": "application/json"},
    )
    assert response.status_code == 201
    return UUID(response.json()["id"]), email


def provision_active_user(
    client: TestClient,
    *,
    email: str | None = None,
    password: str = "correct horse battery staple",
    role: str = "tenant_administrator",
    status: str = "active",
) -> tuple[UUID, UUID, str, str]:
    tenant_id, _ = register_tenant(client)
    user_id = uuid4()
    login_email = email or f"active-{uuid4().hex[:12]}@example.org"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=user_id,
                tenant_id=tenant_id,
                email=login_email,
                display_name="Login Test User",
                credential_digest=hash_password(password),
                role=role,
                status=status,
                created_at=datetime.now(timezone.utc),
                last_authenticated_at=None,
            )
        )
    return tenant_id, user_id, login_email, password


def post_login(client: TestClient, email: str, password: str):
    return client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Accept": "application/json"},
    )


def test_valid_login_issues_scoped_tokens_and_hashes_refresh_credential(
    client: TestClient,
) -> None:
    tenant_id, user_id, email, password = provision_active_user(client)
    correlation_id = str(uuid4())
    response = client.post(
        "/v1/auth/login",
        json={"email": email.upper(), "password": password},
        headers={"Accept": "application/json", "X-Correlation-ID": correlation_id},
    )

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == correlation_id
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == get_settings().access_token_ttl_seconds
    assert body["user_role"] == "tenant_administrator"
    assert "keys:write" in body["scopes"]
    assert "tenant_id" not in body

    claims = jwt.decode(
        body["access_token"],
        get_settings().jwt_signing_secret,
        algorithms=["HS256"],
        audience="graphrec-api",
        issuer="graphrec",
    )
    assert claims["sub"] == str(user_id)
    assert claims["tid"] == str(tenant_id)
    assert claims["scopes"] == body["scopes"]

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        stored = session.scalar(select(RefreshSession))
        assert stored is not None
        assert stored.user_id == user_id
        assert stored.token_hash == hashlib.sha256(body["refresh_token"].encode()).hexdigest()
        assert stored.token_hash != body["refresh_token"]
        user = session.scalar(select(TenantUser).where(TenantUser.id == user_id))
        assert user is not None
        assert user.last_authenticated_at is not None


def test_wrong_unknown_inactive_and_ambiguous_accounts_fail_generically(
    client: TestClient,
) -> None:
    _, _, email, password = provision_active_user(client)
    shared_email = f"shared-{uuid4().hex[:12]}@example.org"
    _, _, locked_email, _ = provision_active_user(client, password=password, status="locked")
    provision_active_user(client, email=shared_email, password=password)
    provision_active_user(client, email=shared_email, password=password)

    responses = [
        post_login(client, email, "wrong password"),
        post_login(client, f"unknown-{uuid4().hex}@example.org", password),
        post_login(client, locked_email, password),
        post_login(client, shared_email, password),
    ]
    comparable_bodies = []
    for response in responses:
        assert response.status_code == 401
        error = response.json()["error"]
        comparable_bodies.append(
            {key: error[key] for key in ("code", "message", "retryable")}
        )
        assert email not in response.text
        assert password not in response.text
    assert comparable_bodies == [comparable_bodies[0]] * len(comparable_bodies)


def test_invited_registration_administrator_cannot_sign_in(client: TestClient) -> None:
    _, invited_email = register_tenant(client)

    response = post_login(client, invited_email, "unconfigured password")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


@pytest.mark.parametrize(
    ("body", "expected_field"),
    [
        ({"email": "not-an-email", "password": "password"}, "email"),
        ({"email": "admin@example.org", "password": ""}, "password"),
        (
            {
                "email": "admin@example.org",
                "password": "password",
                "tenant_id": str(uuid4()),
            },
            "tenant_id",
        ),
    ],
)
def test_login_rejects_invalid_and_undocumented_fields(
    client: TestClient, body: dict[str, str], expected_field: str
) -> None:
    response = client.post("/v1/auth/login", json=body, headers={"Accept": "application/json"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert any(
        field["field"] == expected_field
        for field in response.json()["error"]["details"]["fields"]
    )
    if body.get("password"):
        assert body["password"] not in response.text


def test_login_contract_rejects_malformed_and_oversized_payloads(client: TestClient) -> None:
    malformed = client.post(
        "/v1/auth/login",
        content="{not-json",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    oversized = client.post(
        "/v1/auth/login",
        content='{"email":"admin@example.org","password":"' + ("x" * 17_000) + '"}',
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "malformed_request"
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "payload_too_large"


def test_login_rate_limit_returns_retry_guidance(client: TestClient) -> None:
    original_limit = login_limiter.limit
    login_limiter.limit = 2
    email = f"unknown-{uuid4().hex}@example.org"
    try:
        assert post_login(client, email, "password").status_code == 401
        assert post_login(client, email, "password").status_code == 401
        limited = post_login(client, email, "password")
    finally:
        login_limiter.limit = original_limit

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert limited.json()["error"]["retryable"] is True
    assert int(limited.headers["retry-after"]) >= 1


def test_refresh_sessions_are_invisible_across_tenants(client: TestClient) -> None:
    tenant_a, _, email_a, password_a = provision_active_user(client)
    tenant_b, _, email_b, password_b = provision_active_user(client)
    assert post_login(client, email_a, password_a).status_code == 200
    assert post_login(client, email_b, password_b).status_code == 200

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        assert session.scalar(select(func.count()).select_from(RefreshSession)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefreshSession)
                .where(RefreshSession.tenant_id == tenant_b)
            )
            == 0
        )
