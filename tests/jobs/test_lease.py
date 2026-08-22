"""Leases: heartbeats, expiry, and the killed worker.

BUILD_PROMPT's second named exit criterion: *"a killed worker's job requeues
automatically"*. A process that is killed cannot report that it was killed, so
the lease is the only evidence available — its lapse is the death certificate.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa

from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.queue import JobLeaseLost, JobQueue
from graphrec.jobs.states import JobType, QueueStatus

pytestmark = [pytest.mark.db]

TYPES = (JobType.EVENT_BATCH,)


def _queue(owner: str, *, lease_seconds: int = 120, max_attempts: int = 3) -> JobQueue:
    return JobQueue(lease_seconds=lease_seconds, max_attempts=max_attempts, owner=owner)


async def _enqueue_and_claim(sessionmaker, tenant_id, owner="worker-a", **kwargs):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, tenant_id)
        await _queue("seed", **kwargs).enqueue(
            session, tenant_id=tenant_id, job_type=JobType.EVENT_BATCH
        )
    async with sessionmaker() as session, session.begin():
        ticket = await _queue(owner, **kwargs).claim(session, job_types=TYPES)
    assert ticket is not None
    return ticket


async def _row(sessionmaker, ticket):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        return (
            await session.execute(
                sa.text(
                    "SELECT status, attempt, lease_owner, lease_expires_at, run_after, "
                    "failure_code, failure_reason, completed_at FROM jobs WHERE job_id = :j"
                ),
                {"j": ticket.job_id},
            )
        ).one()


async def _expire_lease(sessionmaker, ticket) -> None:
    """Age the lease into the past. Simulates a worker that stopped renewing."""
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        await session.execute(
            sa.text(
                "UPDATE jobs SET lease_expires_at = now() - interval '1 minute' "
                "WHERE job_id = :j"
            ),
            {"j": ticket.job_id},
        )


# ------------------------------------------------------------------ heartbeat


async def test_a_heartbeat_pushes_the_lease_out(sessionmaker_app, queue_tenants) -> None:
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    before = (await _row(sessionmaker_app, ticket)).lease_expires_at

    await asyncio.sleep(0.05)
    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        await _queue("worker-a").heartbeat(session, job_id=ticket.job_id)

    assert (await _row(sessionmaker_app, ticket)).lease_expires_at > before


async def test_a_stranger_cannot_renew_a_lease(sessionmaker_app, queue_tenants) -> None:
    """The guard is `lease_owner`, and it is what tells a replaced worker to stop.

    A worker that was swept while it was busy discovers it here — at the
    heartbeat — rather than at the point where it would have written a result
    over its successor's.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])

    async with sessionmaker_app() as session:
        await session.begin()
        await bind_tenant(session, ticket.tenant_id)
        with pytest.raises(JobLeaseLost):
            await _queue("worker-b").heartbeat(session, job_id=ticket.job_id)
        await session.rollback()


async def test_progress_is_published_with_the_lease(sessionmaker_app, queue_tenants) -> None:
    """One statement, because they are one event: alive, and this far along."""
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        await _queue("worker-a").report_progress(
            session, job_id=ticket.job_id, progress={"stage": "building_graph"}
        )

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        progress = await session.scalar(
            sa.text("SELECT progress FROM jobs WHERE job_id = :j"), {"j": ticket.job_id}
        )
    assert progress == {"stage": "building_graph"}


# -------------------------------------------------------------------- expiry


async def test_a_killed_workers_job_requeues_automatically(sessionmaker_app, queue_tenants) -> None:
    """BUILD_PROMPT's second exit criterion for this phase.

    Nobody tells the queue the worker died. The lease simply stops being
    renewed, the sweep notices, and the job goes back — with one attempt spent,
    because a job that kills its worker is a job that may well kill the next one
    and the attempt cap is what stops that becoming a loop.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _expire_lease(sessionmaker_app, ticket)

    swept = await _queue("sweeper").sweep_expired(sessionmaker_app)
    assert swept == 1

    row = await _row(sessionmaker_app, ticket)
    assert row.status == QueueStatus.QUEUED.value
    assert row.lease_owner is None
    assert row.lease_expires_at is None
    assert row.attempt == 1
    assert row.completed_at is None
    assert row.failure_code is None, "a queued job has not failed; it is waiting"


async def test_a_requeued_job_is_claimable_by_another_worker(
    sessionmaker_app, queue_tenants
) -> None:
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _expire_lease(sessionmaker_app, ticket)
    await _queue("sweeper").sweep_expired(sessionmaker_app)

    # The backoff is in the future, so the job is not instantly re-claimable.
    assert (await _row(sessionmaker_app, ticket)).run_after is not None
    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        await session.execute(
            sa.text("UPDATE jobs SET run_after = now() WHERE job_id = :j"), {"j": ticket.job_id}
        )

    async with sessionmaker_app() as session, session.begin():
        retaken = await _queue("worker-b").claim(session, job_types=TYPES)
    assert retaken is not None
    assert retaken.job_id == ticket.job_id


async def test_the_replaced_worker_cannot_write_its_result(sessionmaker_app, queue_tenants) -> None:
    """The most dangerous case the lease guard exists for.

    A worker that was declared dead but was merely slow finishes its work and
    tries to report success. By then somebody else owns the job. Accepting the
    write would mark a job succeeded on the strength of a run the queue had
    already abandoned, and silently discard the successor's.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"], owner="worker-a")
    await _expire_lease(sessionmaker_app, ticket)
    await _queue("sweeper").sweep_expired(sessionmaker_app)

    async with sessionmaker_app() as session:
        await session.begin()
        await bind_tenant(session, ticket.tenant_id)
        with pytest.raises(JobLeaseLost):
            await _queue("worker-a").succeed(session, job_id=ticket.job_id)
        await session.rollback()


async def test_a_live_lease_is_left_alone(sessionmaker_app, queue_tenants) -> None:
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])

    assert await _queue("sweeper").sweep_expired(sessionmaker_app) == 0
    assert (await _row(sessionmaker_app, ticket)).status == QueueStatus.RUNNING.value


async def test_two_sweepers_requeue_a_job_once(sessionmaker_app, queue_tenants) -> None:
    """Every worker sweeps; there is no leader to elect and none to lose.

    That is only safe because the requeue re-checks its own precondition under a
    row lock, so several sweepers racing produce one requeue and one spent
    attempt rather than three.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _expire_lease(sessionmaker_app, ticket)

    results = await asyncio.gather(
        *(_queue(f"sweeper-{n}").sweep_expired(sessionmaker_app) for n in range(3))
    )

    assert sum(results) == 1, f"the job was requeued more than once: {results}"
    assert (await _row(sessionmaker_app, ticket)).attempt == 1


async def test_repeated_expiry_eventually_gives_up(sessionmaker_app, queue_tenants) -> None:
    """A job that keeps killing workers stops being retried.

    The terminal reason is `job_interrupted` rather than `job_attempts_exhausted`
    because the distinction is the operator's: the job never failed on its own
    terms, it was lost with the process running it, and that points at
    infrastructure rather than at the payload.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"], max_attempts=2)

    for _ in range(2):
        await _expire_lease(sessionmaker_app, ticket)
        await _queue("sweeper").sweep_expired(sessionmaker_app)
        async with sessionmaker_app() as session, session.begin():
            await bind_tenant(session, ticket.tenant_id)
            await session.execute(
                sa.text("UPDATE jobs SET run_after = now() WHERE job_id = :j"),
                {"j": ticket.job_id},
            )
        async with sessionmaker_app() as session, session.begin():
            await _queue("worker-b", max_attempts=2).claim(session, job_types=TYPES)

    row = await _row(sessionmaker_app, ticket)
    assert row.status == QueueStatus.FAILED.value
    assert row.attempt == 2
    assert row.failure_code == "job_interrupted"
    assert row.completed_at is not None
    assert (
        row.failure_reason
        == "The worker running this job stopped responding, and no attempts remain."
    )


async def test_the_expiry_scan_returns_only_identifiers(sessionmaker_app, queue_tenants) -> None:
    """The same rule as the claim: which job, never what job."""
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _expire_lease(sessionmaker_app, ticket)

    async with sessionmaker_app() as session, session.begin():
        row = (
            (await session.execute(sa.text("SELECT * FROM job_queue.expired_leases(10)")))
            .mappings()
            .one()
        )

    assert set(row) == {"expired_job_id", "expired_tenant_id"}
