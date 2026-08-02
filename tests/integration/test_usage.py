from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.routes.usage import usage_limiter
from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.service import ROLE_SCOPES
from graphrec_core.database.models import AuditLog, TenantUser, UsageEvent
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import get_settings

pytestmark = pytest.mark.integration

USAGE_TYPES = {
    "accepted_events",
    "recommendation_requests",
    "training_jobs",
    "training_cpu_seconds",
    "stored_products",
    "artifact_storage_bytes",
    "active_model_versions",
    "inference_replicas",
    "replica_runtime_minutes",
}


def provision_user(
    client: TestClient,
    *,
    role: str = "tenant_administrator",
) -> tuple[UUID, UUID, str, str]:
    suffix = uuid4().hex[:12]
    registration = client.post(
        "/v1/tenants",
        json={
            "name": f"Usage Tenant {suffix}",
            "admin_email": f"invited-{suffix}@example.org",
        },
        headers={"Idempotency-Key": str(uuid4()), "Accept": "application/json"},
    )
    assert registration.status_code == 201
    tenant_id = UUID(registration.json()["id"])
    user_id = uuid4()
    email = f"usage-{suffix}@example.org"
    password = "usage test password"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                display_name="Usage Test User",
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


def get_usage(client: TestClient, token: str, suffix: str = ""):
    return client.get(
        f"/v1/usage{suffix}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def add_usage(
    tenant_id: UUID,
    usage_type: str,
    quantity: Decimal,
    *,
    idempotency_key: str | None = None,
    occurred_at: datetime | None = None,
) -> UUID:
    event_id = uuid4()
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            UsageEvent(
                id=event_id,
                tenant_id=tenant_id,
                usage_type=usage_type,
                quantity=quantity,
                source_id=f"source:{event_id}",
                idempotency_key=idempotency_key or f"usage:{event_id}",
                occurred_at=occurred_at or datetime.now(timezone.utc),
            )
        )
    return event_id


def signed_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    expires_at: datetime,
    secret: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "tid": str(tenant_id),
            "role": "tenant_administrator",
            "scopes": ROLE_SCOPES["tenant_administrator"],
            "iat": now - timedelta(minutes=1),
            "exp": expires_at,
            "jti": str(uuid4()),
            "iss": "graphrec",
            "aud": "graphrec-api",
        },
        secret or get_settings().jwt_signing_secret,
        algorithm="HS256",
    )


def dimensions_by_type(body: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["type"]: item for item in body["dimensions"]}  # type: ignore[index,union-attr]


def test_zero_usage_returns_all_dimensions_calendar_period_and_access_log(
    client: TestClient,
) -> None:
    tenant_id, user_id, email, password = provision_user(client)
    token = login_token(client, email, password)
    correlation_id = str(uuid4())
    before = datetime.now(timezone.utc)
    response = client.get(
        "/v1/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        },
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == correlation_id
    body = response.json()
    assert set(body) == {
        "period_start",
        "period_end",
        "reset_at",
        "dimensions",
        "last_reconciled_at",
        "project_defaults",
    }
    dimensions = dimensions_by_type(body)
    assert set(dimensions) == USAGE_TYPES
    assert all(item["used"] == 0 for item in dimensions.values())
    assert dimensions["accepted_events"]["limit"] == 50_000
    assert dimensions["accepted_events"]["remaining"] == 50_000
    assert dimensions["training_cpu_seconds"]["limit"] is None
    assert dimensions["training_cpu_seconds"]["remaining"] is None
    period_start = datetime.fromisoformat(body["period_start"])
    period_end = datetime.fromisoformat(body["period_end"])
    reconciled_at = datetime.fromisoformat(body["last_reconciled_at"])
    assert period_start == datetime(before.year, before.month, 1, tzinfo=timezone.utc)
    assert period_end.day == 1 and period_end > period_start
    assert body["reset_at"] == body["period_end"]
    assert before <= reconciled_at <= after
    assert body["project_defaults"] is True
    assert not any(
        word in response.text.lower()
        for word in ("source_id", "idempotency_key", "customer_id", "product_id", "payment")
    )

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        access = session.scalar(
            select(AuditLog).where(
                AuditLog.action_type == "usage_read",
                AuditLog.actor_reference == user_id,
            )
        )
        assert access is not None
        assert access.correlation_reference == UUID(correlation_id)
        assert access.redacted_details["dimension_count"] == 9
        assert set(access.redacted_details) == {"period_start", "dimension_count"}


def test_durable_ledger_reconciles_used_remaining_and_informational_values(
    client: TestClient,
) -> None:
    tenant_id, _, email, password = provision_user(client)
    add_usage(tenant_id, "accepted_events", Decimal("100"))
    add_usage(tenant_id, "accepted_events", Decimal("25"))
    add_usage(tenant_id, "training_cpu_seconds", Decimal("12.5"))
    add_usage(tenant_id, "stored_products", Decimal("6000"))
    token = login_token(client, email, password)

    response = get_usage(client, token)

    assert response.status_code == 200
    dimensions = dimensions_by_type(response.json())
    assert dimensions["accepted_events"] == {
        "type": "accepted_events",
        "used": 125,
        "limit": 50_000,
        "remaining": 49_875,
        "unit": "count",
    }
    assert dimensions["training_cpu_seconds"]["used"] == 12.5
    assert dimensions["training_cpu_seconds"]["limit"] is None
    assert dimensions["training_cpu_seconds"]["remaining"] is None
    assert dimensions["stored_products"]["used"] == 6_000
    assert dimensions["stored_products"]["limit"] == 5_000
    assert dimensions["stored_products"]["remaining"] == 0


def test_ledger_idempotency_is_tenant_local(client: TestClient) -> None:
    tenant_a, _, _, _ = provision_user(client)
    tenant_b, _, _, _ = provision_user(client)
    shared_key = f"shared:{uuid4()}"
    add_usage(tenant_a, "accepted_events", Decimal(1), idempotency_key=shared_key)
    add_usage(tenant_b, "accepted_events", Decimal(1), idempotency_key=shared_key)

    with pytest.raises(IntegrityError):
        add_usage(tenant_a, "accepted_events", Decimal(1), idempotency_key=shared_key)


def test_runtime_cannot_mutate_immutable_ledger(client: TestClient) -> None:
    tenant_id, _, _, _ = provision_user(client)
    event_id = add_usage(tenant_id, "accepted_events", Decimal(1))

    with pytest.raises(DBAPIError), SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.execute(
            update(UsageEvent).where(UsageEvent.id == event_id).values(quantity=Decimal(2))
        )

    with pytest.raises(DBAPIError), SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.execute(delete(UsageEvent).where(UsageEvent.id == event_id))


def test_usage_events_and_summary_are_tenant_isolated(client: TestClient) -> None:
    tenant_a, _, email_a, password_a = provision_user(client)
    tenant_b, _, _, _ = provision_user(client)
    add_usage(tenant_a, "accepted_events", Decimal(3))
    add_usage(tenant_b, "accepted_events", Decimal(99))
    token_a = login_token(client, email_a, password_a)

    response = get_usage(client, token_a)

    assert response.status_code == 200
    assert dimensions_by_type(response.json())["accepted_events"]["used"] == 3
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 1
        assert session.scalar(
            select(func.count()).select_from(UsageEvent).where(UsageEvent.tenant_id == tenant_b)
        ) == 0


def test_usage_requires_valid_credential_and_scope(client: TestClient) -> None:
    tenant_id, user_id, _, _ = provision_user(client)
    _, _, developer_email, developer_password = provision_user(
        client, role="tenant_developer"
    )
    developer_token = login_token(client, developer_email, developer_password)
    expired = signed_token(
        user_id=user_id,
        tenant_id=tenant_id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    forged = signed_token(
        user_id=user_id,
        tenant_id=tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        secret="different-usage-signing-secret-32-chars",
    )

    missing = client.get("/v1/usage", headers={"Accept": "application/json"})
    expired_response = get_usage(client, expired)
    forged_response = get_usage(client, forged)
    denied = get_usage(client, developer_token)

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authentication_failed"
    assert expired_response.status_code == 401
    assert expired_response.json()["error"]["code"] == "token_expired"
    assert forged_response.status_code == 401
    assert forged_response.json()["error"]["code"] == "authentication_failed"
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "insufficient_scope"


def test_usage_rejects_public_period_or_tenant_selectors(client: TestClient) -> None:
    _, _, email, password = provision_user(client)
    token = login_token(client, email, password)

    response = get_usage(client, token, f"?tenant_id={uuid4()}&period=previous")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert response.json()["error"]["details"]["fields"] == [
        {"field": "period", "message": "Unexpected query parameter"},
        {"field": "tenant_id", "message": "Unexpected query parameter"},
    ]


def test_usage_read_limit_returns_retry_guidance(client: TestClient) -> None:
    _, _, email, password = provision_user(client)
    token = login_token(client, email, password)
    original_limit = usage_limiter.limit
    usage_limiter.limit = 2
    try:
        assert get_usage(client, token).status_code == 200
        assert get_usage(client, token).status_code == 200
        limited = get_usage(client, token)
    finally:
        usage_limiter.limit = original_limit

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert limited.json()["error"]["retryable"] is True
    assert int(limited.headers["retry-after"]) >= 1
