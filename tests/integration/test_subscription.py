from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.routes.subscriptions import subscription_limiter
from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.service import ROLE_SCOPES
from graphrec_core.database.models import AuditLog, Tenant, TenantSubscription, TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import get_settings
from graphrec_core.subscription.service import SubscriptionService

pytestmark = pytest.mark.integration


def test_effective_limits_apply_known_overrides_and_ignore_unknown_metadata() -> None:
    effective = SubscriptionService._effective_limits(
        {"accepted_events": 50_000, "stored_products": 5_000},
        {"accepted_events": 50_000, "stored_products": 5_000},
        {"accepted_events": 75_000, "internal_reason": 999},
    )

    assert effective == {"accepted_events": 75_000, "stored_products": 5_000}
    assert "internal_reason" not in effective


def provision_user(
    client: TestClient,
    *,
    role: str = "tenant_administrator",
) -> tuple[UUID, UUID, str, str]:
    suffix = uuid4().hex[:12]
    registration = client.post(
        "/v1/tenants",
        json={
            "name": f"Subscription Tenant {suffix}",
            "admin_email": f"invited-{suffix}@example.org",
        },
        headers={"Idempotency-Key": str(uuid4()), "Accept": "application/json"},
    )
    assert registration.status_code == 201
    tenant_id = UUID(registration.json()["id"])
    user_id = uuid4()
    email = f"subscriber-{suffix}@example.org"
    password = "subscription test password"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                display_name="Subscription Test User",
                credential_digest=hash_password(password),
                role=role,
                status="active",
                created_at=datetime.now(timezone.utc),
                last_authenticated_at=None,
            )
        )
    return tenant_id, user_id, email, password


def login_token(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def get_subscription(client: TestClient, token: str, suffix: str = ""):
    return client.get(
        f"/v1/subscription{suffix}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def custom_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    role: str = "tenant_administrator",
    scopes: list[str] | None = None,
    expires_delta: timedelta = timedelta(minutes=15),
    secret: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "tid": str(tenant_id),
            "role": role,
            "scopes": scopes if scopes is not None else ROLE_SCOPES[role],
            "iat": now - timedelta(minutes=1),
            "exp": now + expires_delta,
            "jti": str(uuid4()),
            "iss": "graphrec",
            "aud": "graphrec-api",
        },
        secret or get_settings().jwt_signing_secret,
        algorithm="HS256",
    )


def test_subscription_returns_exact_tenant_plan_and_access_logs_read(
    client: TestClient,
) -> None:
    tenant_id, user_id, email, password = provision_user(client)
    token = login_token(client, email, password)
    correlation_id = str(uuid4())
    response = client.get(
        "/v1/subscription",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == correlation_id
    body = response.json()
    assert set(body) == {
        "plan_code",
        "status",
        "period_start",
        "period_end",
        "limits",
        "project_defaults",
    }
    assert body["plan_code"] == "free"
    assert body["status"] == "active"
    assert body["project_defaults"] is True
    assert body["limits"]["accepted_events"] == 50_000
    assert body["limits"]["stored_products"] == 5_000
    assert body["limits"]["artifact_storage_bytes"] == 1_073_741_824
    assert "payment" not in response.text.lower()
    assert "overrides" not in response.text.lower()
    assert "tenant_id" not in body

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        access = session.scalar(
            select(AuditLog).where(
                AuditLog.action_type == "subscription_read",
                AuditLog.actor_reference == user_id,
            )
        )
        assert access is not None
        assert access.correlation_reference == UUID(correlation_id)
        assert set(access.redacted_details) == {"plan_code", "project_defaults"}


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Basic credentials", "ApiKey unavailable-key"],
)
def test_subscription_rejects_missing_or_unavailable_credentials(
    client: TestClient, authorization: str | None
) -> None:
    headers = {"Accept": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization

    response = client.get("/v1/subscription", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert "credentials" not in response.text


def test_subscription_distinguishes_expired_token_from_invalid_signature(
    client: TestClient,
) -> None:
    tenant_id, user_id, _, _ = provision_user(client)
    expired = custom_token(
        user_id=user_id,
        tenant_id=tenant_id,
        expires_delta=timedelta(minutes=-2),
    )
    invalid = custom_token(
        user_id=user_id,
        tenant_id=tenant_id,
        secret="different-signing-secret-with-32-characters",
    )

    expired_response = get_subscription(client, expired)
    invalid_response = get_subscription(client, invalid)

    assert expired_response.status_code == 401
    assert expired_response.json()["error"]["code"] == "token_expired"
    assert invalid_response.status_code == 401
    assert invalid_response.json()["error"]["code"] == "authentication_failed"


def test_subscription_requires_billing_scope(client: TestClient) -> None:
    _, _, email, password = provision_user(client, role="tenant_developer")
    token = login_token(client, email, password)

    response = get_subscription(client, token)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_signed_cross_tenant_identity_fails_closed(client: TestClient) -> None:
    tenant_a, user_a, _, _ = provision_user(client)
    tenant_b, _, _, _ = provision_user(client)
    mismatched = custom_token(user_id=user_a, tenant_id=tenant_b)

    response = get_subscription(client, mismatched)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        assert session.scalar(select(func.count()).select_from(Tenant)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(Tenant).where(Tenant.id == tenant_b)
            )
            == 0
        )


def test_subscription_rejects_public_tenant_selector(client: TestClient) -> None:
    _, _, email, password = provision_user(client)
    token = login_token(client, email, password)

    response = get_subscription(client, token, f"?tenant_id={uuid4()}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert response.json()["error"]["details"]["fields"] == [
        {"field": "tenant_id", "message": "Unexpected query parameter"}
    ]


def test_subscription_read_limit_returns_retry_guidance(client: TestClient) -> None:
    _, _, email, password = provision_user(client)
    token = login_token(client, email, password)
    original_limit = subscription_limiter.limit
    subscription_limiter.limit = 2
    try:
        assert get_subscription(client, token).status_code == 200
        assert get_subscription(client, token).status_code == 200
        limited = get_subscription(client, token)
    finally:
        subscription_limiter.limit = original_limit

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert limited.json()["error"]["retryable"] is True
    assert int(limited.headers["retry-after"]) >= 1


def test_subscription_is_current_tenant_record_only(client: TestClient) -> None:
    tenant_a, _, email_a, password_a = provision_user(client)
    tenant_b, _, _, _ = provision_user(client)
    token_a = login_token(client, email_a, password_a)
    response = get_subscription(client, token_a)

    assert response.status_code == 200
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        visible = session.scalars(select(TenantSubscription)).all()
        assert len(visible) == 1
        assert visible[0].tenant_id == tenant_a
        assert session.scalar(
            select(func.count())
            .select_from(TenantSubscription)
            .where(TenantSubscription.tenant_id == tenant_b)
        ) == 0
