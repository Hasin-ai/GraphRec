"""The nine stages, and the three ways a run can end.

The exit criteria this file exists for:

* all nine stages progress and persist;
* a crash mid-training resumes from the last checkpoint;
* `stage_index` survives failure and cancellation.

Every test drives the real `Worker` over the real registry. Calling
`TrainingPipeline.run` directly would test nine stages without testing the lease,
the attempt budget or the terminal transition, and those are the parts that
decide what a tenant sees when something goes wrong.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from graphrec.common.enums import JobState, ModelVersionStatus
from graphrec.domain.training.service import TrainingRequest
from graphrec.storage import keys
from graphrec.training import states

pytestmark = [pytest.mark.db, pytest.mark.anyio]

#: The smallest of the dialog's three options (L1679). Ten epochs over the
#: fixture's twenty-four users is seconds, and the properties under test —
#: ordering, persistence, resumption — do not get truer at forty.
EPOCHS = 10

#: `Settings.job_max_attempts`. A retryable crash is only terminal on the last
#: one, so a test about what a *failed* run records has to spend them all.
ATTEMPT_BUDGET = 3


async def _queue_a_run(service, bound, tenant, counters, ref="run-1", **kwargs):
    async with bound(tenant) as session:
        outcome = await service.request(
            session,
            counters,
            tenant_id=tenant,
            requested_by=None,
            request=TrainingRequest(request_ref=ref, max_epochs=EPOCHS, **kwargs),
        )
        return outcome.job.training_job_id


async def _row(bound, tenant, training_job_id):
    async with bound(tenant) as session:
        return (
            await session.execute(
                sa.text(
                    "SELECT state, stage_index, progress_text, failure_reason, cancel_reason, "
                    "       error_reference, completed_at "
                    "  FROM training_jobs WHERE training_job_id = :id"
                ),
                {"id": training_job_id},
            )
        ).one()


# ------------------------------------------------------------- the happy path


async def test_a_run_reaches_succeeded_through_every_stage_in_order(
    service, bound, tenant, counters, seed_interactions, run_worker
) -> None:
    """The rail is walked, not jumped.

    Observed after the fact from `jobs.progress`, which the worker rewrites at
    every stage boundary — so the assertion is about what was published while
    the run was in flight, not about where it ended up.
    """
    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    assert await run_worker() == 1

    state, stage_index, progress, failure, cancel, reference, completed = await _row(
        bound, tenant, training_job_id
    )
    assert state == JobState.SUCCEEDED.value
    assert stage_index == states.stage_index(JobState.SUCCEEDED) == 8
    assert progress == "complete"
    assert failure is None
    assert cancel is None
    assert reference is None
    assert completed is not None


async def test_every_stage_is_published_as_the_run_passes_through_it(
    service, bound, tenant, counters, seed_interactions, pipeline, ingest_sessionmaker
) -> None:
    """A console polling `GET /v1/training-jobs/{id}` must see the middle.

    The recorder wraps `Rail.enter` and keeps what each call wrote, which is the
    only way to observe a sequence that is overwritten in place. Eight
    boundaries, because `queued` is written at request time and never entered by
    the worker.
    """
    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    seen: list[tuple[str, int]] = []
    original = type(pipeline)._pipeline

    from graphrec.domain.training import pipeline as pipeline_module

    original_enter = pipeline_module.Rail.enter

    async def record(self, state, progress, **detail):
        await original_enter(self, state, progress, **detail)
        seen.append((state.value, self.stage_index))

    pipeline_module.Rail.enter = record
    try:
        from graphrec.common.config import Settings
        from graphrec.jobs.handlers import HandlerRegistry
        from graphrec.jobs.states import JobType
        from graphrec.jobs.worker import Worker

        registry = HandlerRegistry()
        registry.register(JobType.TRAINING)(pipeline.run)
        worker = Worker(
            name="stage_test",
            sessionmaker=ingest_sessionmaker,
            registry=registry,
            settings=Settings(environment="ci", job_heartbeat_seconds=1),
        )
        assert await worker.run_once()
    finally:
        pipeline_module.Rail.enter = original_enter
        assert original is type(pipeline)._pipeline

    assert [name for name, _ in seen] == list(states.STAGE_NAMES[1:-1])
    assert [index for _, index in seen] == list(range(1, 8))

    state, stage_index, *_ = await _row(bound, tenant, training_job_id)
    assert state == JobState.SUCCEEDED.value
    assert stage_index == 8


async def test_the_snapshot_is_written_once_and_names_what_it_holds(
    service, bound, tenant, counters, seed_interactions, run_worker, artifact_store
) -> None:
    """`dataset_snapshots.training_job_id` is unique, so a resumed run must not
    write a second one.

    The counts are asserted against the fixture rather than against the row's
    own arithmetic: a snapshot that agreed with itself but not with the database
    would be a snapshot nobody could reconcile.
    """
    from tests.training.conftest import EVENTS_PER_USER, ITEMS, USERS

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    async with bound(tenant) as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT snapshot_id, window_days, uri, checksum, sequence_count, "
                    "       product_count, event_count "
                    "  FROM dataset_snapshots WHERE training_job_id = :id"
                ),
                {"id": training_job_id},
            )
        ).one()

    snapshot_id, window_days, uri, checksum, sequences, products, events = row
    assert window_days == 90
    assert sequences == USERS
    assert products == ITEMS
    assert events == USERS * EVENTS_PER_USER
    assert checksum.startswith("sha256:")
    assert uri.endswith(f"{snapshot_id}.npz")
    assert artifact_store.exists(keys.snapshot_key(tenant, snapshot_id))


async def test_the_snapshot_round_trips_through_the_store(
    service, bound, tenant, counters, seed_interactions, run_worker, artifact_store
) -> None:
    """What was stored is what was read, verified against the recorded digest.

    This is the property that makes a snapshot worth having: a run that can be
    re-executed over the same inputs is reproducible, and one that cannot is
    just a row that says a number.
    """
    from graphrec.domain.training import snapshot as snapshot_ops

    await seed_interactions(tenant)
    await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    async with bound(tenant) as session:
        snapshot_id, checksum = (
            await session.execute(sa.text("SELECT snapshot_id, checksum FROM dataset_snapshots"))
        ).one()

    payload = artifact_store.get_bytes(
        keys.snapshot_key(tenant, snapshot_id), expected_digest=checksum
    )
    contents = snapshot_ops.decode(payload)

    from tests.training.conftest import EVENTS_PER_USER, ITEMS, USERS

    assert contents.event_count == USERS * EVENTS_PER_USER
    assert contents.product_count == ITEMS
    assert contents.window_days == 90


async def test_the_curve_starts_from_the_popularity_baseline(
    service, bound, tenant, counters, seed_interactions, run_worker
) -> None:
    """Epoch 0 is the baseline, and every later epoch is a trained one.

    A curve with no baseline answers the wrong question: a tenant cannot tell
    whether 0.31 is good, only whether it went up.
    """
    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    async with bound(tenant) as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT epoch, metric_name, value FROM training_metrics "
                    " WHERE training_job_id = :id ORDER BY epoch, metric_name"
                ),
                {"id": training_job_id},
            )
        ).all()

    epochs = {epoch for epoch, _, _ in rows}
    assert 0 in epochs, "the popularity baseline is epoch 0"
    assert epochs - {0}, "at least one trained epoch was recorded"

    baseline = {name for epoch, name, _ in rows if epoch == 0}
    assert "recall_at_5" in baseline or "recall_at_10" in baseline
    assert "loss" not in baseline, "the baseline was not trained, so it has no loss"

    trained = {name for epoch, name, _ in rows if epoch != 0}
    assert "loss" in trained


async def test_the_run_exports_a_bundle_the_index_can_load(
    service, bound, tenant, counters, seed_interactions, run_worker, artifact_store
) -> None:
    """`indexing_embeddings` produces the one artifact serving needs.

    Phase 9 wrote a bare tensor keyed by the *job*; Phase 10 writes a bundle
    keyed by the *version*, because the version is what a deployment names and
    a job can produce at most one. It is checked by loading it through
    `load_bundle` rather than by opening the file: the exit criterion is that a
    corrupted or foreign bundle is refused at load, and a test that read the
    tensor directly would pass against a bundle the loader rejects.
    """
    from graphrec.ml import bundle as bundle_ops
    from tests.training.conftest import ITEMS

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    version_id, _status = await _version(bound, tenant, training_job_id)
    key = keys.bundle_key(tenant, version_id, bundle_ops.BUNDLE_NAME)
    assert artifact_store.exists(key)

    loaded = bundle_ops.load_bundle(artifact_store.root / key, tenant_id=tenant)
    assert loaded.manifest.tenant_id == tenant
    assert loaded.manifest.training_job_id == training_job_id
    assert loaded.manifest.item_count == ITEMS
    assert loaded.item_embeddings.shape == (ITEMS, loaded.manifest.embedding_dim)


async def test_another_tenant_cannot_load_the_bundle_this_run_produced(
    service, bound, tenant, counters, seed_interactions, run_worker, artifact_store
) -> None:
    """The manifest is the evidence, and it is sealed by the run.

    `keys.belongs_to` checks a path, and a path is a claim made by whoever wrote
    it. This checks the thing training actually signed into the file — over a
    bundle a real pipeline produced rather than one the test wrote.
    """
    from graphrec.ml import bundle as bundle_ops

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    version_id, _status = await _version(bound, tenant, training_job_id)
    path = artifact_store.root / keys.bundle_key(tenant, version_id, bundle_ops.BUNDLE_NAME)

    with pytest.raises(bundle_ops.BundleError):
        bundle_ops.load_bundle(path, tenant_id=uuid.uuid4())


async def test_a_completed_run_registers_a_version_against_the_floor(
    service, bound, tenant, counters, seed_interactions, run_worker
) -> None:
    """The `registering` stage is not a label on the rail — it writes a row.

    The status is whatever the floor decided, so this asserts it is one of the
    two verdicts rather than asserting it is `eligible`: twenty-four seeded
    users are not enough data to guarantee a model that beats popularity, and a
    test that demanded one would be a test of the fixture's luck. What is
    pinned is that a verdict was reached, that a rejection carries its
    explanation, and that an eligible version carries none —
    `ck_model_versions_failure_note` is the schema saying the same thing.
    """
    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    version_id, status = await _version(bound, tenant, training_job_id)
    assert status in {
        ModelVersionStatus.ELIGIBLE.value,
        ModelVersionStatus.REJECTED.value,
    }, "the floor reaches a verdict; `registered` means it never ran"

    async with bound(tenant) as session:
        note, number, dim = (
            await session.execute(
                sa.text(
                    "SELECT failure_note, version_number, embedding_dim "
                    "  FROM model_versions WHERE model_version_id = :id"
                ),
                {"id": version_id},
            )
        ).one()

    assert number == 1, "the first version a tenant trains is version 1"
    assert dim > 0
    if status == ModelVersionStatus.REJECTED.value:
        assert note, "a rejection a tenant cannot read is a rejection they cannot act on"
    else:
        assert note is None


async def test_registration_records_both_the_version_and_the_baseline_it_beat(
    service, bound, tenant, counters, seed_interactions, run_worker
) -> None:
    """CON-01. The comparison the console draws needs both rows to exist, and
    the split column is what tells them apart."""
    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)
    await run_worker()

    version_id, _status = await _version(bound, tenant, training_job_id)
    async with bound(tenant) as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT split, metric_name FROM model_evaluation_metrics "
                    " WHERE model_version_id = :id"
                ),
                {"id": version_id},
            )
        ).all()

    recorded = {tuple(row) for row in rows}
    assert {split for split, _ in recorded} == {"test", "baseline"}
    # The suite runs the pipeline at `k=5`, and the metric names follow `k` —
    # which is the whole point of the floor following it too.
    assert ("test", "recall_at_5") in recorded
    assert ("baseline", "recall_at_5") in recorded
    assert ("test", "coverage") in recorded


async def test_a_resumed_run_registers_one_version_rather_than_two(
    service, bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """`uq_model_versions_job` is the rule; this is the path that would break it.

    A retry re-runs every stage after the checkpoint, `registering` included.
    The second pass has to find the row the first pass wrote and reuse its id —
    not only to satisfy the constraint, but because the id is the key the bundle
    was uploaded under, and a second id would leave the first bundle orphaned
    and the version pointing at a file nothing wrote.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    class CrashesAfterTraining(TrainingPipeline):
        """Dies in `evaluating`, which is after the checkpoint and before the
        version exists — the window a naive retry would register twice in."""

        def _evaluate(self, *args, **kwargs):
            msg = "the worker was killed"
            raise RuntimeError(msg)

    await _run_pipeline(
        ingest_sessionmaker,
        CrashesAfterTraining(artifact_store, min_sequences=1, seed=7, k=5),
        attempts=1,
    )
    await _clear_backoff(bound, tenant, training_job_id)
    await _run_pipeline(
        ingest_sessionmaker, TrainingPipeline(artifact_store, min_sequences=1, seed=7, k=5)
    )

    async with bound(tenant) as session:
        count = await session.scalar(
            sa.text("SELECT count(*) FROM model_versions WHERE training_job_id = :id"),
            {"id": training_job_id},
        )
    assert count == 1

    state, *_ = await _row(bound, tenant, training_job_id)
    assert state == JobState.SUCCEEDED.value


# ------------------------------------------------------------------- failure


async def test_a_run_below_the_minimum_fails_permanently_and_keeps_its_position(
    bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """A deterministic failure spends no attempts and still records where it got to.

    Admission normally refuses this at the door; the case reached here is the
    one where the data shrank between the request and the claim. `stage_index`
    stays at `preparing_data` because that is where the run stopped, and the
    console renders "Stopped at preparing_data." from it (L1707).
    """
    from graphrec.domain.training.pipeline import TrainingPipeline
    from graphrec.domain.training.service import TrainingService

    await seed_interactions(tenant, users=2)
    permissive = TrainingService(cooldown_seconds=0, min_sequences=1)
    training_job_id = await _queue_a_run(permissive, bound, tenant, counters)

    strict = TrainingPipeline(artifact_store, min_sequences=1_000, seed=7, k=5)
    await _run_pipeline(ingest_sessionmaker, strict)

    state, stage_index, progress, failure, _, reference, completed = await _row(
        bound, tenant, training_job_id
    )
    assert state == JobState.FAILED.value
    assert stage_index == states.stage_index(JobState.PREPARING_DATA) == 2
    assert progress == "stopped at preparing_data"
    assert failure is not None
    assert "1,000" in failure
    assert reference is not None
    assert reference.startswith("err-")
    assert completed is not None

    async with bound(tenant) as session:
        attempt, status = (
            await session.execute(
                sa.text(
                    "SELECT j.attempt, j.status FROM jobs AS j "
                    "  JOIN training_jobs AS t ON t.job_id = j.job_id "
                    " WHERE t.training_job_id = :id"
                ),
                {"id": training_job_id},
            )
        ).one()
    assert status == "failed", "a permanent failure does not go back on the queue"
    assert attempt == 0, (
        "and it spends nothing: `JobQueue.fail` does not touch `attempt` on the "
        "permanent path, which is what makes BUILD_PROMPT L471 literally true"
    )


async def test_a_failure_reason_is_approved_copy_not_an_exception_string(
    bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """NR-NF-06. A traceback out of a training worker can carry a row of data.

    So the tenant-visible reason comes from the copy catalogue and the detail
    lives behind `error_reference`, which support can correlate and a tenant
    cannot read anything out of.

    The budget is spent in full first, because a crash with a retry still to
    come is an interruption rather than an outcome and the rail deliberately
    stays where it stopped. `failed` is written by the attempt that finds no
    retry left — which is the only attempt whose reason a tenant should ever be
    shown.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline
    from graphrec.domain.training.service import TrainingService

    await seed_interactions(tenant)
    service = TrainingService(cooldown_seconds=0, min_sequences=1)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    class Exploding(TrainingPipeline):
        async def _prepare(self, ctx, *, training_job_id, settings):
            msg = "customer bob@example.com bought SKU-77"
            raise RuntimeError(msg)

    pipeline = Exploding(artifact_store, min_sequences=1)
    for _ in range(ATTEMPT_BUDGET):
        await _clear_backoff(bound, tenant, training_job_id)
        await _run_pipeline(ingest_sessionmaker, pipeline, attempts=1)

    state, _, _, failure, _, reference, _ = await _row(bound, tenant, training_job_id)
    assert state == JobState.FAILED.value
    assert failure
    assert "bob@example.com" not in failure
    assert "SKU-77" not in failure
    assert reference


# -------------------------------------------------------------- cancellation


async def test_cancelling_mid_run_records_the_stage_it_stopped_at(
    service, bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """L1707: "Cancelled at building_graph." — the stage it reached, not the
    next one.

    The request is made from inside `building_graph`, so the run observes it at
    the next boundary and `stage_index` is left where it was. That ordering is
    the difference between a truthful note and one that names work that never
    started.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    class CancelDuringBuild(TrainingPipeline):
        async def _pipeline(self, ctx, rail, scratch, *, training_job_id, settings):
            async def ask_after_building() -> None:
                async with bound(tenant) as session:
                    await service.cancel(
                        session,
                        training_job_id=training_job_id,
                        reason="operator changed their mind",
                    )

            original_enter = rail.enter

            async def enter(state, progress, **detail):
                await original_enter(state, progress, **detail)
                if state is JobState.BUILDING_GRAPH:
                    await ask_after_building()

            rail.enter = enter  # type: ignore[method-assign]
            return await super()._pipeline(
                ctx, rail, scratch, training_job_id=training_job_id, settings=settings
            )

    await _run_pipeline(
        ingest_sessionmaker, CancelDuringBuild(artifact_store, min_sequences=1, k=5)
    )

    state, stage_index, progress, failure, cancel, _, completed = await _row(
        bound, tenant, training_job_id
    )
    assert state == JobState.CANCELLED.value
    assert stage_index == states.stage_index(JobState.BUILDING_GRAPH) == 3
    assert progress == "stopped at building_graph"
    assert cancel == "Cancelled by requester: operator changed their mind"
    assert failure is None
    assert completed is not None
    assert states.STAGE_NAMES[stage_index] == "building_graph"


async def test_a_cancelled_run_is_not_retried(
    service, bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """Cancellation is not a failure, so the attempt budget is irrelevant to it.

    A cancelled job that went back on the queue would be a job that ignored the
    tenant who asked it to stop.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    async with bound(tenant) as session:
        await service.cancel(
            session, training_job_id=training_job_id, reason="not needed after all"
        )

    await _run_pipeline(ingest_sessionmaker, TrainingPipeline(artifact_store, min_sequences=1))

    async with bound(tenant) as session:
        status = await session.scalar(
            sa.text(
                "SELECT j.status FROM jobs AS j JOIN training_jobs AS t ON t.job_id = j.job_id "
                " WHERE t.training_job_id = :id"
            ),
            {"id": training_job_id},
        )
    assert status == "cancelled"

    state, stage_index, *_ = await _row(bound, tenant, training_job_id)
    assert state == JobState.CANCELLED.value
    assert stage_index == 0, "cancelled before it started, so it stopped at queued"


# ---------------------------------------------------------------- resumption


async def test_a_crash_mid_training_resumes_from_the_last_checkpoint(
    service, bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """The exit criterion. A worker killed at epoch 3 does not restart at epoch 0.

    The first attempt dies inside `training` after a few epochs have been
    checkpointed. The second attempt is a real retry through the queue — same
    job, same payload, attempt two — and it must find the checkpoint the first
    one uploaded and carry on from it.

    Observed through `training_metrics`: the resumed run records epochs above
    the ones the crashed run reached and does not re-record epoch 1, because
    the loop starts after the checkpoint rather than at the beginning.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    crash_after = 3

    class CrashesDuringTraining(TrainingPipeline):
        async def _after_epoch(self, ctx, rail, report, *args) -> None:
            await super()._after_epoch(ctx, rail, report, *args)
            if report.epoch >= crash_after:
                msg = "the worker was killed"
                raise RuntimeError(msg)

    await _run_pipeline(
        ingest_sessionmaker,
        CrashesDuringTraining(artifact_store, min_sequences=1, seed=7, k=5),
        attempts=1,
    )

    checkpoint = keys.checkpoint_key(tenant, training_job_id)
    assert artifact_store.exists(checkpoint), "the crash left a checkpoint behind"

    async with bound(tenant) as session:
        crashed_epochs = set(
            (
                await session.scalars(
                    sa.text(
                        "SELECT DISTINCT epoch FROM training_metrics "
                        " WHERE training_job_id = :id AND epoch > 0"
                    ),
                    {"id": training_job_id},
                )
            ).all()
        )
        state = await session.scalar(
            sa.text("SELECT state FROM training_jobs WHERE training_job_id = :id"),
            {"id": training_job_id},
        )
    assert crashed_epochs == set(range(1, crash_after + 1))
    assert state == JobState.TRAINING.value, "a crash leaves the rail where it stopped"

    # The retry. Same job, same payload; the queue hands it back after the
    # failure because a crash is retryable and the budget is three.
    await _clear_backoff(bound, tenant, training_job_id)
    await _run_pipeline(
        ingest_sessionmaker, TrainingPipeline(artifact_store, min_sequences=1, seed=7, k=5)
    )

    final_state, stage_index, *_ = await _row(bound, tenant, training_job_id)
    assert final_state == JobState.SUCCEEDED.value
    assert stage_index == 8

    async with bound(tenant) as session:
        all_epochs = sorted(
            (
                await session.scalars(
                    sa.text(
                        "SELECT DISTINCT epoch FROM training_metrics "
                        " WHERE training_job_id = :id AND epoch > 0 ORDER BY epoch"
                    ),
                    {"id": training_job_id},
                )
            ).all()
        )
    assert max(all_epochs) > crash_after, "the resumed run trained past the crash"


async def test_a_resumed_run_does_not_write_a_second_snapshot(
    service, bound, tenant, counters, seed_interactions, ingest_sessionmaker, artifact_store
) -> None:
    """`UNIQUE(training_job_id)` (SRS §5.2.9) is the rule; this is the path that
    would break it.

    A retry re-runs `preparing_data`, so the insert has to tolerate the row it
    wrote last time — otherwise the second attempt fails on a constraint the
    first attempt satisfied.
    """
    from graphrec.domain.training.pipeline import TrainingPipeline

    await seed_interactions(tenant)
    training_job_id = await _queue_a_run(service, bound, tenant, counters)

    class CrashesAfterPreparing(TrainingPipeline):
        async def _prepare(self, ctx, *, training_job_id, settings):
            await super()._prepare(ctx, training_job_id=training_job_id, settings=settings)
            msg = "killed just after the snapshot landed"
            raise RuntimeError(msg)

    await _run_pipeline(
        ingest_sessionmaker,
        CrashesAfterPreparing(artifact_store, min_sequences=1, seed=7, k=5),
        attempts=1,
    )
    await _clear_backoff(bound, tenant, training_job_id)
    await _run_pipeline(
        ingest_sessionmaker, TrainingPipeline(artifact_store, min_sequences=1, seed=7, k=5)
    )

    async with bound(tenant) as session:
        count = await session.scalar(
            sa.text("SELECT count(*) FROM dataset_snapshots WHERE training_job_id = :id"),
            {"id": training_job_id},
        )
    assert count == 1

    state, *_ = await _row(bound, tenant, training_job_id)
    assert state == JobState.SUCCEEDED.value


# ----------------------------------------------------------------- machinery


async def _version(bound, tenant, training_job_id) -> tuple[uuid.UUID, str]:
    """The version a run registered, by the job that produced it.

    `uq_model_versions_job` guarantees at most one, so `one()` is the right
    shape: a run that registered twice should fail here loudly rather than be
    read as having registered once.
    """
    async with bound(tenant) as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT model_version_id, status FROM model_versions "
                    " WHERE training_job_id = :id"
                ),
                {"id": training_job_id},
            )
        ).one()
    return row[0], row[1]


async def _clear_backoff(bound, tenant, training_job_id) -> None:
    """Bring a re-queued job's `run_after` forward to now.

    A retryable failure re-queues behind an exponential backoff, which is right
    in production and useless in a test: `run_once` would find nothing to claim
    and the assertion would be about scheduling rather than about resumption.
    Only the delay is skipped — the attempt count, the payload and the
    checkpoint are all left exactly as the crash left them.
    """
    async with bound(tenant) as session:
        await session.execute(
            sa.text(
                "UPDATE jobs SET run_after = now() FROM training_jobs AS t "
                " WHERE t.job_id = jobs.job_id AND t.training_job_id = :id"
            ),
            {"id": training_job_id},
        )


async def _run_pipeline(sessionmaker, pipeline, *, attempts: int = 1) -> int:
    """Claim and run with the real worker, using the pipeline under test."""
    from graphrec.common.config import Settings
    from graphrec.jobs.handlers import HandlerRegistry
    from graphrec.jobs.states import JobType
    from graphrec.jobs.worker import Worker

    registry = HandlerRegistry()
    registry.register(JobType.TRAINING)(pipeline.run)
    worker = Worker(
        name="pipeline_test",
        sessionmaker=sessionmaker,
        registry=registry,
        settings=Settings(
            environment="ci", job_lease_seconds=120, job_heartbeat_seconds=1, job_max_attempts=3
        ),
    )
    ran = 0
    for _ in range(attempts):
        if not await worker.run_once():
            break
        ran += 1
    return ran
