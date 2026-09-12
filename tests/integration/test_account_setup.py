from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.routes.auth import setup_limiter
from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.service import ROLE_SCOPES
from graphrec_core.auth.setup_tokens import issue_setup_token
from graphrec_core.database.models import AccountSetupToken, TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from scripts import issue_account_setup_token

pytestmark = pytest.mark.integration

JSON = {"Accept": "application/json"}
PASSWORD = "setup flow test password"


def register(client: TestClient) -> tuple[UUID, str, str]:
    suffix = uuid4().hex[:12]
    email = f"setup-{suffix}@example.org"
    response = client.post(
        "/v1/tenants",
        json={"name": f"Setup Tenant {suffix}", "admin_email": email},
        headers={"Idempotency-Key": str(uuid4()), **JSON},
    )
    assert response.status_code == 201
    body = response.json()
    return UUID(body["id"]), email, body["setup_token"]


def setup(client: TestClient, **body: str):
    return client.post("/v1/auth/setup-password", json=body, headers=JSON)


def user_row(tenant_id: UUID) -> TenantUser:
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        user = session.scalar(select(TenantUser).where(TenantUser.role == "tenant_administrator"))
        assert user is not None
        session.expunge(user)
        return user


def assert_rejected(response) -> None:
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_setup_token"


def test_setup_token_activates_invited_administrator_once(client: TestClient) -> None:
    tenant_id, email, token = register(client)

    activated = setup(client, setup_token=token, password=PASSWORD, email=email)

    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["user_role"] == "tenant_administrator"
    assert body["scopes"] == ROLE_SCOPES["tenant_administrator"]
    user = user_row(tenant_id)
    assert user.status == "active"
    assert user.credential_digest is not None
    login = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}, headers=JSON)
    assert login.status_code == 200

    # The same token can never be used again, even with a different password.
    assert_rejected(setup(client, setup_token=token, password="another password 123"))
    login = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}, headers=JSON)
    assert login.status_code == 200
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        row = session.scalar(select(AccountSetupToken))
        assert row is not None and row.used_at is not None


def test_email_alone_can_no_longer_take_over_an_account(client: TestClient) -> None:
    tenant_id, email, token = register(client)
    assert setup(client, setup_token=token, password=PASSWORD).status_code == 200
    digest_before = user_row(tenant_id).credential_digest

    email_only = setup(client, email=email, password="attacker password 123")
    forged = setup(client, setup_token="x" * 43, email=email, password="attacker password 123")
    _, _, other_tenant_token = register(client)
    wrong_account = setup(
        client, setup_token=other_tenant_token, email=email, password="attacker password 123"
    )

    assert email_only.status_code == 422
    assert_rejected(forged)
    assert_rejected(wrong_account)
    assert user_row(tenant_id).credential_digest == digest_before
    attacker_login = client.post(
        "/v1/auth/login", json={"email": email, "password": "attacker password 123"}, headers=JSON
    )
    assert attacker_login.status_code == 401


def test_email_mismatch_does_not_consume_the_token(client: TestClient) -> None:
    tenant_id, email, token = register(client)

    assert_rejected(setup(client, setup_token=token, password=PASSWORD, email="other@example.org"))
    assert user_row(tenant_id).status == "invited"
    assert setup(client, setup_token=token, password=PASSWORD, email=email).status_code == 200


def test_expired_and_revoked_tokens_are_rejected(client: TestClient) -> None:
    tenant_id, _, original = register(client)
    user = user_row(tenant_id)
    past = datetime.now(timezone.utc) - timedelta(days=2)
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        expired, _ = issue_setup_token(
            session, tenant_id=tenant_id, user_id=user.id, ttl_seconds=300, now=past
        )

    assert_rejected(setup(client, setup_token=expired, password=PASSWORD))

    # Reissuing revokes every older unused token, including the registration token.
    assert issue_account_setup_token.main([user.email, "--tenant-id", str(tenant_id)]) == 0
    assert_rejected(setup(client, setup_token=original, password=PASSWORD))
    assert user_row(tenant_id).status == "invited"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        rows = session.scalars(select(AccountSetupToken)).all()
        assert len(rows) == 3
        assert sum(1 for row in rows if row.revoked_at is None and row.used_at is None) == 1


def test_reissue_script_prints_a_working_token(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant_id, email, _ = register(client)

    assert issue_account_setup_token.main([email]) == 0
    printed = capsys.readouterr().out
    token = next(
        line.split(":", 1)[1].strip() for line in printed.splitlines() if line.startswith("setup_token:")
    )

    assert setup(client, setup_token=token, password=PASSWORD).status_code == 200
    assert user_row(tenant_id).status == "active"
    # Active accounts cannot be reset through the setup flow.
    assert issue_account_setup_token.main([email]) == 1


def test_setup_tokens_cannot_reset_an_active_account(client: TestClient) -> None:
    tenant_id, _, _ = register(client)
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=user_id,
                tenant_id=tenant_id,
                email=f"active-{uuid4().hex[:8]}@example.org",
                display_name="Active",
                credential_digest=hash_password(PASSWORD),
                role="tenant_developer",
                status="active",
                created_at=now,
            )
        )
        session.flush()
        token, _ = issue_setup_token(
            session, tenant_id=tenant_id, user_id=user_id, ttl_seconds=3600, now=now
        )

    assert_rejected(setup(client, setup_token=token, password="replacement password 1"))


def test_registration_replay_does_not_reveal_the_setup_token(client: TestClient) -> None:
    suffix = uuid4().hex[:12]
    body = {"name": f"Replay Setup {suffix}", "admin_email": f"replay-{suffix}@example.org"}
    headers = {"Idempotency-Key": str(uuid4()), **JSON}

    first = client.post("/v1/tenants", json=body, headers=headers)
    replay = client.post("/v1/tenants", json=body, headers=headers)

    assert first.json()["setup_token"]
    assert replay.status_code == 200
    assert replay.json()["setup_token"] is None
    assert replay.json()["setup_token_expires_at"] is None


def test_setup_endpoint_is_rate_limited(client: TestClient) -> None:
    original_limit = setup_limiter.limit
    setup_limiter.limit = 2
    try:
        for _ in range(2):
            assert_rejected(setup(client, setup_token="y" * 43, password=PASSWORD))
        limited = setup(client, setup_token="y" * 43, password=PASSWORD)
    finally:
        setup_limiter.limit = original_limit

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(limited.headers["retry-after"]) >= 1
