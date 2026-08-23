"""Fixtures for the audit suite.

Two roles connect here, and the difference between them is the whole subject.
`graphrec_app` writes a tenant's own history and reads it back through RLS.
`graphrec_platform` writes rows about tenants and reads across all of them.
Neither may edit or delete a row, and that is asserted against the live grants
rather than against a comment in a migration.

Seeds run as the runtime roles for the reason the isolation suite gives: the
owner is `FORCE`d out of the tenant tables, so an arrangement only the owner
could build would prove nothing about the roles that have to live with it.
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
from tests.isolation.conftest import _force_lifted

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.db

PASSWORD = "a-perfectly-adequate-passphrase"


def _url_for(role: str, password: str) -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    return f"postgresql+psycopg://{role}:{password}@{tail}"


@pytest.fixture(scope="session")
def audit_app_engine(owner_engine):
    engine = sa.create_engine(
        _url_for(
            "graphrec_app", os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
        ),
        poolclass=sa.pool.NullPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def audit_platform_engine(owner_engine):
    engine = sa.create_engine(
        _url_for(
            "graphrec_platform",
            os.environ.get("POSTGRES_PLATFORM_PASSWORD", "graphrec_platform_local_only"),
        ),
        poolclass=sa.pool.NullPool,
    )
    yield engine
    engine.dispose()


def _seed_tenant(engine, label: str, plan_id: uuid.UUID) -> dict[str, uuid.UUID | str]:
    tenant_id, user_id, dev_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    code = f"{label[:3].upper()}{suffix[:5].upper()}"
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
                "code": code,
                "name": f"{label.title()} {suffix}",
                "status": TenantStatus.ACTIVE.value,
            },
        )
        # Both roles, because /v1/audit-logs is administrator-only and "only"
        # is a claim that needs someone to be refused.
        for uid, role, email in (
            (user_id, TenantRole.TENANT_ADMINISTRATOR.value, f"admin-{suffix}@example.com"),
            (dev_id, TenantRole.TENANT_DEVELOPER.value, f"dev-{suffix}@example.com"),
        ):
            conn.execute(
                sa.text(
                    "INSERT INTO tenant_users (tenant_user_id, tenant_id, email, display_name, "
                    "credential_digest, role, status) "
                    "VALUES (:uid, :tid, :email, :dn, :digest, :role, :status)"
                ),
                {
                    "uid": uid,
                    "tid": tenant_id,
                    "email": email,
                    "dn": role,
                    "digest": hash_password(PASSWORD),
                    "role": role,
                    "status": UserStatus.ACTIVE.value,
                },
            )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "code": code,
        "email": f"admin-{suffix}@example.com",
        "dev_email": f"dev-{suffix}@example.com",
    }


@pytest.fixture(scope="session")
def audited_tenants(audit_app_engine, owner_engine) -> Iterator[dict[str, dict]]:
    """Two tenants, because "a tenant cannot see foreign history" needs two."""
    with owner_engine.connect() as conn:
        plan_id = conn.execute(
            sa.text("SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH'")
        ).scalar_one()
    left = _seed_tenant(audit_app_engine, "left", plan_id)
    right = _seed_tenant(audit_app_engine, "rght", plan_id)
    yield {"left": left, "right": right}

    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id = ANY(:ids)"),
            {"ids": [left["tenant_id"], right["tenant_id"]]},
        )


@pytest.fixture(scope="session")
def audit_api(settings, audited_tenants) -> Iterator[TestClient]:
    from apps.control_api.main import create_app

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def _sign_in(api: TestClient, tenant: dict, email_key: str) -> str:
    response = api.post(
        "/v1/auth/sign-in",
        json={"tenant_code": tenant["code"], "email": tenant[email_key], "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


@pytest.fixture(scope="session")
def left_admin(audit_api, audited_tenants) -> str:
    return _sign_in(audit_api, audited_tenants["left"], "email")


@pytest.fixture(scope="session")
def left_developer(audit_api, audited_tenants) -> str:
    return _sign_in(audit_api, audited_tenants["left"], "dev_email")
