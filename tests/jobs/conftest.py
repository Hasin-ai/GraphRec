"""Fixtures for the job-queue suite.

Everything here connects as `graphrec_app` — the role a worker actually runs
as. A queue test run as the migration owner would prove nothing about the claim
function, because the owner can read `jobs` directly and would never discover
that a worker cannot.

The `jobs` table is emptied around every test. The claim query is global by
construction — a worker asks for the next job in the *system*, not the next job
in this test — so a row left behind by an earlier test is a row a later test
can claim, and the failure that produces is both intermittent and misleading.
"""

from __future__ import annotations

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
    from collections.abc import Iterator

pytestmark = [pytest.mark.db]


def _app_url() -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    password = os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
    return f"postgresql+psycopg://graphrec_app:{password}@{tail}"


@pytest.fixture
async def sessionmaker_app(owner_engine):
    """An async sessionmaker as `graphrec_app`.

    `NullPool` because several of these tests hold two or three sessions open at
    once to reproduce a race, and a pool sized for a request path would either
    serialise them — hiding the race — or exhaust itself waiting.
    """
    engine = create_async_engine(_app_url(), poolclass=sa.pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


@pytest.fixture
def _empty_queue(owner_engine) -> Iterator[None]:
    """No jobs before, no jobs after."""

    def wipe() -> None:
        # The owner is subject to `FORCE`d policies too, and no policy names it.
        # Lifting `FORCE` for the length of one statement is the procedure
        # migration 0002 documents for teardown, and it lives only in fixtures.
        with owner_engine.begin() as conn, _force_lifted(conn, "jobs"):
            conn.execute(sa.text("DELETE FROM jobs"))

    wipe()
    yield
    wipe()


@pytest.fixture
async def queue_tenants(sessionmaker_app, owner_engine, _empty_queue):
    """Two tenants, seeded the way registration seeds them.

    Two, because fair sharing is a claim about what happens *between* tenants
    and cannot be observed with one.
    """
    ids = {"alpha": uuid.uuid4(), "beta": uuid.uuid4()}
    suffix = uuid.uuid4().hex[:6].upper()

    for name, tenant_id in ids.items():
        async with sessionmaker_app() as session, session.begin():
            await bind_tenant(session, tenant_id)
            # `ck_tenants_active_requires_plan`: an active tenant is a tenant on
            # a plan. The constraint is the tenancy model refusing to let a
            # fixture invent a state the product does not have.
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
                    "code": f"JOB{suffix}{name[0].upper()}",
                    "name": f"Queue {name} {suffix}",
                    "status": TenantStatus.ACTIVE.value,
                },
            )

    yield ids

    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id IN (:a, :b)"),
            {"a": ids["alpha"], "b": ids["beta"]},
        )
