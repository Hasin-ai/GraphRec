"""Requesting, reading and cancelling a training run.

Three things this module is careful about.

**The one-active-job rule is the database's, not this module's.** `request`
evaluates eligibility so the refusal can be *explained*, and then inserts; if
two requests race past that evaluation, the partial unique index refuses the
second and the `IntegrityError` is translated back into the same `409` the
evaluation would have produced. That is the phase's exit criterion — "two
concurrent training requests yield one job and one 409" — and it is met by the
index, with this module supplying only the wording.

**A replayed `request_ref` is a success.** §17.3: idempotency is keyed on the
business identifier, and an integration that retried after a timeout gets the
original job back rather than a conflict. The lookup happens before the checks,
because a replay of a request made an hour ago must not be refused for a
cooldown that request itself started.

**Two rows, one transaction.** A run is a `jobs` row (leases, attempts, workers)
and a `training_jobs` row (stages, windows, epochs). They are created together
and the queue row is created first, because `training_jobs.job_id` is
`NOT NULL`: there is no moment at which a training job exists without something
to execute it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from graphrec.common.enums import JobState, UsageType
from graphrec.common.errors import ConflictError, NotFoundError, ValidationError
from graphrec.common.ids import uuid7
from graphrec.common.logging import get_logger
from graphrec.db.models.training import DatasetSnapshot, Model, TrainingJob, TrainingMetric
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering import ledger
from graphrec.domain.metering.periods import current_period
from graphrec.domain.training import eligibility as eligibility_ops
from graphrec.jobs.queue import JobQueue
from graphrec.jobs.states import JobType, QueueStatus
from graphrec.training import states

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.db.models.jobs import Job
    from graphrec.domain.metering.counters import UsageCounters

logger = get_logger(__name__)

#: CON-01's only model family, and the dialog's only option (dc.html L1677).
DEFAULT_MODEL_TYPE = "DGSR"

#: The `models` row a tenant gets without asking. One per tenant until something
#: needs a second; see migration 0010's `_models` docstring.
DEFAULT_MODEL_NAME = "default"

#: L1717: "A reason is required for this action." Four characters is the
#: prototype's own floor, and it is a floor rather than a format because the
#: reason is prose a person types, not a code.
MIN_CANCEL_REASON = 4

#: The index migration 0010 builds for the one-active-job rule. Matched by name
#: when translating an `IntegrityError`, because a tenant hitting the
#: `request_ref` unique constraint at the same instant is a different answer.
ACTIVE_JOB_INDEX = "uq_training_jobs_one_active"
REQUEST_REF_INDEX = "uq_training_jobs_request_ref"


@dataclass(frozen=True, slots=True)
class TrainingRequest:
    """What the dialog collects (L1677-1680)."""

    request_ref: str
    model_type: str = DEFAULT_MODEL_TYPE
    interaction_window_days: int = 90
    max_epochs: int = 20


@dataclass(frozen=True, slots=True)
class RequestOutcome:
    """The job, and whether this call is what created it.

    `created` is `False` for a replay. The router returns `202` either way — a
    repeat is a success — but the distinction decides whether usage is metered,
    and metering a retry would charge a tenant twice for one run.
    """

    job: TrainingJob
    created: bool


class TrainingService:
    """One tenant's training runs."""

    def __init__(
        self,
        *,
        concurrency_limit: int = 1,
        cooldown_seconds: int = 900,
        min_sequences: int = 1_000,
        job_lease_seconds: int = 900,
        job_max_attempts: int = 3,
    ) -> None:
        self._concurrency_limit = concurrency_limit
        self._cooldown_seconds = cooldown_seconds
        self._min_sequences = min_sequences
        self._queue = JobQueue(
            lease_seconds=job_lease_seconds,
            max_attempts=job_max_attempts,
            # Enqueueing takes no lease; the name only ever appears in a stack
            # trace. The same choice `IngestionService` makes.
            owner="control_api",
        )

    # -------------------------------------------------------------- eligibility

    async def eligibility(
        self,
        session: AsyncSession,
        counters: UsageCounters,
        *,
        tenant_id: uuid.UUID,
        now: dt.datetime | None = None,
        window_days: int = 90,
    ) -> eligibility_ops.Eligibility:
        return await eligibility_ops.evaluate(
            session,
            counters,
            tenant_id=tenant_id,
            now=now or dt.datetime.now(dt.UTC),
            concurrency_limit=self._concurrency_limit,
            cooldown_seconds=self._cooldown_seconds,
            min_sequences=self._min_sequences,
            window_days=window_days,
        )

    # ------------------------------------------------------------- requesting

    async def request(
        self,
        session: AsyncSession,
        counters: UsageCounters,
        *,
        tenant_id: uuid.UUID,
        requested_by: uuid.UUID | None,
        request: TrainingRequest,
        now: dt.datetime | None = None,
    ) -> RequestOutcome:
        """Admit a run, or refuse it with the reason it was refused for."""
        now = now or dt.datetime.now(dt.UTC)
        self._validate(request)

        replay = await self._by_request_ref(session, request_ref=request.request_ref)
        if replay is not None:
            # Not compared against the replayed job's parameters. A tenant who
            # reuses an identifier with different settings has made a mistake we
            # cannot fix for them, and answering `409` would break the retry
            # path for the far more common case of an unchanged repeat.
            return RequestOutcome(job=replay, created=False)

        decision = await self.eligibility(
            session,
            counters,
            tenant_id=tenant_id,
            now=now,
            window_days=request.interaction_window_days,
        )
        decision.raise_if_blocked()

        model = await self._model(session, tenant_id=tenant_id, model_type=request.model_type)
        training_job_id = uuid7()
        job = TrainingJob(
            training_job_id=training_job_id,
            tenant_id=tenant_id,
            job_id=uuid7(),  # replaced below; the queue assigns the real one
            model_id=model.model_id,
            state=JobState.QUEUED.value,
            stage_index=0,
            # L1683, verbatim.
            progress_text="waiting to start",
            requested_by=requested_by,
            request_ref=request.request_ref,
            interaction_window_days=request.interaction_window_days,
            max_epochs=request.max_epochs,
            requested_at=now,
        )

        # A savepoint, not the transaction. Losing this race must undo the
        # queue row and the training row together and leave everything else
        # standing — including the caller's transaction, which this service does
        # not own. `session.rollback()` here would discard the router's unit of
        # work and then fail on the next statement issued inside it, which is
        # how a `409` turns into a 500.
        try:
            async with session.begin_nested():
                queue_job = await self._queue.enqueue(
                    session,
                    tenant_id=tenant_id,
                    job_type=JobType.TRAINING,
                    payload={"training_job_id": str(training_job_id)},
                    # A training run is the longest thing this system does and
                    # the slowest to redo. It gets the same attempt budget as
                    # everything else; what differs is that its deterministic
                    # failures — too little data, a quota that moved — never
                    # reach a worker at all.
                    run_after=now,
                )
                job.job_id = queue_job.job_id
                session.add(job)
                await session.flush()
        except IntegrityError as exc:
            translated = await self._translate(session, exc, tenant_id=tenant_id, now=now)
            if isinstance(translated, _RaceLostToReplayError):
                # The other side of the race wrote the row this request was
                # asking for. That is the outcome the caller wanted, arrived at
                # by a longer path, so it is a success and it is not metered
                # again — the winner already did that.
                return RequestOutcome(job=translated.job, created=False)
            raise translated from exc

        await self._meter(session, counters, tenant_id=tenant_id, job=job, now=now)
        return RequestOutcome(job=job, created=True)

    def _validate(self, request: TrainingRequest) -> None:
        """The two things the request schema cannot say for itself.

        Window and epoch options are enumerated in the API schema and again as
        check constraints; what is left is the identifier, which is required
        (L1681) and is a business key rather than a header.
        """
        if not request.request_ref.strip():
            raise ValidationError("training_request_ref_required").with_field(
                "request_ref", "training_request_ref_required"
            )
        if request.model_type != DEFAULT_MODEL_TYPE:
            raise ValidationError("training_model_type_unknown").with_field(
                "model_type", "training_model_type_unknown"
            )

    async def _translate(
        self,
        session: AsyncSession,
        exc: IntegrityError,
        *,
        tenant_id: uuid.UUID,
        now: dt.datetime,
    ) -> Exception:
        """Turn an index violation back into the sentence it stands for.

        The savepoint has already been rolled back by the time this is called —
        that is what `async with session.begin_nested()` does on the way out —
        so the session is usable again and the follow-up query for the winning
        job's identifier can be made on it. Reading the winner is the whole
        point: "a training run is already in progress" without saying which one
        leaves the console with nothing to link to.
        """
        detail = str(exc.orig)

        if REQUEST_REF_INDEX in detail:
            # Two requests carrying the same `request_ref` arrived at once and
            # this one lost. The winner is the original, so this is the replay
            # path arriving a moment late, not a conflict.
            replay = await self._by_request_ref_in_tenant(
                session, tenant_id=tenant_id, request_ref=_request_ref_of(exc)
            )
            if replay is not None:
                return _RaceLostToReplayError(replay)

        if ACTIVE_JOB_INDEX in detail:
            winner = await eligibility_ops.active_job(session)
            return ConflictError(
                "training_already_running",
                copy_args={
                    "job_id": str(winner) if winner else "",
                    "concurrency": self._concurrency_limit,
                },
            )

        logger.warning(
            "training_request_integrity_error",
            extra={"tenant_id": str(tenant_id), "at": now.isoformat()},
        )
        return exc

    async def _meter(
        self,
        session: AsyncSession,
        counters: UsageCounters,
        *,
        tenant_id: uuid.UUID,
        job: TrainingJob,
        now: dt.datetime,
    ) -> None:
        """One training run, metered at request rather than at completion.

        The quota card counts requests (L1668 shows 6/8 against a plan's
        `training_limit`), and a run that fails still occupied the global slot.
        Metering on success would let a tenant spend the platform's only
        training capacity indefinitely at no cost to their allowance.
        """
        period = current_period(now)
        granted = await ledger.grant(
            session,
            tenant_id=tenant_id,
            usage_type=UsageType.TRAINING,
            quantity=1,
            idempotency_key=f"training:{job.training_job_id}",
            occurred_at=now,
            source_ref=str(job.training_job_id),
        )
        if granted:
            await counter_ops.note_granted(
                counters,
                tenant_id=tenant_id,
                usage_type=UsageType.TRAINING,
                period=period,
                quantity=1,
            )

    async def _model(
        self, session: AsyncSession, *, tenant_id: uuid.UUID, model_type: str
    ) -> Model:
        found = await session.scalar(
            sa.select(Model).where(Model.name == DEFAULT_MODEL_NAME).limit(1)
        )
        if found is not None:
            return found

        # Two first-ever requests can arrive at once and both find nothing here.
        # The insert is therefore written to tolerate losing: `ON CONFLICT DO
        # NOTHING` waits for the other transaction, inserts nothing once it
        # commits, and the re-read that follows takes a fresh READ COMMITTED
        # snapshot that includes the winner's row.
        #
        # Raising instead would be actively wrong. The race this method is in
        # the middle of is arbitrated by `uq_training_jobs_one_active` a few
        # statements later, and a tenant losing it deserves "a run is already in
        # progress" — not a unique-violation on a container they never asked
        # for and cannot see.
        await session.execute(
            pg_insert(Model)
            .values(
                model_id=uuid7(),
                tenant_id=tenant_id,
                name=DEFAULT_MODEL_NAME,
                model_type=model_type,
                default_config={},
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "name"])
        )
        model = await session.scalar(
            sa.select(Model).where(Model.name == DEFAULT_MODEL_NAME).limit(1)
        )
        if model is None:  # pragma: no cover - the insert either wrote or found
            msg = "the tenant's default model could neither be read nor created"
            raise RuntimeError(msg)
        return model

    # ---------------------------------------------------------------- reading

    async def get(self, session: AsyncSession, *, training_job_id: uuid.UUID) -> TrainingJob:
        """Gate 4. A foreign job is invisible under the tenant's policy, so this
        is a `404` and not a `403` — a `403` would confirm it exists."""
        job = await session.get(TrainingJob, training_job_id)
        if job is None:
            raise NotFoundError("not_found")
        return job

    async def list_jobs(
        self,
        session: AsyncSession,
        *,
        state: JobState | None = None,
        limit: int = 50,
    ) -> list[TrainingJob]:
        """The `/training` table, newest first (L1668)."""
        query = sa.select(TrainingJob).order_by(TrainingJob.requested_at.desc()).limit(limit)
        if state is not None:
            query = query.where(TrainingJob.state == state.value)
        return list((await session.scalars(query)).all())

    async def snapshot_of(
        self, session: AsyncSession, *, training_job_id: uuid.UUID
    ) -> DatasetSnapshot | None:
        found: DatasetSnapshot | None = await session.scalar(
            sa.select(DatasetSnapshot).where(DatasetSnapshot.training_job_id == training_job_id)
        )
        return found

    async def snapshot(self, session: AsyncSession, *, snapshot_id: uuid.UUID) -> DatasetSnapshot:
        found = await session.get(DatasetSnapshot, snapshot_id)
        if found is None:
            raise NotFoundError("not_found")
        return found

    async def metrics(
        self, session: AsyncSession, *, training_job_id: uuid.UUID
    ) -> list[TrainingMetric]:
        """The per-epoch curve, ordered so a client can plot it without sorting."""
        return list(
            (
                await session.scalars(
                    sa.select(TrainingMetric)
                    .where(TrainingMetric.training_job_id == training_job_id)
                    .order_by(TrainingMetric.epoch, TrainingMetric.metric_name)
                )
            ).all()
        )

    async def queue_job(self, session: AsyncSession, *, job: TrainingJob) -> Job:
        return await self._queue.load(session, job_id=job.job_id)

    # ----------------------------------------------------------- cancellation

    async def cancel(
        self,
        session: AsyncSession,
        *,
        training_job_id: uuid.UUID,
        reason: str,
        now: dt.datetime | None = None,
    ) -> TrainingJob:
        """Ask a run to stop, and record who asked and why.

        Nothing stops here. The state moves to `cancelling` and the worker
        notices at its next stage boundary — "The job moves to cancelling and
        then to cancelled" (L1714). Asking twice is the same ask: the first
        request's reason is kept, because it is the one that was audited.
        """
        now = now or dt.datetime.now(dt.UTC)
        job = await self.get(session, training_job_id=training_job_id)
        if job.is_terminal():
            raise ConflictError("job_not_cancellable")
        if len(reason.strip()) < MIN_CANCEL_REASON:
            raise ValidationError("reason_required").with_field("reason", "reason_required")

        if job.job_state is not JobState.CANCELLING:
            job.state = JobState.CANCELLING.value
            # L1718's wording, so the console's panel reads the same whichever
            # realm asked. The stage index is untouched: it is where the run got
            # to, and cancelling is not a place on the rail.
            job.cancel_reason = f"Cancelled by requester: {reason.strip()}"
            job.progress_text = f"cancelling at {states.STAGE_NAMES[job.stage_index]}"
            job.updated_at = now

        queue_job = await self._queue.request_cancellation(
            session, job_id=job.job_id, reason=reason.strip()
        )

        # A run nobody is holding has no worker to observe the request at a
        # stage boundary, so left alone it would sit at `cancelling` for ever —
        # the console would show a spinner on a job that will never move. The
        # queue row is not `running` and this transaction holds a lock on it, so
        # a claim arriving now either waits and finds it cancelled or skips it;
        # settling both sides here is therefore safe, and it is the only path by
        # which a run stopped before it started reaches a terminal state.
        #
        # One window is left open and is not closed here: a worker that dies
        # holding the lease leaves the row `running` until the sweeper requeues
        # it, and a cancellation arriving inside that window is recorded but not
        # settled until the next claim observes it. See PHASE_9_REPORT §3.
        if queue_job.status == QueueStatus.QUEUED.value:
            stopped_at = states.STAGE_NAMES[job.stage_index]
            settled = await self._queue.cancel_unclaimed(
                session, job_id=job.job_id, stage=stopped_at
            )
            if settled:
                job.state = JobState.CANCELLED.value
                job.progress_text = f"stopped at {stopped_at}"
                job.completed_at = now

        await session.flush()
        return job

    # ----------------------------------------------------------------- lookups

    async def _by_request_ref(
        self, session: AsyncSession, *, request_ref: str
    ) -> TrainingJob | None:
        found: TrainingJob | None = await session.scalar(
            sa.select(TrainingJob).where(TrainingJob.request_ref == request_ref)
        )
        return found

    async def _by_request_ref_in_tenant(
        self, session: AsyncSession, *, tenant_id: uuid.UUID, request_ref: str | None
    ) -> TrainingJob | None:
        if request_ref is None:
            return None
        found: TrainingJob | None = await session.scalar(
            sa.select(TrainingJob).where(
                TrainingJob.tenant_id == tenant_id, TrainingJob.request_ref == request_ref
            )
        )
        return found


class _RaceLostToReplayError(Exception):
    """Internal signal: the losing side of a `request_ref` race.

    Carries the winning job so `request` can answer with it. Deliberately not a
    `GraphRecError`: it never becomes a response, because `request` unwraps it
    into the ordinary replay outcome before returning.
    """

    def __init__(self, job: TrainingJob) -> None:
        super().__init__("request_ref replay")
        self.job = job


def _request_ref_of(exc: IntegrityError) -> str | None:
    """Recover the identifier from the failing statement's parameters.

    The alternative — parsing it out of the driver's `DETAIL:` string — would
    depend on the server's message locale. The parameters are what we sent.
    """
    params = exc.params
    if isinstance(params, dict):
        value = params.get("request_ref")
        return str(value) if value is not None else None
    return None


@dataclass(frozen=True, slots=True)
class StageRail:
    """The rail as a value, not a dictionary.

    A dictionary here would reach the router as `dict[str, object]` and force a
    cast at every field — three casts whose only job is to re-assert what this
    function already knew.
    """

    stages: tuple[str, ...]
    stage_index: int
    note: str


def render_stage_rail(job: TrainingJob) -> StageRail:
    """What the rail shows, decided server-side.

    The note is the prototype's, branch for branch (L1707): a live run shows its
    progress text, a failed one "Stopped at X.", a cancelled one "Cancelled at
    X.", a finished one "All stages complete."
    """
    if job.job_state is JobState.SUCCEEDED:
        note = "All stages complete."
    elif job.job_state is JobState.FAILED:
        note = f"Stopped at {job.stopped_at()}."
    elif job.job_state is JobState.CANCELLED:
        note = f"Cancelled at {job.stopped_at()}."
    else:
        note = job.progress_text
    return StageRail(
        stages=states.STAGE_NAMES,
        stage_index=job.rail_position(),
        note=note,
    )


def eligibility_payload(decision: eligibility_ops.Eligibility) -> dict[str, object]:
    return eligibility_ops.as_dict(decision)


__all__ = [
    "ACTIVE_JOB_INDEX",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_MODEL_TYPE",
    "MIN_CANCEL_REASON",
    "REQUEST_REF_INDEX",
    "RequestOutcome",
    "StageRail",
    "TrainingRequest",
    "TrainingService",
    "eligibility_payload",
    "render_stage_rail",
]
