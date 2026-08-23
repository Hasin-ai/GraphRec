"""The nine stages, in the order the console draws them.

This is Phase 8's offline runner wired to a job, a tenant and an object store,
and the wiring is the interesting part rather than the model.

**Every stage boundary is three things at once.** It publishes progress the
console can poll, it renews the lease so the sweeper does not steal a job that
is working, and it is the only place cancellation is observed. `JobContext.stage`
does the first two; this module adds the third obligation on top of it —
`training_jobs.state`, `stage_index` and `progress_text` — because the rail is a
tenant-facing resource and `jobs.progress` is a worker's scratch space.

**The order within a boundary is: ask, then advance.** Cancellation is checked
before the rail moves, so a run cancelled during `training` is recorded as
having stopped at `training` and not at the stage it was about to enter. That is
the prototype's own accounting (L1690, L1707) and it is the only reading under
which "Cancelled at building_graph" describes work that actually happened.

**Training runs in a thread.** Torch is synchronous and CPU-bound, and running
it on the event loop would stop the heartbeat that keeps the lease alive — the
job would be swept mid-epoch by its own worker. So `train` runs through
`anyio.to_thread` and its two seams call back into the loop with
`anyio.from_thread`. The seams are the ones Phase 8 built for this and did not
otherwise use.

**Failures are classified, not just raised.** A dataset below the minimum is a
`PermanentJobError`: it will be exactly as small on the second attempt, and
BUILD_PROMPT L471 is explicit that a deterministic failure consumes no attempts.
A storage timeout is an `OSError` and the classifier already calls that
retryable.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import decimal
import functools
import pathlib
import re
import tempfile
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anyio
import anyio.from_thread
import anyio.to_thread
import sqlalchemy as sa
import torch

from graphrec.common.enums import JobState
from graphrec.common.error_copy import resolve_copy
from graphrec.common.ids import uuid7
from graphrec.common.logging import get_logger
from graphrec.domain.training import snapshot as snapshot_ops
from graphrec.jobs.failures import JobCancelled, PermanentJobError
from graphrec.ml.eval.baseline import evaluate_popularity
from graphrec.ml.eval.evaluate import evaluate_model
from graphrec.ml.eval.split import leave_last_out
from graphrec.ml.features.builder import FeatureBuilder
from graphrec.ml.graph.build import build_graph
from graphrec.ml.train.loop import TrainingConfig, train
from graphrec.storage import keys
from graphrec.storage.store import digest_file
from graphrec.training import states

if TYPE_CHECKING:
    from collections.abc import Iterator

    from graphrec.jobs.handlers import JobContext
    from graphrec.ml.eval.metrics import Metrics
    from graphrec.ml.eval.split import Split
    from graphrec.ml.graph.build import InteractionGraph
    from graphrec.ml.model.dgsr import DGSR
    from graphrec.ml.train.loop import EpochReport, TrainingResult
    from graphrec.storage.store import ArtifactStore

logger = get_logger(__name__)

#: The measures written per epoch and again at the end, as *families*. Named
#: here so the registry's metric floor (Phase 10) and the console's curve read
#: the same keys, and so a measure added to `Metrics` without a decision about
#: storing it is a visible omission rather than a silent one.
#:
#: Families rather than literal names, because `Metrics.as_dict` suffixes three
#: of them with the cut-off it was computed at — `recall_at_10` at K=10 and
#: `recall_at_5` at K=5. A list of literals would silently store nothing at all
#: the moment K moved, which is exactly what a list of literals did.
CURVE_METRICS = ("loss", "recall", "hit_rate", "ndcg", "coverage")

#: `recall_at_10` -> `recall`. Anchored and bounded so a future `recall_at_k_std`
#: is a name this does not quietly accept.
_AT_K = re.compile(r"^(?P<family>.+)_at_\d+$")

#: Epoch 0 holds the popularity baseline. The curve therefore starts from
#: something a tenant can interpret — "better than recommending the top sellers"
#: — rather than from whatever the first trained epoch happened to score.
BASELINE_EPOCH = 0

#: `numeric(18,6)` in migration 0010. Quantised on the way in so the value the
#: console plots is the value the evaluator computed, rather than the value
#: PostgreSQL rounded it to on a later read.
METRIC_PLACES = decimal.Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """What the handler leaves behind in `jobs.progress` on success."""

    snapshot_id: uuid.UUID
    sequence_count: int
    product_count: int
    best_epoch: int
    metrics: dict[str, float]
    baseline: dict[str, float]
    beats_baseline: bool

    def as_progress(self) -> dict[str, Any]:
        return {
            "stage": JobState.SUCCEEDED.value,
            "snapshot_id": str(self.snapshot_id),
            "sequences": self.sequence_count,
            "products": self.product_count,
            "best_epoch": self.best_epoch,
            "metrics": self.metrics,
            "baseline": self.baseline,
            "beats_baseline": self.beats_baseline,
        }


class Rail:
    """The console's view of a run, advanced one stage at a time.

    Holds no session. Every write opens its own transaction through
    `JobContext.control`, because the handler's own transaction rolls back when
    the run fails and a rail that vanished on failure would be a rail that only
    ever shows success.
    """

    def __init__(self, ctx: JobContext, *, training_job_id: uuid.UUID) -> None:
        self._ctx = ctx
        self._training_job_id = training_job_id
        self._index = 0

    @property
    def stage_index(self) -> int:
        return self._index

    async def enter(self, state: JobState, progress: str, **detail: Any) -> None:
        """Observe cancellation, then move the rail to `state`.

        `ctx.stage` raises `JobCancelled` when a cancellation is pending, and it
        raises it *before* this writes anything — so the recorded position is
        the last stage the run actually completed.
        """
        await self._ctx.stage(state.value, **detail)
        self._index = states.stage_index(state)
        await self._write(state=state, progress=progress)

    async def note(self, progress: str, **detail: Any) -> None:
        """Update the progress line without moving the rail.

        This is how "epoch 6 of 20" (BACKEND_PLAN L1116) reaches the console
        without the rail appearing to advance nine times inside one stage.
        """
        await self._ctx.stage(states.STAGE_NAMES[self._index], **detail)
        await self._write(state=states.STAGE_RAIL[self._index], progress=progress)

    async def succeed(self) -> None:
        await self._write(
            state=JobState.SUCCEEDED,
            progress="complete",
            stage_index=states.stage_index(JobState.SUCCEEDED),
            completed=True,
        )

    async def cancel(self) -> None:
        """L1707: "Cancelled at X." — where X is `stage_index`, untouched."""
        await self._write(
            state=JobState.CANCELLED,
            progress=f"stopped at {states.STAGE_NAMES[self._index]}",
            completed=True,
        )

    async def fail(self, *, code: str, reason: str, reference: str) -> None:
        await self._write(
            state=JobState.FAILED,
            progress=f"stopped at {states.STAGE_NAMES[self._index]}",
            completed=True,
            failure_reason=reason,
            error_reference=reference,
        )
        logger.warning(
            "training_job_failed",
            extra={
                "training_job_id": str(self._training_job_id),
                "code": code,
                "error_reference": reference,
            },
        )

    async def _write(
        self,
        *,
        state: JobState,
        progress: str,
        stage_index: int | None = None,
        completed: bool = False,
        failure_reason: str | None = None,
        error_reference: str | None = None,
    ) -> None:
        now = dt.datetime.now(dt.UTC)
        assignments = [
            "state = :state",
            "stage_index = :stage_index",
            "progress_text = :progress",
            "updated_at = :now",
        ]
        params: dict[str, Any] = {
            "state": state.value,
            "stage_index": self._index if stage_index is None else stage_index,
            "progress": progress,
            "now": now,
            "training_job_id": self._training_job_id,
        }
        if completed:
            assignments.append("completed_at = :now")
        else:
            # A retry re-enters the rail on a row that a previous attempt may
            # have left terminal. Clearing the three terminal columns is not
            # tidiness: `ck_training_jobs_failure_reason` and
            # `ck_training_jobs_cancel_reason` refuse a working state that still
            # carries a reason, and `ck_training_jobs_terminal_dated` refuses one
            # that still carries a completion date. A resumed run is not a
            # failed run, and the row has to stop saying that it is.
            assignments += [
                "completed_at = NULL",
                "failure_reason = NULL",
                "cancel_reason = NULL",
                "error_reference = NULL",
            ]
        if failure_reason is not None:
            assignments.append("failure_reason = :failure_reason")
            params["failure_reason"] = failure_reason
        if error_reference is not None:
            assignments.append("error_reference = :error_reference")
            params["error_reference"] = error_reference

        async with self._ctx.control() as control:
            await control.execute(
                sa.text(
                    f"UPDATE training_jobs SET {', '.join(assignments)} "
                    "WHERE training_job_id = :training_job_id"
                ),
                params,
            )


class TrainingPipeline:
    """One run, from the queue to a scored model."""

    def __init__(
        self,
        store: ArtifactStore,
        *,
        builder: FeatureBuilder | None = None,
        min_sequences: int = 1_000,
        seed: int = 1337,
        k: int = 10,
        workspace: pathlib.Path | None = None,
    ) -> None:
        self._store = store
        self._builder = builder or FeatureBuilder()
        self._min_sequences = min_sequences
        self._seed = seed
        self._k = k
        self._workspace = workspace

    async def run(self, ctx: JobContext) -> dict[str, Any]:
        """The handler. Nine stages, and one exit for each way a run can end."""
        training_job_id = _training_job_id(ctx)
        rail = Rail(ctx, training_job_id=training_job_id)
        settings = await self._settings(ctx, training_job_id=training_job_id)

        try:
            with self._scratch() as scratch:
                outcome = await self._pipeline(
                    ctx, rail, scratch, training_job_id=training_job_id, settings=settings
                )
        except JobCancelled:
            await rail.cancel()
            raise
        except PermanentJobError as exc:
            reference = _error_reference(training_job_id)
            await rail.fail(code=exc.code, reason=_copy(exc), reference=reference)
            raise
        except Exception:
            # A retryable crash is not an outcome, it is an interruption, and the
            # queue is about to hand the same job back. Writing `failed` here
            # would put a terminal state on a run that is going to resume, and
            # the console would show a failure that un-fails itself a minute
            # later. So the rail is left exactly where it stopped — which is also
            # what makes the resumed attempt legible: it re-enters at the stage
            # the crashed one was in.
            if ctx.job.attempt + 1 < ctx.job.max_attempts:
                raise
            reference = _error_reference(training_job_id)
            # No exception text. A traceback out of a training worker can carry
            # a row of the tenant's data, and NR-NF-06 keeps that out of both the
            # response body and the log line the tenant can see. The reference
            # is how support correlates the two.
            await rail.fail(code="job_failed", reason=_copy(None), reference=reference)
            raise

        await rail.succeed()
        return outcome.as_progress()

    # ------------------------------------------------------------- the stages

    async def _pipeline(
        self,
        ctx: JobContext,
        rail: Rail,
        scratch: pathlib.Path,
        *,
        training_job_id: uuid.UUID,
        settings: _RunSettings,
    ) -> StageOutcome:
        await rail.enter(JobState.WAITING_FOR_RESOURCES, "waiting for a training slot")

        # ---- preparing_data
        await rail.enter(JobState.PREPARING_DATA, "reading the interaction window")
        contents, snapshot_id = await self._prepare(
            ctx, training_job_id=training_job_id, settings=settings
        )
        await rail.note(
            f"snapshot {snapshot_id} · {contents.sequence_count():,} sequences",
            sequences=contents.sequence_count(),
        )

        # ---- building_graph
        await rail.enter(JobState.BUILDING_GRAPH, "constructing the interaction graph")
        dataset = contents.build(self._builder)
        split = leave_last_out(dataset)
        # The phase-8 exit criterion, run again on real data. It is cheap
        # relative to a training run and it is the one property whose failure
        # would make every metric below meaningless rather than merely wrong.
        split.assert_no_leakage()
        graph = build_graph(split.train)
        await rail.note(
            f"{split.train.n_items:,} items · {graph.n_edges:,} edges",
            items=split.train.n_items,
            edges=graph.n_edges,
        )

        # ---- training
        await rail.enter(JobState.TRAINING, f"epoch 0 of {settings.max_epochs}")
        result = await self._train(ctx, rail, scratch, split=split, settings=settings)

        # ---- evaluating
        await rail.enter(JobState.EVALUATING, "measuring against the held-out split")
        measured, baseline = await anyio.to_thread.run_sync(
            functools.partial(self._evaluate, result_model=result.model, graph=graph, split=split)
        )
        await self._record_metrics(
            ctx,
            training_job_id=training_job_id,
            epoch=BASELINE_EPOCH,
            values=baseline.as_dict(),
        )

        # ---- indexing_embeddings
        await rail.enter(JobState.INDEXING_EMBEDDINGS, "exporting item embeddings")
        await self._export_embeddings(
            ctx, scratch, training_job_id=training_job_id, model=result.model
        )

        # ---- registering
        await rail.enter(JobState.REGISTERING, "recording the result")
        await self._record_metrics(
            ctx,
            training_job_id=training_job_id,
            epoch=result.best_epoch,
            values=measured.as_dict(),
        )
        # The checkpoint is the run's product until Phase 10 turns it into a
        # version. Removing it here would mean a resumed job and a registered
        # one need different artifacts; leaving it means registration reads
        # exactly what training wrote.

        return StageOutcome(
            snapshot_id=snapshot_id,
            sequence_count=contents.sequence_count(),
            product_count=contents.product_count,
            best_epoch=result.best_epoch,
            metrics={key: float(value) for key, value in measured.as_dict().items()},
            baseline={key: float(value) for key, value in baseline.as_dict().items()},
            beats_baseline=measured.beats(baseline),
        )

    # ------------------------------------------------------------ the pieces

    async def _prepare(
        self, ctx: JobContext, *, training_job_id: uuid.UUID, settings: _RunSettings
    ) -> tuple[snapshot_ops.SnapshotContents, uuid.UUID]:
        """Freeze the window, store it, and record what it held.

        The cutoff is taken here and once. Everything downstream reads the
        snapshot rather than the tables, so a run that takes an hour is a run
        over one hour-old view of the data rather than nine views of it.

        A retry re-enters this stage, and `UNIQUE(training_job_id)` (SRS §5.2.9)
        says a run has one snapshot — so the second attempt adopts the first
        one's cutoff instead of taking a new one. That is not only about the
        constraint: the checkpoint it is about to resume was trained against that
        window, and reading a fresher one would move the data out from under a
        half-trained model and quietly invalidate the epochs already spent.
        """
        existing = await self._existing_snapshot(ctx, training_job_id=training_job_id)
        cutoff_at = existing[1] if existing else dt.datetime.now(dt.UTC)

        async with ctx.control() as control:
            contents = await snapshot_ops.read_contents(
                control, cutoff_at=cutoff_at, window_days=settings.window_days
            )

        sequences = contents.sequence_count()
        if sequences < self._min_sequences:
            # L697, and permanent: the same window will hold the same number of
            # sequences on the second attempt.
            raise PermanentJobError("training_insufficient_data", minimum=self._min_sequences)

        if existing is not None:
            # The object is already in the store under this identifier, and its
            # checksum is what the row promises. Re-uploading would be a write
            # that can only change something for the worse.
            return contents, existing[0]

        snapshot_id = uuid7()
        key = keys.snapshot_key(ctx.tenant_id, snapshot_id)
        checksum = self._store.put_bytes(key, snapshot_ops.encode(contents))

        async with ctx.control() as control:
            await control.execute(
                sa.text(
                    "INSERT INTO dataset_snapshots "
                    "  (snapshot_id, tenant_id, training_job_id, cutoff_at, window_days, "
                    "   uri, checksum, sequence_count, product_count, event_count) "
                    "VALUES (:snapshot_id, :tenant_id, :training_job_id, :cutoff_at, :window_days, "
                    "        :uri, :checksum, :sequences, :products, :events)"
                ),
                {
                    "snapshot_id": snapshot_id,
                    "tenant_id": ctx.tenant_id,
                    "training_job_id": training_job_id,
                    "cutoff_at": cutoff_at,
                    "window_days": settings.window_days,
                    "uri": self._store.uri(key),
                    "checksum": checksum,
                    "sequences": sequences,
                    "products": contents.product_count,
                    "events": contents.event_count,
                },
            )
        return contents, snapshot_id

    async def _existing_snapshot(
        self, ctx: JobContext, *, training_job_id: uuid.UUID
    ) -> tuple[uuid.UUID, dt.datetime] | None:
        """This run's snapshot, if an earlier attempt already froze one."""
        async with ctx.control() as control:
            row = (
                await control.execute(
                    sa.text(
                        "SELECT snapshot_id, cutoff_at FROM dataset_snapshots "
                        " WHERE training_job_id = :training_job_id"
                    ),
                    {"training_job_id": training_job_id},
                )
            ).first()
        if row is None:
            return None
        return row[0], row[1]

    async def _train(
        self,
        ctx: JobContext,
        rail: Rail,
        scratch: pathlib.Path,
        *,
        split: Split,
        settings: _RunSettings,
    ) -> TrainingResult:
        """Run the loop off the event loop, reporting from inside it.

        The checkpoint is pulled from the store before the first epoch and
        pushed after each one. That is what makes a crash resumable: a worker
        that dies at epoch 7 leaves epoch 7's checkpoint in the store, and the
        next attempt at the same job downloads it and starts at epoch 8.
        """
        checkpoint_path = scratch / "checkpoint.safetensors"
        checkpoint_key = keys.checkpoint_key(ctx.tenant_id, _training_job_id(ctx))
        resume = self._store.exists(checkpoint_key)
        if resume:
            self._store.get_file(checkpoint_key, checkpoint_path)
            logger.info("training_checkpoint_restored", extra={"key": checkpoint_key})

        config = TrainingConfig(epochs=settings.max_epochs, seed=self._seed, k=self._k)
        cancelled = _Flag()

        def on_epoch(report: EpochReport) -> None:
            # Called from the training thread. `from_thread.run` schedules the
            # coroutine on the loop that started this worker and blocks here
            # until it finishes, so progress is durable before the next epoch
            # begins rather than merely queued.
            anyio.from_thread.run(
                self._after_epoch,
                ctx,
                rail,
                report,
                settings,
                cancelled,
                checkpoint_key,
                checkpoint_path,
            )

        result = await anyio.to_thread.run_sync(
            functools.partial(
                train,
                split,
                self._builder,
                config=config,
                checkpoint_path=checkpoint_path,
                resume=resume,
                on_epoch=on_epoch,
                should_stop=cancelled.is_set,
            )
        )
        # `should_stop` breaks the loop without saying why, which is right for
        # the loop and wrong for the job: a run stopped because somebody asked
        # is cancelled, not early-stopped. The flag is the only thing that can
        # tell the two apart once `train` has returned.
        if cancelled.is_set():
            raise JobCancelled(states.STAGE_NAMES[rail.stage_index])
        return result

    async def _after_epoch(
        self,
        ctx: JobContext,
        rail: Rail,
        report: EpochReport,
        settings: _RunSettings,
        cancelled: _Flag,
        checkpoint_key: str,
        checkpoint_path: pathlib.Path,
    ) -> None:
        if checkpoint_path.exists():
            self._store.put_file(checkpoint_key, checkpoint_path)

        values: dict[str, float] = {"loss": report.loss}
        if report.validation is not None:
            values.update(report.validation.as_dict())
        await self._record_metrics(
            ctx,
            training_job_id=_training_job_id(ctx),
            epoch=report.epoch,
            values=values,
        )

        try:
            # BACKEND_PLAN L1116's progress line, verbatim in shape.
            await rail.note(
                f"epoch {report.epoch} of {settings.max_epochs}",
                epoch=report.epoch,
                loss=round(report.loss, 6),
            )
        except JobCancelled:
            # Raised inside a callback running on a training thread's behalf.
            # Letting it out here would surface as a torch stack; recording it
            # and letting the loop finish the epoch it is in is both tidier and
            # what "cooperative" means.
            cancelled.set()

    def _evaluate(
        self, *, result_model: DGSR, graph: InteractionGraph, split: Split
    ) -> tuple[Metrics, Metrics]:
        """Model and baseline, on the same held-out set, in one thread hop.

        Both, always. A metric with nothing to compare it against cannot answer
        the only question a tenant has about it, and Phase 10's eligibility
        floor is defined relative to this baseline (ADR 0024).
        """
        measured = evaluate_model(
            result_model, graph, self._builder, split.train, split.test, k=self._k, seed=self._seed
        )
        baseline = evaluate_popularity(split.train, split.test, k=self._k)
        return measured, baseline

    async def _export_embeddings(
        self,
        ctx: JobContext,
        scratch: pathlib.Path,
        *,
        training_job_id: uuid.UUID,
        model: DGSR,
    ) -> None:
        """Write the item matrix the candidate index will be built from.

        Dot-product scoring means a version *is* an item matrix (ADR 0023), so
        this stage produces the one artifact serving needs and Phase 10's
        `CandidateIndex` loads. It is a `safetensors` file for the reason ADR
        0025 gives, and it is exported here rather than at registration because
        this is the stage the console named.
        """
        from safetensors.torch import save_file

        path = scratch / "items.safetensors"
        matrix = await anyio.to_thread.run_sync(functools.partial(_export_matrix, model))
        await anyio.to_thread.run_sync(
            functools.partial(
                save_file,
                {"item_embeddings": matrix},
                str(path),
                metadata={
                    "tenant_id": str(ctx.tenant_id),
                    "training_job_id": str(training_job_id),
                    "feature_builder_version": str(self._builder.VERSION),
                },
            )
        )
        key = keys.bundle_key(ctx.tenant_id, training_job_id, "items.safetensors")
        self._store.put_file(key, path)
        logger.info(
            "training_embeddings_exported",
            extra={"key": key, "digest": digest_file(path)},
        )

    async def _record_metrics(
        self,
        ctx: JobContext,
        *,
        training_job_id: uuid.UUID,
        epoch: int,
        values: dict[str, float],
    ) -> None:
        """Append the curve's points, ignoring a repeat.

        `ON CONFLICT DO NOTHING` rather than an upsert: `training_metrics` has
        no `UPDATE` grant, and a resumed run re-measuring an epoch it already
        recorded should keep the original measurement rather than fail on it.
        """
        rows = [
            {
                "metric_id": uuid7(),
                "tenant_id": ctx.tenant_id,
                "training_job_id": training_job_id,
                "epoch": epoch,
                "metric_name": name,
                "value": decimal.Decimal(str(value)).quantize(METRIC_PLACES),
            }
            for name, value in values.items()
            if _is_curve_metric(name)
        ]
        if not rows:
            return
        async with ctx.control() as control:
            await control.execute(
                sa.text(
                    "INSERT INTO training_metrics "
                    "  (metric_id, tenant_id, training_job_id, epoch, metric_name, value) "
                    "VALUES (:metric_id, :tenant_id, :training_job_id, :epoch, "
                    "        :metric_name, :value) "
                    "ON CONFLICT (training_job_id, epoch, metric_name) DO NOTHING"
                ),
                rows,
            )

    # ------------------------------------------------------------- utilities

    async def _settings(self, ctx: JobContext, *, training_job_id: uuid.UUID) -> _RunSettings:
        """Read the run's own parameters, not the current defaults.

        A job queued yesterday with a 30-day window trains on 30 days even if
        the dialog's default has since moved. The payload carries only the
        identifier; everything else is read from the row, which is the record a
        tenant can see.
        """
        async with ctx.control() as control:
            row = (
                await control.execute(
                    sa.text(
                        "SELECT interaction_window_days, max_epochs FROM training_jobs "
                        "WHERE training_job_id = :training_job_id"
                    ),
                    {"training_job_id": training_job_id},
                )
            ).first()
        if row is None:
            raise PermanentJobError("job_failed")
        return _RunSettings(window_days=int(row[0]), max_epochs=int(row[1]))

    @contextlib.contextmanager
    def _scratch(self) -> Iterator[pathlib.Path]:
        """A working directory that is deleted however the run ends.

        Checkpoints live in the object store; this is only the local copy the
        loop reads and writes. Leaving them on a worker's disk would make a
        resumed job depend on landing on the same host, which is the one thing
        a resumable job must not depend on.
        """
        with tempfile.TemporaryDirectory(dir=self._workspace) as name:
            yield pathlib.Path(name)


@dataclass(frozen=True, slots=True)
class _RunSettings:
    window_days: int
    max_epochs: int


class _Flag:
    """A boolean set from one thread and read from another.

    No lock. It is written once, never cleared, and a reader that misses the
    write by one epoch loses nothing that a stage boundary will not catch.
    """

    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set


def _training_job_id(ctx: JobContext) -> uuid.UUID:
    """The payload carries one field, and a job without it cannot be run.

    Permanent rather than retryable: a malformed payload is malformed on every
    attempt, and spending three of them proving that helps nobody.
    """
    raw = ctx.payload.get("training_job_id")
    if raw is None:
        raise PermanentJobError("job_failed")
    return uuid.UUID(str(raw))


def _is_curve_metric(name: str) -> bool:
    """Whether a measured value belongs on the stored curve.

    A filter rather than a pass-through: `Metrics` is free to grow a diagnostic
    nobody asked to persist, and `training_metrics` is a table a tenant reads.
    """
    match = _AT_K.match(name)
    return (match.group("family") if match else name) in CURVE_METRICS


def _export_matrix(model: DGSR) -> torch.Tensor:
    """The item matrix, detached and contiguous, with no autograd graph attached.

    `no_grad` because an exported tensor that still remembers how it was
    computed is both larger than it needs to be and impossible to serialise.
    """
    with torch.no_grad():
        return model.item_matrix().detach().contiguous()


def _error_reference(training_job_id: uuid.UUID) -> str:
    """L1697's shape: `err-` plus a short, stable suffix of the job.

    Derived from the identifier rather than random, so a tenant quoting it twice
    quotes the same string and support can find the run without a lookup table.
    """
    return f"err-{training_job_id.hex[:4]}-{training_job_id.hex[4:8]}"


def _copy(exc: PermanentJobError | None) -> str:
    """`failure_reason` is shown to a tenant (L1697), so it is approved copy.

    Not `str(exc)`. The catalogue is the only text that has been through product
    review, and a failure is exactly the moment a raw exception string would
    otherwise reach somebody who cannot act on it.
    """
    if exc is None:
        return resolve_copy("job_failed")
    return resolve_copy(exc.code, **exc.copy_args)


__all__ = [
    "BASELINE_EPOCH",
    "CURVE_METRICS",
    "Rail",
    "StageOutcome",
    "TrainingPipeline",
]
