"""Fixtures for the authorization matrix.

Unlike the isolation suite, these tests go through the HTTP surface: a real app,
a real token, a real database. The point is not that the SQL is right — the
isolation suite covers that — but that the five gates run in the right order and
produce the right status codes, including the ones whose *wrongness* would be a
leak (403 where 404 is required).
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from graphrec.auth.passwords import hash_password
from graphrec.common.enums import TenantRole, TenantStatus, UserStatus

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.authz

PASSWORD = "a-perfectly-adequate-passphrase"


def _app_url() -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    password = os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
    return f"postgresql+psycopg://graphrec_app:{password}@{tail}"


@pytest.fixture(scope="session")
def seed_engine(owner_engine):
    """Seeds through the runtime role, exactly as registration does."""
    engine = sa.create_engine(_app_url(), poolclass=sa.pool.NullPool)
    yield engine
    engine.dispose()


def _make_tenant(
    engine, *, label: str, status: str, plan_id: uuid.UUID | None
) -> dict[str, uuid.UUID | str]:
    tenant_id = uuid.uuid4()
    admin_id, dev_id = uuid.uuid4(), uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    digest = hash_password(PASSWORD)
    with engine.connect() as conn, conn.begin():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text(
                "INSERT INTO tenants (tenant_id, plan_id, tenant_code, tenant_name, status) "
                "VALUES (:tid, :plan, :code, :name, :status)"
            ),
            {
                "tid": tenant_id,
                "plan": plan_id,
                "code": f"{label[:3].upper()}{suffix[:5].upper()}",
                "name": f"{label.title()} {suffix}",
                "status": status,
            },
        )
        for user_id, role, email in (
            (admin_id, TenantRole.TENANT_ADMINISTRATOR.value, f"admin-{suffix}@example.com"),
            (dev_id, TenantRole.TENANT_DEVELOPER.value, f"dev-{suffix}@example.com"),
        ):
            conn.execute(
                sa.text(
                    "INSERT INTO tenant_users (tenant_user_id, tenant_id, email, display_name, "
                    "credential_digest, role, status) "
                    "VALUES (:uid, :tid, :email, :dn, :digest, :role, :status)"
                ),
                {
                    "uid": user_id,
                    "tid": tenant_id,
                    "email": email,
                    "dn": role,
                    "digest": digest,
                    "role": role,
                    "status": UserStatus.ACTIVE.value,
                },
            )
    return {
        "tenant_id": tenant_id,
        "admin_id": admin_id,
        "dev_id": dev_id,
        "code": f"{label[:3].upper()}{suffix[:5].upper()}",
        "admin_email": f"admin-{suffix}@example.com",
        "dev_email": f"dev-{suffix}@example.com",
    }


@pytest.fixture(scope="session")
def realm(owner_engine, seed_engine) -> Iterator[dict]:
    """Two active tenants, one suspended tenant, and one platform operator."""
    with owner_engine.connect() as conn:
        plan_id = conn.execute(
            sa.text("SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH'")
        ).scalar_one()

    home = _make_tenant(
        seed_engine, label="home", status=TenantStatus.ACTIVE.value, plan_id=plan_id
    )
    other = _make_tenant(
        seed_engine, label="other", status=TenantStatus.ACTIVE.value, plan_id=plan_id
    )
    frozen = _make_tenant(
        seed_engine, label="frzn", status=TenantStatus.SUSPENDED.value, plan_id=plan_id
    )

    operator_id = uuid.uuid4()
    operator_email = f"op-{operator_id.hex[:8]}@platform.example.com"
    with owner_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_users (platform_user_id, email, display_name, "
                "credential_digest, status) VALUES (:pid, :email, 'Operator', :digest, 'active')"
            ),
            {"pid": operator_id, "email": operator_email, "digest": hash_password(PASSWORD)},
        )
        for permission in ("platform", "monitoring"):
            conn.execute(
                sa.text(
                    "INSERT INTO platform_user_permissions (platform_user_id, permission) "
                    "VALUES (:pid, :perm)"
                ),
                {"pid": operator_id, "perm": permission},
            )

    yield {
        "home": home,
        "other": other,
        "frozen": frozen,
        "operator_id": operator_id,
        "operator_email": operator_email,
    }

    with owner_engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY"))
        try:
            conn.execute(
                sa.text("DELETE FROM tenants WHERE tenant_id = ANY(:ids)"),
                {"ids": [home["tenant_id"], other["tenant_id"], frozen["tenant_id"]]},
            )
            conn.execute(
                sa.text("DELETE FROM platform_users WHERE platform_user_id = :pid"),
                {"pid": operator_id},
            )
        finally:
            conn.execute(sa.text("ALTER TABLE tenants FORCE ROW LEVEL SECURITY"))


@pytest.fixture(scope="session")
def api(settings, realm) -> Iterator[TestClient]:
    from apps.control_api.main import create_app

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def _sign_in(api: TestClient, tenant: dict, who: str) -> str:
    response = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": tenant["code"],
            "email": tenant[f"{who}_email"],
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


@pytest.fixture(scope="session")
def home_admin(api, realm) -> str:
    return _sign_in(api, realm["home"], "admin")


@pytest.fixture(scope="session")
def home_dev(api, realm) -> str:
    return _sign_in(api, realm["home"], "dev")


@pytest.fixture(scope="session")
def other_admin(api, realm) -> str:
    return _sign_in(api, realm["other"], "admin")


@pytest.fixture(scope="session")
def operator_token(api, realm) -> str:
    response = api.post(
        "/v1/platform/auth/sign-in",
        json={"email": realm["operator_email"], "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def fresh_tenant(owner_engine, seed_engine, api):
    """A tenant of one's own, for tests that change what they read.

    `realm` is session-scoped and every sign-in in this suite draws on it, so a
    test that changes a password, a role or a status there is changing what a
    later test authenticates with. This hands out a private tenant instead —
    same shape, same two users, deleted afterwards — and returns it already
    signed in as both roles, because every caller needs that immediately.
    """
    with owner_engine.connect() as conn:
        plan_id = conn.execute(
            sa.text("SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH'")
        ).scalar_one()

    created: list[uuid.UUID] = []

    def factory(label: str = "cns") -> dict:
        tenant = _make_tenant(
            seed_engine, label=label, status=TenantStatus.ACTIVE.value, plan_id=plan_id
        )
        created.append(tenant["tenant_id"])  # type: ignore[arg-type]
        tenant["admin_token"] = _sign_in(api, tenant, "admin")
        tenant["dev_token"] = _sign_in(api, tenant, "dev")
        return tenant

    yield factory

    with owner_engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY"))
        try:
            conn.execute(
                sa.text("DELETE FROM tenants WHERE tenant_id = ANY(:ids)"), {"ids": created}
            )
        finally:
            conn.execute(sa.text("ALTER TABLE tenants FORCE ROW LEVEL SECURITY"))
