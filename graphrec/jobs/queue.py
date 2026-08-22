"""The queue client: enqueue, claim, lease, finish.

Two kinds of session appear here and the difference is the security boundary.

`claim` and `sweep_expired` take an **unbound** session. They are the only
methods that do, they run cross-tenant by necessity, and each reaches the
database through a `SECURITY DEFINER` function that returns identifiers and
nothing else (migration 0006, ADR 0008, ADR 0011).

Everything else takes a session already bound to the job's tenant, and runs
under the ordinary tenant policy. A worker binds the tenant the claim named and
from that point is indistinguishable from a request handler: it cannot read a
foreign row, and an `UPDATE` naming a foreign `tenant_id` is refused by
`WITH CHECK`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa
from sqlalchemy import CursorResult, Text
from sqlalchemy.dialects.postgresql import ARRAY

from graphrec.common.error_copy import resolve_copy
from graphrec.common.errors import ConflictError, NotFoundError
from graphrec.common.ids import uuid7
from graphrec.common.logging import get_logger
from graphrec.db.models.jobs import Job
from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.failures import Verdict, backoff_seconds
from graphrec.jobs.states import JobType, QueueStatus

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


class JobLeaseLost(Exception):  # noqa: N818 - a race outcome, not a fault
    """The worker no longer holds the lease it is trying to act on.

    Raised when a write guarded by `lease_owner = :owner` matches no row. The
    job has been swept and reclaimed by somebody else, and this worker's result
    is stale — writing it would overwrite the successor's work with the output
    of a run the queue has already given up on.
    """


@dataclass(frozen=True, slots=True)
class ClaimTicket:
    """What a claim returns: which job, and whose.

    Two identifiers. Not the payload — the worker reads that under the tenant's
    own policy, one statement later.
    """

    job_id: uuid.UUID
    tenant_id: uuid.UUID


class JobQueue:
    def __init__(
        self,
        *,
        lease_seconds: int,
        max_attempts: int,
        owner: str,
    ) -> None:
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        #: Identifies this worker in `lease_owner`. Free text, and never
        #: authoritative for anything but the guard on the worker's own writes.
        self.owner = owner

    # ------------------------------------------------------------- enqueueing

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        job_type: JobType,
        payload: dict[str, Any] | None = None,
        priority: int = 5,
        max_attempts: int | None = None,
        run_after: dt.datetime | None = None,
    ) -> Job:
        """Insert a queued job. `session` must already be bound to `tenant_id`.

        The `tenant_id` argument is not trusted to be right: the policy's
        `WITH CHECK` compares it against the bound context and refuses the
        insert if they differ. Passing a foreign tenant here fails loudly rather
        than quietly enqueueing work against somebody else's account.
        """
        job = Job(
            job_id=uuid7(),
            tenant_id=tenant_id,
            job_type=job_type.value,
            status=QueueStatus.QUEUED.value,
            priority=priority,
            attempt=0,
            max_attempts=max_attempts or self.max_attempts,
            run_after=run_after or dt.datetime.now(dt.UTC),
            payload=payload or {},
            progress={},
        )
        session.add(job)
        await session.flush()
        return job

    # ---------------------------------------------------------------- claiming

    async def claim(
        self, session: AsyncSession, *, job_types: Sequence[JobType]
    ) -> ClaimTicket | None:
        """Take the next eligible job, or return None if there is none.

        `session` is deliberately unbound. A worker serves every tenant and
        cannot know whose job it will get until it has got it, so it cannot bind
        a context beforehand — the claim is the thing that produces the answer.

        The whole of the concurrency argument lives in the function this calls:
        `FOR UPDATE … SKIP LOCKED` means a row another transaction has locked is
        passed over rather than waited on, so two workers running this at the
        same instant take two different jobs and neither blocks.
        """
        row = (
            await session.execute(
                sa.text(
                    "SELECT claimed_job_id, claimed_tenant_id "
                    "FROM job_queue.claim(:owner, :types, :lease)"
                ).bindparams(
                    sa.bindparam("owner", value=self.owner, type_=Text),
                    sa.bindparam("types", value=[t.value for t in job_types], type_=ARRAY(Text)),
                    sa.bindparam("lease", value=self.lease_seconds),
                )
            )
        ).first()
        if row is None:
            return None
        return ClaimTicket(job_id=row[0], tenant_id=row[1])

    async def load(self, session: AsyncSession, *, job_id: uuid.UUID) -> Job:
        """Read the claimed job under its tenant's policy.

        A foreign `job_id` is invisible here rather than forbidden, so this
        raises `NotFoundError` — gate 4, and the reason it is a 404 is that a
        403 would confirm the job exists somewhere.
        """
        job = await session.get(Job, job_id)
        if job is None:
            raise NotFoundError("not_found")
        return job

    # ------------------------------------------------------------------ leases

    async def heartbeat(self, session: AsyncSession, *, job_id: uuid.UUID) -> None:
        """Push the lease out by another `lease_seconds`.

        Guarded on `lease_owner`. A worker that was swept while it was busy —
        because it stalled, or its clock and the database's disagreed — finds
        the guard matches nothing and learns it has been replaced. That is the
        point at which it must stop, not the point at which it writes a result.
        """
        result = await session.execute(
            sa.text(
                "UPDATE jobs SET lease_expires_at = now() + make_interval(secs => :lease), "
                "updated_at = now() "
                "WHERE job_id = :job_id AND lease_owner = :owner AND status = 'running'"
            ),
            {"lease": self.lease_seconds, "job_id": job_id, "owner": self.owner},
        )
        if cast("CursorResult[Any]", result).rowcount != 1:
            raise JobLeaseLost(str(job_id))

    async def report_progress(
        self, session: AsyncSession, *, job_id: uuid.UUID, progress: dict[str, Any]
    ) -> None:
        """Record stage progress and refresh the lease in one statement.

        One statement because a heartbeat and a progress update are the same
        event: the worker is alive and has got this far.
        """
        result = await session.execute(
            sa.text(
                "UPDATE jobs SET progress = CAST(:progress AS jsonb), "
                "lease_expires_at = now() + make_interval(secs => :lease), updated_at = now() "
                "WHERE job_id = :job_id AND lease_owner = :owner AND status = 'running'"
            ).bindparams(sa.bindparam("progress", value=progress, type_=sa.JSON)),
            {"lease": self.lease_seconds, "job_id": job_id, "owner": self.owner},
        )
        if cast("CursorResult[Any]", result).rowcount != 1:
            raise JobLeaseLost(str(job_id))

    async def cancellation_requested(self, session: AsyncSession, *, job_id: uuid.UUID) -> bool:
        """Whether a cancellation has been asked for since the job was claimed.

        Read at stage boundaries. Cheap: a single indexed row, and the queue is
        tens of jobs a day (ASM-03), so polling it costs nothing worth saving.
        """
        return bool(
            await session.scalar(
                sa.text("SELECT cancel_requested_at IS NOT NULL FROM jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        )

    # -------------------------------------------------------------- finishing

    async def _finish(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        status: QueueStatus,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        progress: dict[str, Any] | None = None,
    ) -> None:
        result = await session.execute(
            sa.text(
                "UPDATE jobs SET status = :status, completed_at = now(), updated_at = now(), "
                "lease_owner = NULL, lease_expires_at = NULL, "
                "failure_code = :failure_code, failure_reason = :failure_reason, "
                "progress = COALESCE(CAST(:progress AS jsonb), progress) "
                "WHERE job_id = :job_id AND lease_owner = :owner AND status = 'running'"
            ).bindparams(sa.bindparam("progress", value=progress, type_=sa.JSON)),
            {
                "status": status.value,
                "failure_code": failure_code,
                "failure_reason": failure_reason,
                "job_id": job_id,
                "owner": self.owner,
            },
        )
        if cast("CursorResult[Any]", result).rowcount != 1:
            raise JobLeaseLost(str(job_id))

    async def succeed(
        self, session: AsyncSession, *, job_id: uuid.UUID, progress: dict[str, Any] | None = None
    ) -> None:
        await self._finish(session, job_id=job_id, status=QueueStatus.SUCCEEDED, progress=progress)

    async def finish_cancelled(
        self, session: AsyncSession, *, job_id: uuid.UUID, stage: str | None
    ) -> None:
        """Settle a job the worker stopped at a boundary.

        BACKEND_PLAN §195: the terminal *stage* is persisted, not just the
        terminal status, because the console renders "Cancelled at
        building_graph." (dc.html L1707) and cannot reconstruct that from
        `cancelled` alone.
        """
        await self._finish(
            session,
            job_id=job_id,
            status=QueueStatus.CANCELLED,
            failure_code="job_cancelled",
            failure_reason=resolve_copy("job_cancelled"),
            progress={"stage_at": stage} if stage else None,
        )

    async def fail(
        self, session: AsyncSession, *, job_id: uuid.UUID, verdict: Verdict
    ) -> QueueStatus:
        """Apply the retry policy, and return where the job ended up.

        A **permanent** failure terminates immediately and spends nothing. That
        is what makes BUILD_PROMPT's "a deterministic failure consumes no
        attempts" literally true rather than approximately: `attempt` is not
        touched on this path at all, so a malformed payload is refused once and
        the tenant's remaining budget is exactly what it was.

        A **retryable** failure spends one attempt and either re-queues behind a
        backoff or, if that was the last one, gives up.
        """
        if not verdict.should_retry:
            await self._finish(
                session,
                job_id=job_id,
                status=QueueStatus.FAILED,
                failure_code=verdict.code,
                failure_reason=resolve_copy(verdict.code, **verdict.copy_args),
            )
            return QueueStatus.FAILED

        job = await self.load(session, job_id=job_id)
        spent = job.attempt + 1

        if spent >= job.max_attempts:
            code = "job_attempts_exhausted"
            result = await session.execute(
                sa.text(
                    "UPDATE jobs SET status = 'failed', attempt = :attempt, "
                    "completed_at = now(), updated_at = now(), "
                    "lease_owner = NULL, lease_expires_at = NULL, "
                    "failure_code = :code, failure_reason = :reason "
                    "WHERE job_id = :job_id AND lease_owner = :owner AND status = 'running'"
                ),
                {
                    "attempt": spent,
                    "code": code,
                    "reason": resolve_copy(code, attempts=job.max_attempts),
                    "job_id": job_id,
                    "owner": self.owner,
                },
            )
            # Guarded like every other outcome write. Without this check the
            # retry branches would report an outcome they never recorded, and a
            # worker that had lost its lease would come away believing it had
            # spent an attempt that its successor is still holding.
            if cast("CursorResult[Any]", result).rowcount != 1:
                raise JobLeaseLost(str(job_id))
            return QueueStatus.FAILED

        result = await session.execute(
            sa.text(
                "UPDATE jobs SET status = 'queued', attempt = :attempt, "
                "run_after = now() + make_interval(secs => :backoff), updated_at = now(), "
                "lease_owner = NULL, lease_expires_at = NULL, "
                "failure_code = NULL, failure_reason = NULL "
                "WHERE job_id = :job_id AND lease_owner = :owner AND status = 'running'"
            ),
            {
                "attempt": spent,
                "backoff": backoff_seconds(spent),
                "job_id": job_id,
                "owner": self.owner,
            },
        )
        if cast("CursorResult[Any]", result).rowcount != 1:
            raise JobLeaseLost(str(job_id))
        # The failure fields are cleared, not kept: a job sitting in `queued` has
        # not failed, and a console that showed a reason next to a pending job
        # would be describing a run that is about to be superseded.
        return QueueStatus.QUEUED

    # ------------------------------------------------------------ cancellation

    async def request_cancellation(
        self, session: AsyncSession, *, job_id: uuid.UUID, reason: str
    ) -> Job:
        """Record a cancellation request. Called by the API, not by a worker.

        This does not stop anything. It moves the job to what the prototype
        calls `cancelling` (dc.html L1718) and waits for the worker to notice at
        its next stage boundary — "The job moves to cancelling and then to
        cancelled" (L1714).
        """
        job = await self.load(session, job_id=job_id)
        if job.is_terminal():
            raise ConflictError("job_not_cancellable")
        if job.cancel_requested_at is None:
            job.cancel_requested_at = dt.datetime.now(dt.UTC)
            # L1718: 'Cancelled by requester: ' + the reason typed in the dialog.
            job.cancel_reason = f"Cancelled by requester: {reason}"
            await session.flush()
        return job

    # -------------------------------------------------------- expiry sweeping

    async def sweep_expired(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        limit: int = 50,
    ) -> int:
        """Return jobs whose worker stopped renewing their lease.

        This is what makes a killed worker recoverable without anybody noticing
        it died. The lease is the liveness signal; its lapse is the only
        evidence available, because a process that was killed cannot report it.

        Two transactions per job, deliberately. The cross-tenant read finds
        candidates and yields identifiers only; the decision — spend an attempt
        and requeue, or give up — is taken in a transaction bound to the job's
        own tenant, under that tenant's own policy. A `SECURITY DEFINER` function
        that did both would be a cross-tenant writer with business logic in it.
        """
        async with sessionmaker() as session, session.begin():
            candidates = [
                ClaimTicket(job_id=row[0], tenant_id=row[1])
                for row in (
                    await session.execute(
                        sa.text(
                            "SELECT expired_job_id, expired_tenant_id "
                            "FROM job_queue.expired_leases(:limit)"
                        ),
                        {"limit": limit},
                    )
                ).all()
            ]

        swept = 0
        for ticket in candidates:
            async with sessionmaker() as session, session.begin():
                await bind_tenant(session, ticket.tenant_id)
                if await self._requeue_expired(session, job_id=ticket.job_id):
                    swept += 1
        if swept:
            logger.warning("job_leases_expired", extra={"swept": swept})
        return swept

    async def _requeue_expired(self, session: AsyncSession, *, job_id: uuid.UUID) -> bool:
        """Requeue one expired job, or report that somebody else got there first.

        `FOR UPDATE` plus the re-check of `status` and `lease_expires_at` is the
        whole of the race handling: two sweepers can see the same candidate, and
        only the one that takes the row lock first finds the condition still
        true.
        """
        row = (
            await session.execute(
                sa.text(
                    "SELECT attempt, max_attempts FROM jobs "
                    "WHERE job_id = :job_id AND status = 'running' "
                    "AND lease_expires_at < now() FOR UPDATE"
                ),
                {"job_id": job_id},
            )
        ).first()
        if row is None:
            return False

        attempt, max_attempts = row
        spent = attempt + 1

        if spent >= max_attempts:
            # Out of budget. A job whose worker keeps dying is usually a job that
            # kills workers, and repeating it forever would take the queue down
            # with it.
            code = "job_interrupted"
            await session.execute(
                sa.text(
                    "UPDATE jobs SET status = 'failed', attempt = :attempt, "
                    "completed_at = now(), updated_at = now(), "
                    "lease_owner = NULL, lease_expires_at = NULL, "
                    "failure_code = :code, failure_reason = :reason "
                    "WHERE job_id = :job_id"
                ),
                {
                    "attempt": spent,
                    "code": code,
                    "reason": resolve_copy(code),
                    "job_id": job_id,
                },
            )
            return True

        await session.execute(
            sa.text(
                "UPDATE jobs SET status = 'queued', attempt = :attempt, "
                "run_after = now() + make_interval(secs => :backoff), updated_at = now(), "
                "lease_owner = NULL, lease_expires_at = NULL "
                "WHERE job_id = :job_id"
            ),
            {"attempt": spent, "backoff": backoff_seconds(spent), "job_id": job_id},
        )
        return True


__all__ = ["ClaimTicket", "JobLeaseLost", "JobQueue"]
