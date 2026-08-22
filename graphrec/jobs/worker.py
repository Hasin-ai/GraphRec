"""The claim loop.

Shared by `job_worker` and `training_worker`, which differ only in which
handlers they register and therefore which job types they claim.

The loop's shape is dictated by one fact: **the outcome of a job cannot be
recorded in the transaction that failed.** A handler that raises because
PostgreSQL rejected a statement leaves an aborted transaction behind, and every
subsequent statement in it — including the `UPDATE` that would mark the job
failed — is refused. So the work runs in one transaction and the outcome is
written in another, opened fresh.

Success is the exception to that, and deliberately so: `succeed` runs *inside*
the handler's transaction, so a job's effects and the record that it happened
commit together or not at all. A worker killed a millisecond before that commit
leaves a `running` job with no effects, and the sweeper retries it. A worker
killed a millisecond after leaves a `succeeded` job with all of them. There is
no interval in which the two disagree.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import uuid
from typing import TYPE_CHECKING

from graphrec.common.logging import get_logger
from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.failures import JobCancelled, classify
from graphrec.jobs.handlers import JobContext
from graphrec.jobs.queue import JobLeaseLost, JobQueue
from graphrec.jobs.states import JobType

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from graphrec.common.config import Settings
    from graphrec.jobs.handlers import HandlerRegistry
    from graphrec.jobs.queue import ClaimTicket

logger = get_logger(__name__)


def worker_identity(prefix: str) -> str:
    """`job_worker@host/pid/short-uuid`.

    Host and pid make a stuck lease traceable to a process an operator can go
    and look at. The uuid suffix keeps two workers distinct after a pid is
    reused, which is the case where a lease guard would otherwise let a restarted
    process finish a job its predecessor had already lost.
    """
    return f"{prefix}@{socket.gethostname()}/{os.getpid()}/{uuid.uuid4().hex[:8]}"


class Worker:
    """One process's worth of claim loops, plus the expiry sweeper."""

    def __init__(
        self,
        *,
        name: str,
        sessionmaker: async_sessionmaker[AsyncSession],
        registry: HandlerRegistry,
        settings: Settings,
    ) -> None:
        self.name = name
        self.identity = worker_identity(name)
        self.sessionmaker = sessionmaker
        self.registry = registry
        self.settings = settings
        self.queue = JobQueue(
            lease_seconds=settings.job_lease_seconds,
            max_attempts=settings.job_max_attempts,
            owner=self.identity,
        )
        self._stopping = asyncio.Event()

    def request_stop(self) -> None:
        """Stop claiming. In-flight jobs are allowed to finish.

        Draining rather than aborting, because a job killed mid-flight is a job
        somebody has to reason about later, and a deploy should not create work
        for its own operators.
        """
        self._stopping.set()

    # ------------------------------------------------------------------ loops

    async def run(self) -> None:
        if not self.registry.job_types:
            raise RuntimeError(f"{self.name} has no handlers registered and would claim nothing")

        logger.info(
            "worker_starting",
            extra={
                "worker": self.identity,
                "job_types": [t.value for t in self.registry.job_types],
                "concurrency": self.settings.worker_concurrency,
            },
        )
        loops = [
            asyncio.create_task(self._claim_loop(), name=f"{self.name}-claim-{n}")
            for n in range(self.settings.worker_concurrency)
        ]
        loops.append(asyncio.create_task(self._sweep_loop(), name=f"{self.name}-sweep"))
        try:
            await asyncio.gather(*loops)
        finally:
            for task in loops:
                task.cancel()
            logger.info("worker_stopped", extra={"worker": self.identity})

    async def _claim_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                # The loop itself must survive anything a single iteration can
                # do to it. A worker that exits on a transient database blip is
                # a worker that stops draining the queue for everybody.
                logger.exception("claim_loop_error", extra={"worker": self.identity})
                worked = False
            if not worked:
                await self._wait(self.settings.job_poll_interval_seconds)

    async def _sweep_loop(self) -> None:
        """Requeue jobs whose worker stopped renewing their lease.

        Runs in every worker rather than in one designated process. There is no
        leader to elect and no single point whose death leaves expired leases
        unswept — the sweep is idempotent under contention (see
        `JobQueue._requeue_expired`), so several of them racing is harmless.
        """
        while not self._stopping.is_set():
            await self._wait(self.settings.job_sweep_interval_seconds)
            if self._stopping.is_set():
                return
            try:
                await self.queue.sweep_expired(
                    self.sessionmaker, limit=self.settings.job_sweep_batch
                )
            except Exception:
                logger.exception("sweep_error", extra={"worker": self.identity})

    async def _wait(self, seconds: float) -> None:
        """Sleep, but wake immediately on shutdown."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    # ------------------------------------------------------------- one job

    async def run_once(self) -> bool:
        """Claim and run at most one job. Returns whether there was one."""
        async with self.sessionmaker() as session, session.begin():
            # Unbound: the claim is what decides whose job this is. See
            # `JobQueue.claim`.
            ticket = await self.queue.claim(session, job_types=self.registry.job_types)
        if ticket is None:
            return False

        await self._execute(ticket)
        return True

    async def _execute(self, ticket: ClaimTicket) -> None:
        log_context = {
            "worker": self.identity,
            "job_id": str(ticket.job_id),
            # The tenant identifier is this worker's own subject, not a foreign
            # one, so it is not the disclosure NR-NF-06 forbids.
            "tenant_id": str(ticket.tenant_id),
        }

        # The control session lives outside the handler's transaction and is
        # what `JobContext.stage` writes progress and lease renewals through.
        # `SET LOCAL` dies with its transaction, so it is bound per use rather
        # than once here.
        async with self.sessionmaker() as control:
            heartbeat = asyncio.create_task(self._heartbeat_loop(ticket))
            try:
                await self._run_handler(ticket, control, log_context)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

    async def _run_handler(
        self,
        ticket: ClaimTicket,
        control: AsyncSession,
        log_context: dict[str, str],
    ) -> None:
        try:
            async with self.sessionmaker() as work, work.begin():
                await bind_tenant(work, ticket.tenant_id)
                job = await self.queue.load(work, job_id=ticket.job_id)

                handler = self.registry.get(JobType(job.job_type))
                if handler is None:  # pragma: no cover - the claim filter prevents it
                    raise RuntimeError(f"no handler for job type {job.job_type!r}")

                ctx = JobContext(job=job, session=work, control=control, queue=self.queue)

                # A job cancelled before it was ever picked up should not do any
                # work at all, so the first boundary is before the handler runs.
                if job.cancel_requested_at is not None:
                    raise JobCancelled(None)

                progress = await handler(ctx)
                await self.queue.succeed(work, job_id=ticket.job_id, progress=progress)

            logger.info("job_succeeded", extra=log_context)

        except JobCancelled as exc:
            stage = exc.stage
            await self._record(
                ticket,
                lambda session: self.queue.finish_cancelled(
                    session, job_id=ticket.job_id, stage=stage
                ),
            )
            logger.info("job_cancelled", extra={**log_context, "stage": stage or ""})

        except JobLeaseLost:
            # Someone else owns this job now. Writing an outcome would overwrite
            # theirs with the result of a run the queue has already abandoned.
            logger.warning("job_lease_lost", extra=log_context)

        except Exception as exc:
            verdict = classify(exc)
            # The exception is logged with `exc_info`, which stays in the
            # operator's log. What reaches the job row — and therefore the
            # tenant's console — is `verdict.code` resolved through the approved
            # copy catalogue, never `str(exc)` (NR-NF-06).
            logger.exception(
                "job_failed",
                extra={**log_context, "code": verdict.code, "verdict": verdict.retryability.value},
            )
            await self._record(
                ticket,
                lambda session: self.queue.fail(session, job_id=ticket.job_id, verdict=verdict),
            )

    async def _record(
        self, ticket: ClaimTicket, action: Callable[[AsyncSession], Awaitable[object]]
    ) -> None:
        """Write a job outcome in a transaction of its own.

        Separate from the handler's, which by this point may be aborted and
        incapable of executing anything at all.
        """
        try:
            async with self.sessionmaker() as session, session.begin():
                await bind_tenant(session, ticket.tenant_id)
                await action(session)
        except JobLeaseLost:
            logger.warning(
                "job_outcome_discarded",
                extra={"worker": self.identity, "job_id": str(ticket.job_id)},
            )
        except Exception:
            # The outcome could not be recorded. The lease will lapse and the
            # sweeper will requeue the job, which is the correct fallback: an
            # unrecorded outcome is indistinguishable from a dead worker.
            logger.exception(
                "job_outcome_unrecorded",
                extra={"worker": self.identity, "job_id": str(ticket.job_id)},
            )

    async def _heartbeat_loop(self, ticket: ClaimTicket) -> None:
        """Renew the lease on its own connection while a handler runs.

        On its own connection because a renewal issued inside the handler's
        transaction is invisible until that transaction commits — which is
        precisely when the lease has stopped mattering. A long single-stage
        handler, of which training is one, would otherwise be swept and rerun
        while it was working perfectly.
        """
        while True:
            await asyncio.sleep(self.settings.job_heartbeat_seconds)
            try:
                async with self.sessionmaker() as session, session.begin():
                    await bind_tenant(session, ticket.tenant_id)
                    await self.queue.heartbeat(session, job_id=ticket.job_id)
            except JobLeaseLost:
                return
            except Exception:
                logger.exception(
                    "heartbeat_error",
                    extra={"worker": self.identity, "job_id": str(ticket.job_id)},
                )


__all__ = ["Worker", "worker_identity"]
