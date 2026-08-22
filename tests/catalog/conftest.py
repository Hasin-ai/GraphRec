"""Fixtures for the catalogue suite.

Everything connects as `graphrec_app`, the role a request actually runs as.
Running these as the migration owner would prove nothing: the owner holds grants
no request has, and the point of several of these tests is what a request
*cannot* do.

Two tenants, because "this product is not visible to that tenant" is not a
statement one tenant can make.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from graphrec.common.enums import TenantStatus
from graphrec.db.tenant_context import bind_tenant
from tests.isolation.conftest import _force_lifted

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


def _app_url() -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    password = os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
    return f"postgresql+psycopg://graphrec_app:{password}@{tail}"


@pytest.fixture
async def catalog_sessionmaker(owner_engine):
    """An async sessionmaker as `graphrec_app`.

    `NullPool` because a few of these tests hold two sessions open at once —
    one per tenant — and a pool sized for a request path would serialise them.
    """
    engine = create_async_engine(_app_url(), poolclass=sa.pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def catalog_tenants(
    catalog_sessionmaker, owner_engine
) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Two active tenants on GROWTH, seeded the way registration seeds them."""
    ids = {"alpha": uuid.uuid4(), "beta": uuid.uuid4()}
    suffix = uuid.uuid4().hex[:6].upper()

    for name, tenant_id in ids.items():
        async with catalog_sessionmaker() as session, session.begin():
            await bind_tenant(session, tenant_id)
            plan_id = await session.scalar(
                sa.text("SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH'")
            )
            await session.execute(
                sa.text(
                    "INSERT INTO tenants (tenant_id, plan_id, tenant_code, tenant_name, status) "
                    "VALUES (:tid, :plan, :code, :name, :status)"
                ),
                {
                    "tid": tenant_id,
                    "plan": plan_id,
                    "code": f"CAT{suffix}{name[0].upper()}",
                    "name": f"Catalog {name} {suffix}",
                    "status": TenantStatus.ACTIVE.value,
                },
            )

    yield ids

    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id = ANY(:ids)"),
            {"ids": list(ids.values())},
        )


@pytest.fixture
def bound(catalog_sessionmaker):
    """A committed transaction bound to one tenant — production's exact manoeuvre.

    `SET LOCAL` dies with its transaction, so the binding happens inside the
    `begin()` block rather than once when the session is opened. Phase 4 lost a
    day to the other arrangement.
    """

    @contextlib.asynccontextmanager
    async def _bound(tenant_id: uuid.UUID) -> AsyncIterator:
        async with catalog_sessionmaker() as session, session.begin():
            await bind_tenant(session, tenant_id)
            yield session

    return _bound


@pytest.fixture
def grant_override(owner_engine):
    """Grant a quota override to a tenant.

    Written as the owner with `FORCE` lifted for the length of one statement:
    `graphrec_app` holds `SELECT` on `quota_overrides` and nothing more, because
    a tenant raising its own limit is the failure the table exists to prevent.
    That the fixture has to reach for the escape hatch is the grant working.
    """
    granted: list[uuid.UUID] = []

    def _grant(tenant_id: uuid.UUID, *, usage_type: str, limit_value: int) -> uuid.UUID:
        override_id = uuid.uuid4()
        with owner_engine.begin() as conn, _force_lifted(conn, "quota_overrides"):
            conn.execute(
                sa.text(
                    "INSERT INTO quota_overrides (override_id, tenant_id, usage_type, "
                    "limit_value, reason, granted_by) "
                    "VALUES (:oid, :tid, :ut, :lv, 'catalogue suite', :tid)"
                ),
                {"oid": override_id, "tid": tenant_id, "ut": usage_type, "lv": limit_value},
            )
        granted.append(override_id)
        return override_id

    yield _grant

    if granted:
        with owner_engine.begin() as conn, _force_lifted(conn, "quota_overrides"):
            conn.execute(
                sa.text("DELETE FROM quota_overrides WHERE override_id = ANY(:ids)"),
                {"ids": granted},
            )


@pytest.fixture
def _empty_catalog(owner_engine) -> Iterator[None]:
    """No products before, none after. Categories go with them."""

    def wipe() -> None:
        with owner_engine.begin() as conn, _force_lifted(conn, "products"):
            conn.execute(sa.text("DELETE FROM products"))
        with owner_engine.begin() as conn, _force_lifted(conn, "product_categories"):
            conn.execute(sa.text("DELETE FROM product_categories"))

    wipe()
    yield
    wipe()


# The HTTP-level catalogue tests need a real app, real tokens and both tenant
# roles. That apparatus already exists for the authorization matrix, and a
# second copy of it would be a second thing to keep in step.
from tests.authz.conftest import (  # noqa: E402
    api,  # noqa: F401
    home_admin,  # noqa: F401
    home_dev,  # noqa: F401
    other_admin,  # noqa: F401
    realm,  # noqa: F401
    seed_engine,  # noqa: F401
)
