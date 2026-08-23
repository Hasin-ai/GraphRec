"""Fixtures for the platform realm.

The realm's distinguishing feature is that authorization is *per permission*
rather than per role, so almost every test here needs an operator holding some
permissions and not others. That is what `operator` is: a factory that mints a
platform user with exactly the permissions asked for, signs them in, and caches
the token so a suite that wants eight different combinations pays for eight
sign-ins rather than eight per test.

Tenants are seeded through `graphrec_app` — the runtime path, under RLS — while
platform users are seeded as the owner, because `platform_users` is not a
tenant-owned table and the platform role holds no `INSERT` on it. Both of those
are the production arrangement rather than a convenience: an operator is created
by an installation procedure, not by a request.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from graphrec.auth.passwords import hash_password
from graphrec.common.enums import TenantStatus
from tests.isolation.conftest import _force_lifted

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.db

PASSWORD = "a-perfectly-adequate-passphrase"

#: All five, for the tests that want an operator who can see everything.
EVERYTHING = ("platform", "plan_management", "platform_scope", "monitoring", "audit")


def _url_for(role: str, password: str) -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    return f"postgresql+psycopg://{role}:{password}@{tail}"


@pytest.fixture(scope="session")
def estate_engine(owner_engine):
    """Seeds tenants as `graphrec_app`, exactly as registration does."""
    engine = sa.create_engine(
        _url_for(
            "graphrec_app", os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
        ),
        poolclass=sa.pool.NullPool,
    )
    yield engine
    engine.dispose()


def _seed_tenant(engine, *, label: str, status: str, plan_id: uuid.UUID) -> dict:
    tenant_id = uuid.uuid4()
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
                "status": status,
            },
        )
    return {"tenant_id": tenant_id, "code": code, "name": f"{label.title()} {suffix}"}


@pytest.fixture(scope="session")
def estate(estate_engine, owner_engine) -> Iterator[dict]:
    """Three tenants: two active and one already suspended.

    The suspended one exists so that "suspend a tenant" and "suspend a tenant
    that is already suspended" are both reachable without one test depending on
    another having run first.
    """
    with owner_engine.connect() as conn:
        plans = dict(
            conn.execute(
                sa.text(
                    "SELECT plan_code, plan_id FROM pricing_plans WHERE plan_code IN "
                    "('GROWTH', 'STARTER')"
                )
            ).all()
        )

    tenants = {
        "acme": _seed_tenant(
            estate_engine, label="acme", status=TenantStatus.ACTIVE.value, plan_id=plans["GROWTH"]
        ),
        "beta": _seed_tenant(
            estate_engine, label="beta", status=TenantStatus.ACTIVE.value, plan_id=plans["GROWTH"]
        ),
        "cold": _seed_tenant(
            estate_engine,
            label="cold",
            status=TenantStatus.SUSPENDED.value,
            plan_id=plans["STARTER"],
        ),
    }
    yield {"tenants": tenants, "plans": plans}

    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id = ANY(:ids)"),
            {"ids": [row["tenant_id"] for row in tenants.values()]},
        )


@pytest.fixture(scope="session")
def platform_api(settings, estate) -> Iterator[TestClient]:
    from apps.control_api.main import create_app

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture(scope="session")
def operator(platform_api, owner_engine) -> Iterator[Callable[..., str]]:
    """`operator("platform", "audit")` — a token holding exactly those.

    Keyed by the permission set, so asking twice costs one operator. The
    identifiers are random per run: an authorization test that passed because a
    row survived from a previous run would be worse than no test.
    """
    minted: dict[frozenset[str], str] = {}
    created: list[uuid.UUID] = []

    def _make(*permissions: str) -> str:
        key = frozenset(permissions)
        if key in minted:
            return minted[key]
        user_id = uuid.uuid4()
        email = f"op-{user_id.hex[:10]}@platform.example.com"
        with owner_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO platform_users (platform_user_id, email, display_name, "
                    "credential_digest, status) "
                    "VALUES (:pid, :email, 'Operator', :digest, 'active')"
                ),
                {"pid": user_id, "email": email, "digest": hash_password(PASSWORD)},
            )
            for permission in permissions:
                conn.execute(
                    sa.text(
                        "INSERT INTO platform_user_permissions (platform_user_id, permission) "
                        "VALUES (:pid, :perm)"
                    ),
                    {"pid": user_id, "perm": permission},
                )
        created.append(user_id)
        response = platform_api.post(
            "/v1/platform/auth/sign-in", json={"email": email, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        minted[key] = response.json()["access_token"]
        return minted[key]

    yield _make

    with owner_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM platform_users WHERE platform_user_id = ANY(:ids)"),
            {"ids": created},
        )


@pytest.fixture(scope="session")
def full_operator(operator) -> str:
    return operator(*EVERYTHING)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def platform_session(owner_engine):
    """An async session as `graphrec_platform`, for the domain-level tests.

    The board is worth exercising below HTTP as well as through it: the HTTP
    tests can only assert the *consistency* of whatever the installation happens
    to look like when they run, while a direct call can choose the instant it
    asks about and therefore choose which measurements are impossible.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        _url_for(
            "graphrec_platform",
            os.environ.get("POSTGRES_PLATFORM_PASSWORD", "graphrec_platform_local_only"),
        ),
        poolclass=sa.pool.NullPool,
    )
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()
