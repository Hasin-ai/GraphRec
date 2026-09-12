from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from apps.api.routes.tenants import registration_limiter
from graphrec_core.auth.setup_tokens import setup_token_hash
from graphrec_core.database.models import (
    AccountSetupToken,
    AuditLog,
    RegistrationRequest,
    TenantResourceQuota,
    TenantSubscription,
    TenantUser,
)
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant

pytestmark = pytest.mark.integration


def unique_registration() -> tuple[dict[str, str], str]:
    suffix = uuid4().hex[:12]
    return (
        {"name": f"Tenant {suffix}", "admin_email": f"admin-{suffix}@example.org"},
        str(uuid4()),
    )


def post_registration(client: TestClient, body: dict[str, str], key: str):
    return client.post(
        "/v1/tenants",
        json=body,
        headers={"Idempotency-Key": key, "Accept": "application/json"},
    )


def test_valid_registration_creates_required_records_atomically(client: TestClient) -> None:
    body, key = unique_registration()
    correlation_id = str(uuid4())
    response = client.post(
        "/v1/tenants",
        json=body,
        headers={
            "Idempotency-Key": key,
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        },
    )

    assert response.status_code == 201
    assert response.headers["x-correlation-id"] == correlation_id
    result = response.json()
    assert result == {
        "id": result["id"],
        "name": body["name"],
        "status": "active",
        "created_at": result["created_at"],
        "administrator_email": body["admin_email"],
        "next_step": "Complete account setup with the one-time setup_token before it expires",
        "setup_token": result["setup_token"],
        "setup_token_expires_at": result["setup_token_expires_at"],
    }
    assert isinstance(result["setup_token"], str) and len(result["setup_token"]) >= 40
    assert result["setup_token_expires_at"] > result["created_at"]
    assert "password" not in response.text.lower()
    tenant_id = UUID(result["id"])

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        user = session.scalar(select(TenantUser))
        assert user is not None
        assert user.email == body["admin_email"]
        assert user.role == "tenant_administrator"
        assert user.status == "invited"
        assert user.credential_digest is None
        assert session.scalar(select(func.count()).select_from(TenantSubscription)) == 1
        assert session.scalar(select(func.count()).select_from(TenantResourceQuota)) == 1
        audit = session.scalar(select(AuditLog))
        assert audit is not None
        assert audit.outcome == "succeeded"
        assert body["admin_email"] not in str(audit.redacted_details)
        # Only the hash of the setup token is persisted, never the token itself.
        setup_token = session.scalar(select(AccountSetupToken))
        assert setup_token is not None
        assert setup_token.user_id == user.id
        assert setup_token.token_hash == setup_token_hash(result["setup_token"])
        assert setup_token.used_at is None and setup_token.revoked_at is None
        stored = session.scalar(
            select(RegistrationRequest.response_body).where(RegistrationRequest.tenant_id == tenant_id)
        )
        assert stored is not None
        assert result["setup_token"] not in str(stored)


def test_same_idempotency_key_and_body_replays_without_duplicate_effect(client: TestClient) -> None:
    body, key = unique_registration()
    first = post_registration(client, body, key)
    replay = post_registration(client, body, key)

    assert first.status_code == 201
    assert replay.status_code == 200
    # A replay never re-discloses the one-time setup token.
    assert replay.json() == {
        **first.json(),
        "setup_token": None,
        "setup_token_expires_at": None,
    }
    tenant_id = UUID(first.json()["id"])
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        assert session.scalar(select(func.count()).select_from(TenantUser)) == 1
        assert session.scalar(select(func.count()).select_from(TenantSubscription)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1
        assert session.scalar(select(func.count()).select_from(AccountSetupToken)) == 1


def test_idempotency_key_reuse_with_different_body_conflicts(client: TestClient) -> None:
    first_body, key = unique_registration()
    second_body, _ = unique_registration()
    assert post_registration(client, first_body, key).status_code == 201

    response = post_registration(client, second_body, key)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert first_body["admin_email"] not in response.text


def test_same_registration_with_a_new_key_is_a_safe_duplicate(client: TestClient) -> None:
    body, key = unique_registration()
    assert post_registration(client, body, key).status_code == 201

    response = post_registration(client, body, str(uuid4()))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_resource"
    assert body["admin_email"] not in response.text


@pytest.mark.parametrize(
    ("body", "expected_field"),
    [
        ({"name": "", "admin_email": "admin@example.org"}, "name"),
        ({"name": "Valid", "admin_email": "not-an-email"}, "admin_email"),
        (
            {"name": "Valid", "admin_email": "admin@example.org", "tenant_id": str(uuid4())},
            "tenant_id",
        ),
        (
            {"name": "Valid", "admin_email": "admin@example.org", "password": "not-accepted"},
            "password",
        ),
    ],
)
def test_validation_rejects_invalid_or_undocumented_fields(
    client: TestClient, body: dict[str, str], expected_field: str
) -> None:
    response = post_registration(client, body, str(uuid4()))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert any(
        field["field"] == expected_field
        for field in response.json()["error"]["details"]["fields"]
    )


def test_missing_idempotency_key_uses_error_contract(client: TestClient) -> None:
    body, _ = unique_registration()
    response = client.post("/v1/tenants", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert response.headers["x-correlation-id"] == response.json()["error"]["correlation_id"]


def test_malformed_json_and_content_type_use_safe_contract_errors(client: TestClient) -> None:
    malformed = client.post(
        "/v1/tenants",
        content="{not-json",
        headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid4())},
    )
    wrong_type = client.post(
        "/v1/tenants",
        content="name=x",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Idempotency-Key": str(uuid4())},
    )

    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "malformed_request"
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"]["code"] == "malformed_request"


def test_oversized_body_is_rejected_before_parsing(client: TestClient) -> None:
    response = client.post(
        "/v1/tenants",
        content='{"name":"' + ("x" * 17_000) + '","admin_email":"admin@example.org"}',
        headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid4())},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_rate_limit_returns_retry_guidance(client: TestClient) -> None:
    original_limit = registration_limiter.limit
    registration_limiter.limit = 2
    try:
        for _ in range(2):
            body, key = unique_registration()
            assert post_registration(client, body, key).status_code == 201
        body, key = unique_registration()
        limited = post_registration(client, body, key)
    finally:
        registration_limiter.limit = original_limit

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert limited.json()["error"]["retryable"] is True
    assert int(limited.headers["retry-after"]) >= 1


def test_forced_rls_blocks_cross_tenant_reads_and_writes(client: TestClient) -> None:
    body_a, key_a = unique_registration()
    body_b, key_b = unique_registration()
    tenant_a = UUID(post_registration(client, body_a, key_a).json()["id"])
    tenant_b = UUID(post_registration(client, body_b, key_b).json()["id"])

    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        visible_b = session.scalar(
            select(func.count()).select_from(TenantUser).where(TenantUser.tenant_id == tenant_b)
        )
        visible_a = session.scalar(
            select(func.count()).select_from(TenantUser).where(TenantUser.tenant_id == tenant_a)
        )
        assert visible_b == 0
        assert visible_a == 1

    with pytest.raises(DBAPIError), SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        session.execute(
            text(
                """
                INSERT INTO tenant_users
                  (id, tenant_id, email, display_name, credential_digest, role, status, created_at)
                VALUES
                  (:id, :tenant_id, :email, 'forged', NULL,
                   'tenant_developer', 'invited', now())
                """
            ),
            {"id": uuid4(), "tenant_id": tenant_b, "email": f"forged-{uuid4()}@example.org"},
        )
