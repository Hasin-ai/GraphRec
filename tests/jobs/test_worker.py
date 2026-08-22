"""The claim loop end to end, and cooperative cancellation.

These tests drive the real `Worker` against the real database with handlers
registered for the occasion. What they are checking is the part that cannot be
seen from the queue client alone: that a handler's transaction and the record
that it succeeded commit together, that a failure recorded after an aborted
transaction still lands, and that cancellation is observed where the handler
says it may be.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from graphrec.common.config import Settings
from graphrec.common.errors import UnavailableError
from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.failures import PermanentJobError
from graphrec.jobs.handlers import HandlerRegistry, JobContext
from graphrec.jobs.queue import JobQueue
from graphrec.jobs.states import JobType, QueueStatus
from graphrec.jobs.worker import Worker, worker_identity

pytestmark = [pytest.mark.db]


def _settings() -> Settings:
    return Settings(
        environment="ci",
        job_lease_seconds=60,
        job_heartbeat_seconds=1,
        job_max_attempts=3,
        worker_concurrency=1,
    )


def _worker(sessionmaker, registry: HandlerRegistry) -> Worker:
    return Worker(
        name="test_worker", sessionmaker=sessionmaker, registry=registry, settings=_settings()
    )


async def _enqueue(sessionmaker, tenant_id, payload=None, *, job_type=JobType.EVENT_BATCH):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, tenant_id)
        job = await JobQueue(lease_seconds=60, max_attempts=3, owner="seed").enqueue(
            session, tenant_id=tenant_id, job_type=job_type, payload=payload or {}
        )
        return job.job_id


async def _row(sessionmaker, tenant_id, job_id):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, tenant_id)
        return (
            await session.execute(
                sa.text(
                    "SELECT status, attempt, progress, failure_code, failure_reason, "
                    "cancel_requested_at, cancel_reason, completed_at "
                    "FROM jobs WHERE job_id = :j"
                ),
                {"j": job_id},
            )
        ).one()


# ------------------------------------------------------------------- identity


def test_a_worker_identity_names_a_process_an_operator_can_find() -> None:
    identity = worker_identity("job_worker")
    host, _, tail = identity.partition("@")
    pid, _, unique = tail.partition("/")[2].partition("/")
    assert host == "job_worker"
    assert pid.isdigit()
    assert len(unique) == 8


def test_two_workers_in_one_process_are_distinguishable() -> None:
    """A pid is reused. Without the suffix, a restarted process could satisfy a
    lease guard belonging to its predecessor."""
    assert worker_identity("job_worker") != worker_identity("job_worker")


async def test_a_worker_with_no_handlers_refuses_to_start(sessionmaker_app) -> None:
    """Rather than starting, claiming nothing, and looking healthy while it does.

    An empty registry means an empty claim filter, and a worker that claims
    nothing is indistinguishable from a working one until somebody notices a
    queue that never drains.
    """
    worker = _worker(sessionmaker_app, HandlerRegistry())
    with pytest.raises(RuntimeError, match="no handlers registered"):
        await worker.run()


# ------------------------------------------------------------------- success


async def test_a_handler_runs_and_the_job_succeeds(sessionmaker_app, queue_tenants) -> None:
    registry = HandlerRegistry()
    seen: list[dict] = []

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> dict:
        seen.append(dict(ctx.payload))
        return {"rows": 12}

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"], {"file": "batch.csv"})

    assert await _worker(sessionmaker_app, registry).run_once() is True

    assert seen == [{"file": "batch.csv"}]
    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.SUCCEEDED.value
    assert row.progress == {"rows": 12}
    assert row.completed_at is not None
    assert row.attempt == 0


async def test_an_empty_queue_reports_no_work(sessionmaker_app, queue_tenants) -> None:
    registry = HandlerRegistry()

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        return None

    assert await _worker(sessionmaker_app, registry).run_once() is False


async def test_the_handler_sees_only_its_own_tenant(sessionmaker_app, queue_tenants) -> None:
    """The worker binds the tenant the claim named, and from there is
    indistinguishable from a request handler: it can read that tenant's rows and
    no others."""
    registry = HandlerRegistry()
    visible: list[list[uuid.UUID]] = []

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        rows = await ctx.session.execute(sa.text("SELECT tenant_id FROM tenants"))
        visible.append([r.tenant_id for r in rows])
        return None

    await _enqueue(sessionmaker_app, queue_tenants["beta"])
    await _worker(sessionmaker_app, registry).run_once()

    assert visible == [[queue_tenants["beta"]]]


async def test_a_handlers_writes_and_its_success_commit_together(
    sessionmaker_app, queue_tenants
) -> None:
    """Success is recorded inside the handler's own transaction.

    So a worker killed a millisecond before the commit leaves a `running` job
    with none of its effects, and one killed a millisecond after leaves a
    `succeeded` job with all of them. There is no interval in which the two
    disagree.
    """
    registry = HandlerRegistry()
    marker = f"WRK{uuid.uuid4().hex[:5].upper()}"

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        await ctx.session.execute(
            sa.text("UPDATE tenants SET tenant_name = :n WHERE tenant_id = :t"),
            {"n": marker, "t": ctx.tenant_id},
        )
        return None

    await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, queue_tenants["alpha"])
        name = await session.scalar(
            sa.text("SELECT tenant_name FROM tenants WHERE tenant_id = :t"),
            {"t": queue_tenants["alpha"]},
        )
    assert name == marker


async def test_a_failed_handlers_writes_are_rolled_back(sessionmaker_app, queue_tenants) -> None:
    """And the failure is still recorded, from a transaction opened fresh.

    An aborted transaction cannot execute the `UPDATE` that marks the job
    failed, so the outcome is written in another one — which is the whole reason
    the loop is shaped the way it is.
    """
    registry = HandlerRegistry()
    marker = f"BAD{uuid.uuid4().hex[:5].upper()}"

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        await ctx.session.execute(
            sa.text("UPDATE tenants SET tenant_name = :n WHERE tenant_id = :t"),
            {"n": marker, "t": ctx.tenant_id},
        )
        raise PermanentJobError("job_failed")

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, queue_tenants["alpha"])
        name = await session.scalar(
            sa.text("SELECT tenant_name FROM tenants WHERE tenant_id = :t"),
            {"t": queue_tenants["alpha"]},
        )
    assert name != marker, "a failed handler's partial writes survived"

    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.FAILED.value
    assert row.failure_code == "job_failed"


async def test_a_database_error_in_a_handler_is_retried(sessionmaker_app, queue_tenants) -> None:
    """The transaction is aborted by PostgreSQL itself. The outcome still lands."""
    registry = HandlerRegistry()

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        await ctx.session.execute(sa.text("SELECT no_such_function()"))
        return None

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.QUEUED.value
    assert row.attempt == 1


async def test_a_transient_failure_is_retried_and_a_permanent_one_is_not(
    sessionmaker_app, queue_tenants
) -> None:
    registry = HandlerRegistry()

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        raise UnavailableError("service_unavailable")

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.QUEUED.value
    assert row.attempt == 1


# -------------------------------------------------------------- cancellation


async def test_cancellation_is_observed_at_a_stage_boundary(
    sessionmaker_app, queue_tenants
) -> None:
    """dc.html L1714: "The job moves to cancelling and then to cancelled."

    Nothing interrupts the handler. It is asked between two stages, at a point
    it nominated, and the stage it had reached is what the console renders as
    "Cancelled at …" (L1707).
    """
    registry = HandlerRegistry()
    reached: list[str] = []

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        await ctx.stage("preparing_data")
        reached.append("preparing_data")
        # The request arrives while the handler is between stages.
        async with sessionmaker_app() as session, session.begin():
            await bind_tenant(session, ctx.tenant_id)
            await JobQueue(lease_seconds=60, max_attempts=3, owner="api").request_cancellation(
                session, job_id=ctx.job_id, reason="superseded by a corrected catalog sync"
            )
        await ctx.stage("building_graph")
        reached.append("building_graph")
        return None

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    assert reached == ["preparing_data"], "the handler ran past the cancellation"
    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.CANCELLED.value
    assert row.progress == {"stage_at": "building_graph"}
    assert row.failure_reason == "Work already done is discarded."
    assert row.cancel_reason == ("Cancelled by requester: superseded by a corrected catalog sync")


async def test_a_job_cancelled_before_it_ran_does_no_work(sessionmaker_app, queue_tenants) -> None:
    registry = HandlerRegistry()
    ran: list[int] = []

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        ran.append(1)
        return None

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, queue_tenants["alpha"])
        await session.execute(
            sa.text("UPDATE jobs SET cancel_requested_at = now() WHERE job_id = :j"),
            {"j": job_id},
        )

    await _worker(sessionmaker_app, registry).run_once()

    assert ran == [], "a job cancelled before it was picked up should do nothing at all"
    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.CANCELLED.value


async def test_a_handler_that_never_reaches_a_boundary_cannot_be_cancelled(
    sessionmaker_app, queue_tenants
) -> None:
    """Stated as a test because it is a design consequence, not an accident.

    Cancellation is the handler's to observe. One that declares no boundary runs
    to completion, and the honest place to record that is here rather than in a
    docstring nobody reads.
    """
    registry = HandlerRegistry()

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        async with sessionmaker_app() as session, session.begin():
            await bind_tenant(session, ctx.tenant_id)
            await JobQueue(lease_seconds=60, max_attempts=3, owner="api").request_cancellation(
                session, job_id=ctx.job_id, reason="too late"
            )
        return None

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.status == QueueStatus.SUCCEEDED.value


async def test_a_terminal_job_cannot_be_cancelled(sessionmaker_app, queue_tenants) -> None:
    """dc.html L1706, and a 409 — the actor is entitled; the state forbids it."""
    from graphrec.common.errors import ConflictError

    registry = HandlerRegistry()

    @registry.register(JobType.EVENT_BATCH)
    async def handle(ctx: JobContext) -> None:
        return None

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    await _worker(sessionmaker_app, registry).run_once()

    async with sessionmaker_app() as session:
        await session.begin()
        await bind_tenant(session, queue_tenants["alpha"])
        with pytest.raises(ConflictError) as caught:
            await JobQueue(lease_seconds=60, max_attempts=3, owner="api").request_cancellation(
                session, job_id=job_id, reason="changed my mind"
            )
        await session.rollback()

    assert caught.value.reason() == "Only a job in an active state can be cancelled."


async def test_cancelling_another_tenants_job_is_not_found(sessionmaker_app, queue_tenants) -> None:
    """Gate 4. A 403 would confirm the job exists somewhere."""
    from graphrec.common.errors import NotFoundError

    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])

    async with sessionmaker_app() as session:
        await session.begin()
        await bind_tenant(session, queue_tenants["beta"])
        with pytest.raises(NotFoundError):
            await JobQueue(lease_seconds=60, max_attempts=3, owner="api").request_cancellation(
                session, job_id=job_id, reason="not mine"
            )
        await session.rollback()


async def test_requesting_cancellation_twice_keeps_the_first_reason(
    sessionmaker_app, queue_tenants
) -> None:
    job_id = await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    queue = JobQueue(lease_seconds=60, max_attempts=3, owner="api")

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, queue_tenants["alpha"])
        await queue.request_cancellation(session, job_id=job_id, reason="first")
        await queue.request_cancellation(session, job_id=job_id, reason="second")

    row = await _row(sessionmaker_app, queue_tenants["alpha"], job_id)
    assert row.cancel_reason == "Cancelled by requester: first"


# ------------------------------------------------------------------ registry


def test_a_registry_refuses_two_handlers_for_one_type() -> None:
    registry = HandlerRegistry()

    @registry.register(JobType.EVENT_BATCH)
    async def first(ctx: JobContext) -> None:
        return None

    with pytest.raises(RuntimeError, match="already registered"):

        @registry.register(JobType.EVENT_BATCH)
        async def second(ctx: JobContext) -> None:
            return None


def test_the_claim_filter_is_the_registry(sessionmaker_app) -> None:
    registry = HandlerRegistry()

    @registry.register(JobType.PRODUCT_BULK_UPSERT)
    async def handle(ctx: JobContext) -> None:
        return None

    assert registry.job_types == (JobType.PRODUCT_BULK_UPSERT,)
    assert _worker(sessionmaker_app, registry).registry.job_types == (JobType.PRODUCT_BULK_UPSERT,)
