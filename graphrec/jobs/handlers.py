"""What a handler is, and how it reports progress.

A handler is one `async` function per job type. It receives a context carrying
the job, a tenant-bound session, and one method — `stage` — which is the only
place cancellation is observed.

That is the whole of the cooperative-cancellation design. A handler that never
calls `stage` can never be cancelled, and a handler that calls it between every
pair of writes can be cancelled anywhere it is safe to be. The decision belongs
to the handler because only the handler knows which of its moments leave the
tenant's data in a state somebody could describe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from graphrec.common.logging import get_logger
from graphrec.db.tenant_context import bind_tenant
from graphrec.jobs.failures import JobCancelled

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.db.models.jobs import Job
    from graphrec.jobs.queue import JobQueue
    from graphrec.jobs.states import JobType

logger = get_logger(__name__)


class JobContext:
    """One job's working context, handed to its handler."""

    def __init__(
        self,
        *,
        job: Job,
        session: AsyncSession,
        control: AsyncSession,
        queue: JobQueue,
    ) -> None:
        self.job = job
        #: Bound to the job's tenant, inside the handler's transaction. Every
        #: read and write the handler makes goes through here and is therefore
        #: subject to the tenant's own policy — a worker has no more reach into
        #: the data than a request handler does.
        self.session = session
        #: A second connection, outside that transaction, used for progress and
        #: lease writes. Separate because a lease renewal that is invisible
        #: until the handler commits is not a liveness signal: the sweeper would
        #: see a stale `lease_expires_at` and steal a job that is working fine.
        self._control = control
        self._queue = queue
        self._stage: str | None = None

    @property
    def job_id(self) -> uuid.UUID:
        return self.job.job_id

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.job.tenant_id

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload

    @property
    def current_stage(self) -> str | None:
        return self._stage

    async def stage(self, name: str, **detail: Any) -> None:
        """Enter a named stage: publish progress, renew the lease, and check for
        a cancellation request.

        Raises `JobCancelled` if one has been made. The exception carries the
        stage the job had reached, because the console renders "Cancelled at
        building_graph." (dc.html L1707) and cannot reconstruct that from the
        status alone.

        A stage must be shorter than the lease. That is the contract: the lease
        is renewed here and nowhere else in a handler's control, so a stage that
        outlives it will be swept and its job retried by somebody else.
        """
        self._stage = name
        progress: dict[str, Any] = {"stage": name, **detail}

        async with self._control.begin():
            # `SET LOCAL` dies with its transaction, so the control session is
            # bound here rather than once when it was opened. Without this the
            # progress write is denied by the tenant's own policy, the guarded
            # `UPDATE` matches nothing, and the handler is told it lost a lease
            # it still holds.
            await bind_tenant(self._control, self.tenant_id)
            await self._queue.report_progress(self._control, job_id=self.job_id, progress=progress)
            cancelled = await self._queue.cancellation_requested(self._control, job_id=self.job_id)

        if cancelled:
            raise JobCancelled(name)


class JobHandler(Protocol):
    """`async def handle(ctx) -> progress | None`.

    The return value is merged into the job's `progress` on success, so a
    handler can leave behind the counts the console shows without a second
    write.
    """

    async def __call__(self, ctx: JobContext) -> dict[str, Any] | None: ...


class HandlerRegistry:
    """Job type to handler. A worker claims only the types it can run.

    Registering nothing for a type is not an oversight to be tolerated at
    runtime: a worker that claimed a job it cannot run would lease it, fail it,
    and spend the tenant's attempts on the deployment's mistake. So the claim
    filter is derived from the registry rather than configured beside it.
    """

    def __init__(self) -> None:
        self._handlers: dict[JobType, JobHandler] = {}

    def register(
        self, job_type: JobType
    ) -> Callable[[Callable[[JobContext], Awaitable[dict[str, Any] | None]]], JobHandler]:
        def decorate(
            fn: Callable[[JobContext], Awaitable[dict[str, Any] | None]],
        ) -> JobHandler:
            if job_type in self._handlers:
                raise RuntimeError(f"a handler is already registered for {job_type.value!r}")
            handler: JobHandler = fn  # type: ignore[assignment]
            self._handlers[job_type] = handler
            return handler

        return decorate

    def get(self, job_type: JobType) -> JobHandler | None:
        return self._handlers.get(job_type)

    @property
    def job_types(self) -> tuple[JobType, ...]:
        """Exactly what this worker may claim."""
        return tuple(self._handlers)


__all__ = ["HandlerRegistry", "JobContext", "JobHandler"]
