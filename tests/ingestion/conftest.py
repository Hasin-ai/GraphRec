"""Fixtures for the ingestion suite.

Everything connects as `graphrec_app` — the role both a request handler and a
worker actually run as. Running these as the migration owner would prove nothing
about the parts that matter: the owner can read `submissions` directly and would
never discover that a merge statement is constrained by the tenant's own policy.

Two tenants, because "this batch is not visible to that tenant" is not a
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

# The HTTP half of this suite (`test_ingest_api.py`) needs a running app, a
# realm of tenants and two signed-in people. All three already exist, built
# once and correctly, in the authorization suite. They are re-exported here
# rather than rebuilt: a fixture imported into a conftest is collected as that
# directory's own, so the ingest suite gets its own tenants and its own client
# — it does not reach into another suite's state.
from tests.authz.conftest import (  # noqa: F401
    api,
    home_admin,
    home_dev,
    other_admin,
    realm,
    seed_engine,
)
from tests.isolation.conftest import _force_lifted

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

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
async def ingest_sessionmaker(owner_engine):
    """An async sessionmaker as `graphrec_app`.

    `NullPool` because the processor holds two connections at once — the
    handler's transaction and the control transaction — and several tests hold
    a third to observe what the control transaction published *while* the
    handler was still running. A pool sized for a request path would deadlock
    waiting for itself.
    """
    engine = create_async_engine(_app_url(), poolclass=sa.pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


def _wipe(owner_engine) -> None:
    """Dependents first. The order is the foreign keys read backwards.

    `FORCE` is lifted for the length of each statement — the owner is subject to
    the policies too, and no policy names it. That a teardown has to reach for
    the escape hatch is the isolation working.
    """
    for table in (
        # Metering first: ingestion now writes `usage_events`, and a ledger row
        # left behind is a tenant that starts the next test part-way through
        # their month.
        "usage_events",
        "monthly_usage_aggregates",
        "ingest_staging_items",
        "submission_errors",
        "interaction_events",
        "submissions",
        "customers",
        "products",
        "product_categories",
        "jobs",
    ):
        with owner_engine.begin() as conn, _force_lifted(conn, table):
            conn.execute(sa.text(f"DELETE FROM {table}"))


@pytest.fixture
def _empty_ingestion(owner_engine) -> Iterator[None]:
    """Nothing before, nothing after.

    The claim query is global by construction — a worker asks for the next job
    in the *system* — so a submission left behind by an earlier test is work a
    later test's worker will pick up, and the failure that produces is both
    intermittent and misleading.
    """
    _wipe(owner_engine)
    yield
    _wipe(owner_engine)


@pytest.fixture
async def ingest_tenants(
    ingest_sessionmaker, owner_engine, _empty_ingestion
) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Two active tenants on GROWTH, seeded the way registration seeds them."""
    ids = {"alpha": uuid.uuid4(), "beta": uuid.uuid4()}
    suffix = uuid.uuid4().hex[:6].upper()

    for name, tenant_id in ids.items():
        async with ingest_sessionmaker() as session, session.begin():
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
                    "code": f"ING{suffix}{name[0].upper()}",
                    "name": f"Ingest {name} {suffix}",
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
def tenant(ingest_tenants) -> uuid.UUID:
    return ingest_tenants["alpha"]


@pytest.fixture
def bound(ingest_sessionmaker):
    """A committed transaction bound to one tenant — production's exact manoeuvre.

    `SET LOCAL` dies with its transaction, so the binding happens inside the
    `begin()` block rather than once when the session is opened.
    """

    @contextlib.asynccontextmanager
    async def _bound(tenant_id: uuid.UUID) -> AsyncIterator:
        async with ingest_sessionmaker() as session, session.begin():
            await bind_tenant(session, tenant_id)
            yield session

    return _bound


@pytest.fixture
def seed_products(bound):
    """Put products in a tenant's catalogue without going through the API.

    Events reference products, so most event tests need a catalogue first and
    none of them are testing the catalogue.
    """

    async def _seed(tenant_id: uuid.UUID, *external_ids: str) -> None:
        async with bound(tenant_id) as session:
            for external_id in external_ids:
                await session.execute(
                    sa.text(
                        "INSERT INTO products (product_id, tenant_id, external_product_id, "
                        "    title, is_active, availability, attributes) "
                        "VALUES (gen_random_uuid(), :tid, :eid, :title, true, 'in_stock', '{}')"
                    ),
                    {"tid": tenant_id, "eid": external_id, "title": f"Product {external_id}"},
                )

    return _seed


@pytest.fixture
def drain(ingest_sessionmaker):
    """Run the real worker, with the real registry, until the queue is empty.

    The real registry — `apps.job_worker.registry` — rather than one assembled
    for the test. A handler that works when a test wires it up but is not
    registered in the process that ships is a handler that does not run.

    And the real counters, for the same reason. `Worker` defaults to a
    process-local pair so that a unit test needs no Redis; a worker that takes
    that default in a deployment moves a counter nobody else can see, and
    `/v1/usage` — which reads the shared one — under-reports every batch the
    worker charged. That is exactly the defect this fixture failed to catch
    while it was building its own worker differently from
    `apps/job_worker/main.py`.
    """
    from redis.asyncio import ConnectionPool, Redis

    from apps.job_worker.registry import registry
    from graphrec.common.config import Settings
    from graphrec.domain.metering.counters import RedisUsageCounters, ResilientUsageCounters
    from graphrec.jobs.worker import Worker

    async def _drain(limit: int = 8) -> int:
        settings = Settings(
            environment="ci", job_lease_seconds=60, job_heartbeat_seconds=1, job_max_attempts=3
        )
        pool = ConnectionPool.from_url(str(settings.redis_url))
        redis = Redis(connection_pool=pool)
        worker = Worker(
            name="ingest_test",
            sessionmaker=ingest_sessionmaker,
            registry=registry,
            settings=settings,
            counters=ResilientUsageCounters(RedisUsageCounters(redis)),
        )
        try:
            ran = 0
            for _ in range(limit):
                if not await worker.run_once():
                    break
                ran += 1
            return ran
        finally:
            await redis.aclose()
            # The client does not disconnect a pool it was handed, and a
            # connection collected by the garbage collector inside an async
            # test is an unraisable `ResourceWarning` — which this suite
            # promotes to an error.
            await pool.disconnect()

    return _drain
