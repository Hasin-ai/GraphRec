"""Retries: what spends an attempt, and what does not.

BUILD_PROMPT's third named exit criterion: *"a deterministic failure consumes no
attempts"*. `attempt` counts the retry budget **consumed**, so claiming spends
nothing and a permanent failure spends nothing. Only a decision to try again
does.

That is a stronger claim than "the job stops after a permanent failure". A
malformed CSV should leave the tenant's budget exactly as it found it, because
the budget exists to bound *retrying* and nothing was retried.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from graphrec.common.errors import ConflictError, UnavailableError, ValidationError
from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.failures import (
    BACKOFF_CAP_SECONDS,
    PermanentJobError,
    Retryability,
    backoff_seconds,
    classify,
)
from graphrec.jobs.queue import JobQueue
from graphrec.jobs.states import JobType, QueueStatus

pytestmark = [pytest.mark.db]

TYPES = (JobType.EVENT_BATCH,)


def _queue(owner: str, *, max_attempts: int = 3) -> JobQueue:
    return JobQueue(lease_seconds=120, max_attempts=max_attempts, owner=owner)


async def _enqueue_and_claim(sessionmaker, tenant_id, *, owner="worker-a", max_attempts=3):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, tenant_id)
        await _queue("seed", max_attempts=max_attempts).enqueue(
            session, tenant_id=tenant_id, job_type=JobType.EVENT_BATCH
        )
    async with sessionmaker() as session, session.begin():
        ticket = await _queue(owner, max_attempts=max_attempts).claim(session, job_types=TYPES)
    assert ticket is not None
    return ticket


async def _fail(sessionmaker, ticket, exc, *, owner="worker-a", max_attempts=3):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        return await _queue(owner, max_attempts=max_attempts).fail(
            session, job_id=ticket.job_id, verdict=classify(exc)
        )


async def _row(sessionmaker, ticket):
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        return (
            await session.execute(
                sa.text(
                    "SELECT status, attempt, failure_code, failure_reason, run_after, "
                    "completed_at, lease_owner FROM jobs WHERE job_id = :j"
                ),
                {"j": ticket.job_id},
            )
        ).one()


# ------------------------------------------------------------- the classifier


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PermanentJobError("job_failed"), Retryability.PERMANENT),
        (ValidationError("invalid_request"), Retryability.PERMANENT),
        (ConflictError("conflict"), Retryability.PERMANENT),
        (UnavailableError("service_unavailable"), Retryability.RETRYABLE),
        (TimeoutError(), Retryability.RETRYABLE),
        (ConnectionResetError(), Retryability.RETRYABLE),
        (OSError("disk"), Retryability.RETRYABLE),
        (RuntimeError("who knows"), Retryability.RETRYABLE),
    ],
)
def test_the_classifier_reads_the_flag_the_api_already_carries(exc, expected) -> None:
    """`GraphRecError.retryable` has existed since Phase 1 and answers this.

    A worker asking "should I try again?" is asking the same question the API
    answers for a client, of the same exception. A second taxonomy invented for
    workers would drift the first time somebody set one flag and not the other.
    """
    assert classify(exc).retryability is expected


def test_an_unknown_exception_is_retried_rather_than_dropped() -> None:
    """The less damaging of two wrong answers.

    Retrying a genuinely deterministic bug wastes at most `max_attempts` runs
    and then stops. Refusing to retry a transient one silently loses a tenant's
    ingestion. The attempt cap is what makes the optimistic default safe.
    """
    verdict = classify(RuntimeError("unclassified"))
    assert verdict.should_retry
    assert verdict.code == "job_failed"


def test_a_permanent_failure_carries_its_own_code() -> None:
    verdict = classify(PermanentJobError("training_insufficient_data", minimum=1000))
    assert verdict.code == "training_insufficient_data"
    assert verdict.copy_args == {"minimum": 1000}


def test_a_database_operational_error_is_retryable() -> None:
    assert classify(OperationalError("SELECT 1", {}, Exception())).should_retry


def test_backoff_grows_and_is_capped() -> None:
    values = [backoff_seconds(n) for n in range(12)]
    assert values == sorted(values)
    assert max(values) == BACKOFF_CAP_SECONDS
    assert backoff_seconds(0) > 0


# --------------------------------------------------- a deterministic failure


async def test_a_deterministic_failure_consumes_no_attempts(
    sessionmaker_app, queue_tenants
) -> None:
    """BUILD_PROMPT's third exit criterion for this phase."""
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])

    status = await _fail(sessionmaker_app, ticket, PermanentJobError("job_failed"))

    assert status is QueueStatus.FAILED
    row = await _row(sessionmaker_app, ticket)
    assert row.attempt == 0, "a failure nobody retried spent none of the retry budget"
    assert row.status == QueueStatus.FAILED.value
    assert row.completed_at is not None
    assert row.lease_owner is None


async def test_a_deterministically_failed_job_is_not_reclaimed(
    sessionmaker_app, queue_tenants
) -> None:
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _fail(sessionmaker_app, ticket, ValidationError("invalid_request"))

    async with sessionmaker_app() as session, session.begin():
        assert await _queue("worker-b").claim(session, job_types=TYPES) is None


async def test_the_failure_reason_is_approved_copy_not_an_exception_message(
    sessionmaker_app, queue_tenants
) -> None:
    """NR-NF-06, at the one place a worker's internals could reach a tenant.

    A traceback out of an ingestion handler can carry a row of somebody's data
    in it. What is stored is a catalogue code and the sentence it resolves to,
    so there is no path by which `str(exc)` becomes console text.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    secret = "customer-4471@private.example paid 240.00"

    await _fail(sessionmaker_app, ticket, PermanentJobError("job_failed"))

    row = await _row(sessionmaker_app, ticket)
    assert row.failure_code == "job_failed"
    assert row.failure_reason == "The job stopped before completing. No partial result was kept."
    assert secret not in (row.failure_reason or "")


# -------------------------------------------------------- a transient failure


async def test_a_transient_failure_spends_one_attempt_and_requeues(
    sessionmaker_app, queue_tenants
) -> None:
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])

    status = await _fail(sessionmaker_app, ticket, UnavailableError("service_unavailable"))

    assert status is QueueStatus.QUEUED
    row = await _row(sessionmaker_app, ticket)
    assert row.attempt == 1
    assert row.status == QueueStatus.QUEUED.value
    assert row.completed_at is None
    assert row.failure_code is None, "a job waiting to run again has not failed"


async def test_the_retry_waits_behind_a_backoff(sessionmaker_app, queue_tenants) -> None:
    """Immediately re-claimable would mean spinning the whole budget in
    milliseconds against a dependency that needs a moment."""
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _fail(sessionmaker_app, ticket, UnavailableError("service_unavailable"))

    async with sessionmaker_app() as session, session.begin():
        assert await _queue("worker-b").claim(session, job_types=TYPES) is None


async def test_the_last_attempt_gives_up_and_says_how_many(sessionmaker_app, queue_tenants) -> None:
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"], max_attempts=1)

    status = await _fail(
        sessionmaker_app, ticket, UnavailableError("service_unavailable"), max_attempts=1
    )

    assert status is QueueStatus.FAILED
    row = await _row(sessionmaker_app, ticket)
    assert row.attempt == 1
    assert row.failure_code == "job_attempts_exhausted"
    assert "1 attempts" in row.failure_reason


async def test_attempts_accumulate_across_claims(sessionmaker_app, queue_tenants) -> None:
    """The budget is the job's, not the worker's. A new worker inherits it."""
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"], max_attempts=3)
    await _fail(sessionmaker_app, ticket, UnavailableError("service_unavailable"))

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        await session.execute(
            sa.text("UPDATE jobs SET run_after = now() WHERE job_id = :j"), {"j": ticket.job_id}
        )
    async with sessionmaker_app() as session, session.begin():
        retaken = await _queue("worker-b").claim(session, job_types=TYPES)
    assert retaken is not None

    await _fail(
        sessionmaker_app, retaken, UnavailableError("service_unavailable"), owner="worker-b"
    )
    assert (await _row(sessionmaker_app, ticket)).attempt == 2


async def test_a_permanent_failure_after_a_retry_leaves_the_spent_attempts_alone(
    sessionmaker_app, queue_tenants
) -> None:
    """It spends none of its own — but it does not refund the ones already spent.

    `attempt` is a record of what happened, not a running judgement about the
    job.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])
    await _fail(sessionmaker_app, ticket, UnavailableError("service_unavailable"))

    async with sessionmaker_app() as session, session.begin():
        await bind_tenant(session, ticket.tenant_id)
        await session.execute(
            sa.text("UPDATE jobs SET run_after = now() WHERE job_id = :j"), {"j": ticket.job_id}
        )
    async with sessionmaker_app() as session, session.begin():
        retaken = await _queue("worker-b").claim(session, job_types=TYPES)
    assert retaken is not None
    await _fail(sessionmaker_app, retaken, ValidationError("invalid_request"), owner="worker-b")

    row = await _row(sessionmaker_app, ticket)
    assert row.attempt == 1
    assert row.status == QueueStatus.FAILED.value


async def test_two_failures_do_not_race_the_attempt_counter(
    sessionmaker_app, queue_tenants
) -> None:
    """Only the lease holder may record an outcome, so there is nothing to race.

    A second reporter is refused by the guard rather than incrementing the
    counter a second time.
    """
    ticket = await _enqueue_and_claim(sessionmaker_app, queue_tenants["alpha"])

    results = await asyncio.gather(
        _fail(sessionmaker_app, ticket, UnavailableError("service_unavailable")),
        _fail(sessionmaker_app, ticket, UnavailableError("service_unavailable")),
        return_exceptions=True,
    )

    assert sum(1 for r in results if isinstance(r, QueueStatus)) == 1
    assert (await _row(sessionmaker_app, ticket)).attempt == 1
