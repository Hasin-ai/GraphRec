"""Fixtures for the training suite.

Training reads what ingestion wrote, so the tenants, the sessionmaker and the
teardown are the ingestion suite's, re-exported rather than rebuilt. What is
added here is the three things training needs and ingestion does not: a
catalogue with interactions in it, an artifact store on disk, and a worker that
runs the real pipeline.

**The store is `LocalArtifactStore`, not a mock.** It is a real implementation of
the port with real atomic writes and real digests, so a test that resumes from a
checkpoint resumes from a file that was actually written and verified. A mock
would let the resume test pass against a store that never persisted anything,
which is precisely the failure the test exists to catch.

**The worker is the real `Worker` with a real registry.** Attempts, leases,
cancellation and the terminal transition are the queue's behaviour, and a test
that drove `TrainingPipeline.run` directly would be testing nine stages without
testing the thing that runs them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from graphrec.domain.metering.counters import InMemoryUsageCounters

# The HTTP half of this suite (`test_training_api.py`) needs a running app, a
# realm of tenants and two signed-in people, exactly as the ingest suite does.
# Re-exported rather than rebuilt, for the reason given there.
from tests.authz.conftest import (  # noqa: F401
    api,
    home_admin,
    home_dev,
    other_admin,
    realm,
    seed_engine,
)
from tests.ingestion.conftest import (  # noqa: F401
    _app_url,
    _empty_ingestion,
    bound,
    ingest_sessionmaker,
    ingest_tenants,
    seed_products,
)
from tests.isolation.conftest import _force_lifted
from tests.metering.conftest import plan_limit  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.db]

#: Small enough to train in seconds, large enough to leave every user a
#: validation and a test target after `leave_last_out` takes two each.
USERS = 24
ITEMS = 12
EVENTS_PER_USER = 8

#: Fixed, so a window boundary is a decision in the test rather than a property
#: of the hour it runs at.
NOW = dt.datetime(2026, 8, 14, 9, 41, 2, tzinfo=dt.UTC)


@pytest.fixture
def counters() -> InMemoryUsageCounters:
    return InMemoryUsageCounters()


@pytest.fixture
def _empty_training(owner_engine) -> Iterator[None]:
    """Training's own tables, emptied around every test.

    In dependency order, children first. `models` is included: the service
    creates a tenant's `default` model lazily, and a leftover one would make the
    "created on first request" assertion pass for the wrong reason.
    """
    tables = ("training_metrics", "dataset_snapshots", "training_jobs", "models")

    def wipe() -> None:
        for table in tables:
            with owner_engine.begin() as conn, _force_lifted(conn, table):
                conn.execute(sa.text(f"DELETE FROM {table}"))

    wipe()
    yield
    wipe()


@pytest.fixture
def training_tenants(_empty_training, ingest_tenants):  # noqa: F811
    """The ingestion suite's two tenants, with training's tables emptied first.

    The wipe is a dependency rather than a separate fixture the tests remember
    to request, because a test that forgot it would fail somewhere else — on a
    leftover active job blocking an unrelated request — and the failure would
    point at the wrong thing.
    """
    return ingest_tenants


@pytest.fixture
def tenant(training_tenants) -> uuid.UUID:
    return training_tenants["alpha"]


@pytest.fixture
def artifact_store(tmp_path):
    from graphrec.storage.local import LocalArtifactStore

    return LocalArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def seed_interactions(bound, seed_products):  # noqa: F811
    """A catalogue and a history dense enough to train on.

    Deterministic rather than random: item `(user + step) % ITEMS` gives every
    user a distinct trajectory through the same catalogue, which is enough
    structure for the graph to be non-trivial and little enough that the run
    finishes inside a test.

    Timestamps step backwards from `NOW` so that every event lands inside a
    30-day window and the last one per user — the leave-last-out target — is
    unambiguously the latest.
    """

    async def _seed(tenant_id: uuid.UUID, *, users: int = USERS, items: int = ITEMS) -> None:
        await seed_products(tenant_id, *[f"P{index:03d}" for index in range(items)])
        async with bound(tenant_id) as session:
            product_ids = dict(
                (
                    await session.execute(
                        sa.text("SELECT external_product_id, product_id FROM products")
                    )
                ).all()
            )
            for user in range(users):
                customer_id = uuid.uuid4()
                await session.execute(
                    sa.text(
                        "INSERT INTO customers (customer_id, tenant_id, external_customer_id, "
                        "    first_seen_at, last_seen_at) "
                        "VALUES (:cid, :tid, :ext, :first, :last)"
                    ),
                    {
                        "cid": customer_id,
                        "tid": tenant_id,
                        "ext": f"U{user:03d}",
                        "first": NOW - dt.timedelta(days=EVENTS_PER_USER),
                        "last": NOW,
                    },
                )
                rows = [
                    {
                        "eid": uuid.uuid4(),
                        "tid": tenant_id,
                        "cid": customer_id,
                        "pid": product_ids[f"P{(user + step) % items:03d}"],
                        "ext": f"E-{user:03d}-{step:02d}",
                        "at": NOW - dt.timedelta(days=EVENTS_PER_USER - step, hours=user % 12),
                    }
                    for step in range(EVENTS_PER_USER)
                ]
                await session.execute(
                    sa.text(
                        "INSERT INTO interaction_events (event_id, tenant_id, customer_id, "
                        "    product_id, external_event_id, event_type, occurred_at, "
                        "    received_at) "
                        "VALUES (:eid, :tid, :cid, :pid, :ext, 'purchase', :at, :at)"
                    ),
                    rows,
                )

    return _seed


@pytest.fixture
def pipeline(artifact_store):
    """The real pipeline, with the minimum lowered to what a test can seed.

    `min_sequences=1` rather than 1,000. The bound itself is tested at the
    admission boundary, where it belongs; forcing every pipeline test to seed a
    thousand users would buy nothing except minutes.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline

    return TrainingPipeline(artifact_store, min_sequences=1, seed=7, k=5)


@pytest.fixture
def run_worker(ingest_sessionmaker, pipeline):  # noqa: F811
    """Claim and run training jobs with the real `Worker`.

    `job_max_attempts` and the lease are the production settings' shape but
    shorter, so a test that means to observe a retry does not wait two minutes
    for a lease to lapse.
    """
    from graphrec.common.config import Settings
    from graphrec.jobs.handlers import HandlerRegistry
    from graphrec.jobs.states import JobType
    from graphrec.jobs.worker import Worker

    registry = HandlerRegistry()
    registry.register(JobType.TRAINING)(pipeline.run)

    async def _run(limit: int = 4) -> int:
        worker = Worker(
            name="training_test",
            sessionmaker=ingest_sessionmaker,
            registry=registry,
            settings=Settings(
                environment="ci",
                job_lease_seconds=120,
                job_heartbeat_seconds=1,
                job_max_attempts=3,
            ),
        )
        ran = 0
        for _ in range(limit):
            if not await worker.run_once():
                break
            ran += 1
        return ran

    return _run


@pytest.fixture
def service():
    """A `TrainingService` with the cooldown off unless a test asks for it.

    Zero rather than 900, because almost every test here requests a run and then
    requests another, and a fifteen-minute cooldown would make each of them a
    test of the cooldown. `test_admission.py` sets it deliberately.
    """
    from graphrec.domain.training.service import TrainingService

    return TrainingService(cooldown_seconds=0, min_sequences=1)
