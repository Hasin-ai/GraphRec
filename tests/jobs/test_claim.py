"""Claiming: disjointness, fair sharing, and where the tenant comes from.

BUILD_PROMPT's first named exit criterion for this phase is *"two workers claim
disjoint jobs"*. That is the property `FOR UPDATE … SKIP LOCKED` exists to
provide, and it is the one that fails silently if it fails at all: a queue that
hands the same job to two workers does not error, it does the work twice.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.queue import JobQueue
from graphrec.jobs.states import JobType, QueueStatus

pytestmark = [pytest.mark.db, pytest.mark.isolation]

TYPES = (JobType.EVENT_BATCH,)


def _queue(owner: str, *, lease_seconds: int = 120, max_attempts: int = 3) -> JobQueue:
    return JobQueue(lease_seconds=lease_seconds, max_attempts=max_attempts, owner=owner)


async def _enqueue(sessionmaker, tenant_id, *, count=1, priority=5, job_type=JobType.EVENT_BATCH):
    created = []
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, tenant_id)
        queue = _queue("seed")
        for index in range(count):
            job = await queue.enqueue(
                session,
                tenant_id=tenant_id,
                job_type=job_type,
                payload={"index": index},
                priority=priority,
            )
            created.append(job.job_id)
    return created


async def _claim(sessionmaker, owner: str):
    async with sessionmaker() as session, session.begin():
        return await _queue(owner).claim(session, job_types=TYPES)


# ------------------------------------------------------------------ the basics


async def test_a_claim_returns_the_job_and_its_tenant(sessionmaker_app, queue_tenants) -> None:
    [job_id] = await _enqueue(sessionmaker_app, queue_tenants["alpha"])

    ticket = await _claim(sessionmaker_app, "worker-a")

    assert ticket is not None
    assert ticket.job_id == job_id
    assert ticket.tenant_id == queue_tenants["alpha"]


async def test_an_empty_queue_yields_nothing_rather_than_blocking(
    sessionmaker_app, queue_tenants
) -> None:
    assert await _claim(sessionmaker_app, "worker-a") is None


async def test_a_claim_returns_only_identifiers(sessionmaker_app, queue_tenants) -> None:
    """The claim answers *which* job, never *what* job.

    The payload is tenant data. It crosses into the worker one statement later,
    read under that tenant's own policy — so the cross-tenant function never
    handles it, and cannot be made to leak it.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])

    async with sessionmaker_app() as session, session.begin():
        row = (
            (
                await session.execute(
                    sa.text("SELECT * FROM job_queue.claim('w', ARRAY['event_batch'], 120)")
                )
            )
            .mappings()
            .one()
        )

    assert set(row) == {"claimed_job_id", "claimed_tenant_id"}


async def test_a_claimed_job_is_running_and_leased(sessionmaker_app, queue_tenants) -> None:
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    ticket = await _claim(sessionmaker_app, "worker-a")
    assert ticket is not None

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        row = (
            await session.execute(
                sa.text(
                    "SELECT status, lease_owner, lease_expires_at, started_at, attempt "
                    "FROM jobs WHERE job_id = :j"
                ),
                {"j": ticket.job_id},
            )
        ).one()

    assert row.status == QueueStatus.RUNNING.value
    assert row.lease_owner == "worker-a"
    assert row.lease_expires_at is not None
    assert row.started_at is not None
    assert row.attempt == 0, "claiming is not an attempt; only failing is"


async def test_a_job_scheduled_for_later_is_not_claimed(sessionmaker_app, queue_tenants) -> None:
    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, queue_tenants["alpha"])
        await session.execute(
            sa.text(
                "INSERT INTO jobs (job_id, tenant_id, job_type, run_after) "
                "VALUES (:j, :t, 'event_batch', now() + interval '1 hour')"
            ),
            {"j": uuid.uuid4(), "t": queue_tenants["alpha"]},
        )

    assert await _claim(sessionmaker_app, "worker-a") is None


async def test_a_worker_does_not_claim_a_type_it_cannot_run(
    sessionmaker_app, queue_tenants
) -> None:
    """The claim filter is derived from the handler registry.

    A worker that leased a job it has no handler for would fail it and spend the
    tenant's attempts on the deployment's mistake.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"], job_type=JobType.TRAINING)

    async with sessionmaker_app() as session, session.begin():
        assert await _queue("worker-a").claim(session, job_types=(JobType.EVENT_BATCH,)) is None
        assert await _queue("worker-a").claim(session, job_types=(JobType.TRAINING,)) is not None


# ------------------------------------------------------------- disjointness


async def test_two_workers_claim_disjoint_jobs(sessionmaker_app, queue_tenants) -> None:
    """BUILD_PROMPT's first exit criterion for this phase.

    Two claims running at the same instant against one queued job: exactly one
    of them gets it, and the other is told there is nothing rather than being
    made to wait for a lock it will lose anyway. That second half is what
    `SKIP LOCKED` adds over an ordinary `FOR UPDATE`.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"], count=6)

    tickets = await asyncio.gather(*(_claim(sessionmaker_app, f"worker-{n}") for n in range(6)))

    claimed = [t.job_id for t in tickets if t is not None]
    assert len(claimed) == 6, "every queued job should have gone to some worker"
    assert len(set(claimed)) == 6, f"a job was claimed twice: {claimed}"


async def test_a_running_job_is_not_claimed_again(sessionmaker_app, queue_tenants) -> None:
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])

    first = await _claim(sessionmaker_app, "worker-a")
    second = await _claim(sessionmaker_app, "worker-b")

    assert first is not None
    assert second is None, "a leased job must not be claimable until its lease lapses"


async def test_a_concurrent_claim_does_not_block(sessionmaker_app, queue_tenants) -> None:
    """Two open transactions, one job, and neither waits on the other.

    The first holds a row lock for the length of its transaction. Without
    `SKIP LOCKED` the second would block on it; with it, the second is told the
    queue is empty immediately. The timeout is the assertion.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])

    async with sessionmaker_app() as held, held.begin():
        first = await _queue("worker-a").claim(held, job_types=TYPES)
        assert first is not None

        # Still inside the first transaction: the row is locked and uncommitted.
        async with sessionmaker_app() as other, other.begin():
            second = await asyncio.wait_for(
                _queue("worker-b").claim(other, job_types=TYPES), timeout=5
            )
        assert second is None


# --------------------------------------------------------------- fair sharing


async def test_one_tenants_backlog_does_not_starve_another(sessionmaker_app, queue_tenants) -> None:
    """The reason the claim carries a window function.

    Alpha enqueues a deep backlog; beta enqueues one job afterwards. Ordering by
    arrival alone would put beta behind all of it. Round-robin by tenant puts
    beta's only job second — behind alpha's first, ahead of alpha's rest.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"], count=5)
    await _enqueue(sessionmaker_app, queue_tenants["beta"], count=1)

    order = []
    for n in range(6):
        ticket = await _claim(sessionmaker_app, f"worker-{n}")
        assert ticket is not None
        order.append(ticket.tenant_id)

    assert order[0] == queue_tenants["alpha"]
    assert order[1] == queue_tenants["beta"], f"beta waited behind alpha's backlog: {order}"
    assert order[2:] == [queue_tenants["alpha"]] * 4


async def test_priority_orders_a_tenants_own_work(sessionmaker_app, queue_tenants) -> None:
    """Priority ranks a tenant against itself, never against another tenant.

    Otherwise every tenant would set priority 9 on everything and the field
    would mean nothing, except for the tenant who had not noticed yet.
    """
    [low] = await _enqueue(sessionmaker_app, queue_tenants["alpha"], priority=2)
    [high] = await _enqueue(sessionmaker_app, queue_tenants["alpha"], priority=8)

    first = await _claim(sessionmaker_app, "worker-a")
    second = await _claim(sessionmaker_app, "worker-b")

    assert first is not None
    assert second is not None
    assert first.job_id == high
    assert second.job_id == low


async def test_a_high_priority_job_does_not_jump_another_tenants_queue(
    sessionmaker_app, queue_tenants
) -> None:
    await _enqueue(sessionmaker_app, queue_tenants["alpha"], count=2, priority=9)
    await _enqueue(sessionmaker_app, queue_tenants["beta"], count=1, priority=1)

    order = [
        (await _claim(sessionmaker_app, f"worker-{n}")).tenant_id  # type: ignore[union-attr]
        for n in range(3)
    ]

    assert (
        order[1] == queue_tenants["beta"]
    ), "priority 9 bought alpha a second slot ahead of beta's first"


# ---------------------------------------------------------------- isolation


async def test_a_worker_cannot_read_the_queue_without_claiming(
    sessionmaker_app, queue_tenants
) -> None:
    """The worker role holds no cross-tenant read of its own.

    An unbound `SELECT` on `jobs` returns nothing, which is the whole reason the
    claim has to be a `SECURITY DEFINER` function rather than a query.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])

    async with sessionmaker_app() as session, session.begin():
        assert (await session.execute(sa.text("SELECT job_id FROM jobs"))).all() == []


async def test_a_claimed_job_is_invisible_to_another_tenants_context(
    sessionmaker_app, queue_tenants
) -> None:
    """Gate 4, at the queue.

    The claim names a tenant, and binding a *different* one does not make the
    job readable. If it did, a worker with a bug in its binding would be a
    cross-tenant reader.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    ticket = await _claim(sessionmaker_app, "worker-a")
    assert ticket is not None

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, queue_tenants["beta"])
        found = (
            await session.execute(
                sa.text("SELECT job_id FROM jobs WHERE job_id = :j"), {"j": ticket.job_id}
            )
        ).all()
    assert found == []


async def test_a_job_cannot_be_enqueued_against_another_tenant(
    sessionmaker_app, queue_tenants
) -> None:
    """`WITH CHECK` refuses it; the argument is not trusted to be right."""
    async with sessionmaker_app() as session:
        await session.begin()
        await bind_tenant(session, queue_tenants["alpha"])
        with pytest.raises(sa.exc.ProgrammingError) as caught:
            await _queue("seed").enqueue(
                session, tenant_id=queue_tenants["beta"], job_type=JobType.EVENT_BATCH
            )
        await session.rollback()
    assert "row-level security" in str(caught.value).lower()


async def test_no_role_may_delete_a_job(sessionmaker_app, queue_tenants) -> None:
    """A job that ran is what the console's submission history is made of.

    A queue you can delete from is a queue whose failures can be made to
    disappear.
    """
    await _enqueue(sessionmaker_app, queue_tenants["alpha"])
    async with sessionmaker_app() as session:
        await session.begin()
        await bind_tenant(session, queue_tenants["alpha"])
        with pytest.raises(sa.exc.ProgrammingError) as caught:
            await session.execute(sa.text("DELETE FROM jobs"))
        await session.rollback()
    assert "permission denied" in str(caught.value).lower()
