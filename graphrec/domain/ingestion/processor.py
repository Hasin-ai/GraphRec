"""The two ingestion handlers: validate in chunks, stage, merge once.

The shape is the same for both kinds and the difference is two functions — which
validator decides an item is usable, and which merge applies the staged set — so
it is written once.

**Where each write goes is deliberate, and there are two destinations.**

*The handler's transaction* carries everything that must be true together: the
staged items, the merged rows, the per-item errors, and the final counts. Either
all of that commits or none of it does, which is what makes a retry safe — a job
that died mid-merge left nothing behind for anyone to reconcile.

*The control transaction* (`ctx.control()`) carries the stage the submission has
reached, and it commits immediately. A tenant polling the submission page
through a long merge has to see `validating` and then `applying`; if the status
lived in the handler's transaction they would see `received` until everything
appeared at once. It is also what lets a *failed* job leave behind a submission
that says it failed, rather than one stuck at `received` forever.

The two cannot disagree about anything that matters, because the control
transaction only ever writes the stage — never a count. Counts are written once,
at the end, by the transaction that produced them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.config import get_settings
from graphrec.common.enums import SubmissionKind, SubmissionStatus, UsageType
from graphrec.common.ids import uuid7
from graphrec.common.logging import get_logger
from graphrec.db.models import IngestStagingItem, Submission
from graphrec.domain import quotas
from graphrec.domain.ingestion import merge as merges
from graphrec.domain.ingestion.merge import ErrorRecorder, MergeCounts
from graphrec.domain.ingestion.service import SYNC_MODE_UPSERT_AND_DISABLE_MISSING
from graphrec.domain.ingestion.validation import (
    ItemInvalid,
    normalise_event,
    normalise_product,
    reference_for,
)
from graphrec.jobs.failures import JobCancelled, PermanentJobError, classify

if TYPE_CHECKING:
    from graphrec.jobs.handlers import JobContext

logger = get_logger(__name__)

#: How many items are held in memory at once. Independent of the collection
#: bound on purpose: memory bounded by the size of the input is not bounded, and
#: the day the 5,000-item limit is raised for one plan this number should not
#: have to be revisited.
VALIDATION_CHUNK = 500

#: Read the submitted collection a window at a time, expanding the JSONB array
#: in the database rather than pulling it into the worker. `WITH ORDINALITY` is
#: what gives every item a stable position — which is what a failure is reported
#: under, and what makes the error samples orderable back into send order.
_ITEM_WINDOW = sa.text(
    """
    SELECT e.ord - 1 AS ordinal, e.elem AS item
    FROM submissions s,
         LATERAL jsonb_array_elements(s.raw_payload -> 'items') WITH ORDINALITY AS e(elem, ord)
    WHERE s.submission_id = :submission_id
    ORDER BY e.ord
    OFFSET :offset
    LIMIT :chunk
    """
)


async def process_event_batch(ctx: JobContext) -> dict[str, Any]:
    """`POST /v1/events/batches` — the deferred half."""
    return await _process(ctx, kind=SubmissionKind.EVENT_BATCH)


async def process_product_bulk_upsert(ctx: JobContext) -> dict[str, Any]:
    """`POST /v1/products:bulk-upsert` — the deferred half."""
    return await _process(ctx, kind=SubmissionKind.PRODUCT_SYNC)


async def _process(ctx: JobContext, *, kind: SubmissionKind) -> dict[str, Any]:
    submission = await _load(ctx, kind=kind)

    if submission.is_terminal():
        # A job may be delivered twice — a lease that lapsed while its worker
        # was merely slow is the ordinary case. The submission, not the job row,
        # is the record of whether the work happened, so a finished one is
        # reported back rather than redone.
        logger.info(
            "submission_already_finished",
            extra={"submission_id": str(submission.submission_id), "status": submission.status},
        )
        return _progress(submission)

    try:
        return await _run(ctx, submission=submission, kind=kind)
    except JobCancelled:
        await _mark_failed(ctx, submission_id=submission.submission_id, code="job_cancelled")
        raise
    except Exception as exc:
        # The submission's own record of the failure, written outside the
        # transaction that is about to roll back. `classify` resolves the code
        # the job row will carry, so the two agree; the exception's text is
        # never stored and never logged into it (NR-NF-06).
        await _mark_failed(ctx, submission_id=submission.submission_id, code=classify(exc).code)
        raise


async def _load(ctx: JobContext, *, kind: SubmissionKind) -> Submission:
    """Fetch the submission this job is about, through the tenant's own policy.

    A missing row is permanent, not retryable. The session is tenant-bound, so
    "missing" covers both "deleted" and "belongs to someone else" — and neither
    becomes visible by trying again.
    """
    try:
        submission_id = uuid.UUID(str(ctx.payload.get("submission_id")))
    except ValueError:  # pragma: no cover - only reachable from a malformed enqueue
        raise PermanentJobError("job_failed") from None

    submission = await ctx.session.scalar(
        sa.select(Submission).where(Submission.submission_id == submission_id)
    )
    if submission is None or submission.submission_kind is not kind:
        raise PermanentJobError("job_failed")
    return submission


async def _run(ctx: JobContext, *, submission: Submission, kind: SubmissionKind) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    recorder = ErrorRecorder(
        tenant_id=ctx.tenant_id,
        submission_id=submission.submission_id,
        cap=get_settings().max_submission_error_samples,
    )

    await _advance(ctx, submission=submission, status=SubmissionStatus.VALIDATING)
    refused = await _validate(ctx, submission=submission, kind=kind, recorder=recorder, now=now)

    await _advance(ctx, submission=submission, status=SubmissionStatus.APPLYING)
    applied = await _merge(ctx, submission=submission, kind=kind, recorder=recorder, now=now)

    await _complete(
        ctx,
        submission=submission,
        counts=MergeCounts(failed=refused) + applied,
        kept=recorder.kept,
        now=now,
    )
    return _progress(submission)


# ------------------------------------------------------------------- passes


async def _validate(
    ctx: JobContext,
    *,
    submission: Submission,
    kind: SubmissionKind,
    recorder: ErrorRecorder,
    now: dt.datetime,
) -> int:
    """Stream the collection, validate it, and stage what survives.

    Returns how many items were refused outright. The refusals themselves are
    sampled as they are found, in order, because a tenant looking at a
    submission that failed four thousand times needs the first hundred to be the
    first hundred *they sent* — not whichever hundred some later pass reached
    first.
    """
    id_field = "event_id" if kind is SubmissionKind.EVENT_BATCH else "external_id"
    offset = 0
    refused = 0

    while True:
        rows = (
            await ctx.session.execute(
                _ITEM_WINDOW,
                {
                    "submission_id": submission.submission_id,
                    "offset": offset,
                    "chunk": VALIDATION_CHUNK,
                },
            )
        ).all()
        if not rows:
            break

        staged: list[dict[str, Any]] = []
        for ordinal, raw in rows:
            try:
                item = (
                    normalise_event(raw, now=now)
                    if kind is SubmissionKind.EVENT_BATCH
                    else normalise_product(raw)
                )
            except ItemInvalid as exc:
                refused += 1
                await recorder.record(
                    ctx.session,
                    ordinal=ordinal,
                    item_reference=reference_for(raw, ordinal=ordinal, id_field=id_field),
                    code=exc.code,
                )
                continue
            staged.append(
                {
                    "staging_item_id": uuid7(),
                    "tenant_id": ctx.tenant_id,
                    "submission_id": submission.submission_id,
                    "ordinal": ordinal,
                    "item": item,
                }
            )

        if staged:
            await ctx.session.execute(sa.insert(IngestStagingItem), staged)

        offset += len(rows)
        # One cancellation boundary and one lease renewal per chunk. Both
        # matter: five thousand items is minutes of work, and a handler that
        # never reaches a boundary can neither be stopped nor prove it is alive.
        await ctx.stage(
            SubmissionStatus.VALIDATING.value,
            submission_id=str(submission.submission_id),
            validated=offset,
            failed=refused,
        )

    return refused


async def _merge(
    ctx: JobContext,
    *,
    submission: Submission,
    kind: SubmissionKind,
    recorder: ErrorRecorder,
    now: dt.datetime,
) -> MergeCounts:
    await ctx.stage(SubmissionStatus.APPLYING.value, submission_id=str(submission.submission_id))

    if kind is SubmissionKind.EVENT_BATCH:
        return await merges.merge_events(
            ctx.session,
            tenant_id=ctx.tenant_id,
            submission_id=submission.submission_id,
            now=now,
            recorder=recorder,
        )

    await _assert_product_quota(ctx, submission=submission, now=now)
    return await merges.merge_products(
        ctx.session,
        tenant_id=ctx.tenant_id,
        submission_id=submission.submission_id,
        reference=submission.external_reference,
        now=now,
        disable_missing=(submission.options or {}).get("mode")
        == SYNC_MODE_UPSERT_AND_DISABLE_MISSING,
        recorder=recorder,
    )


async def _assert_product_quota(
    ctx: JobContext, *, submission: Submission, now: dt.datetime
) -> None:
    """Check the quota against what the merge *would* create, in its own transaction.

    Same reasoning as `CatalogService._assert_product_quota` (ER-F-11): a count
    taken in one transaction and an insert made in another is how two concurrent
    submissions both see room for five hundred products and commit a thousand.
    Here the count is `count_new_products`, which excludes staged items that
    match a product the tenant already has — an upsert of the existing
    catalogue consumes no new quota, however large the file.

    A submission that would exceed the limit fails **whole**. Applying the first
    n items and refusing the rest would leave a catalogue that is neither what
    the tenant had nor what they sent, with nothing to say where the cut fell.
    """
    limit = await quotas.effective_limit(
        ctx.session, tenant_id=ctx.tenant_id, usage_type=UsageType.PRODUCTS, now=now
    )
    if limit is None:
        return

    used = int(
        await ctx.session.scalar(sa.text("SELECT count(*) FROM products WHERE deleted_at IS NULL"))
        or 0
    )
    incoming = await merges.count_new_products(ctx.session, submission_id=submission.submission_id)
    if used + incoming <= limit:
        return

    raise PermanentJobError(
        "product_quota_exhausted",
        used=f"{used + incoming:,}",
        limit=f"{limit:,}",
        plan_code=await quotas.plan_code(ctx.session, tenant_id=ctx.tenant_id),
    )


# -------------------------------------------------------------- bookkeeping


async def _advance(ctx: JobContext, *, submission: Submission, status: SubmissionStatus) -> None:
    """Publish the stage immediately, on the control transaction.

    Guarded on `completed_at IS NULL`, so a stage write that races a completion
    cannot revive a submission that has already finished.
    """
    async with ctx.control() as control:
        await control.execute(
            sa.text(
                "UPDATE submissions SET status = :status, updated_at = now() "
                "WHERE submission_id = :submission_id AND completed_at IS NULL"
            ),
            {"status": status.value, "submission_id": submission.submission_id},
        )


async def _mark_failed(ctx: JobContext, *, submission_id: uuid.UUID, code: str) -> None:
    """Record a terminal failure outside the transaction that is rolling back.

    Best effort by design. If this write fails too, the job's own failure is
    still recorded by the worker and the submission is left mid-stage, which a
    retry or the reconciler can still resolve. Raising from here would replace a
    meaningful failure with a meaningless one.

    The payload is cleared on the way past: a submission that will never be
    applied has no further use for the tenant's raw data.
    """
    try:
        async with ctx.control() as control:
            await control.execute(
                sa.text(
                    "UPDATE submissions SET status = 'failed', failure_code = :code, "
                    "    completed_at = now(), raw_payload = NULL, updated_at = now() "
                    "WHERE submission_id = :submission_id AND completed_at IS NULL"
                ),
                {"code": code, "submission_id": submission_id},
            )
    except Exception:  # pragma: no cover - defensive
        logger.exception("submission_failure_unrecorded", extra={"job_id": str(ctx.job_id)})


async def _complete(
    ctx: JobContext,
    *,
    submission: Submission,
    counts: MergeCounts,
    kept: int,
    now: dt.datetime,
) -> None:
    """Write the final counts, drop the staging rows, and clear the payload.

    All three in the handler's transaction, alongside the merged data, so the
    submission can never claim a count the merge did not produce.

    `raw_payload` is cleared rather than kept: it has been applied, nothing reads
    it again, and it is the tenant's raw business data (migration 0008). The
    staging rows go for the same reason — they are scratch, and a `DELETE` grant
    exists on that table and no other precisely so this line can run.
    """
    await ctx.session.execute(
        sa.delete(IngestStagingItem).where(
            IngestStagingItem.submission_id == submission.submission_id
        )
    )
    submission.accepted_count = counts.accepted
    submission.updated_count = counts.updated
    submission.skipped_count = counts.skipped
    submission.failed_count = counts.failed
    submission.error_count = kept
    submission.status = SubmissionStatus.COMPLETED.value
    submission.completed_at = now
    submission.raw_payload = None
    await ctx.session.flush()


def _progress(submission: Submission) -> dict[str, Any]:
    """What the job row keeps once the submission holds the real answer.

    Counts only. No identifiers from the collection, because a job's progress is
    read by operators as well as by the tenant (NR-NF-06).
    """
    return {
        "submission_id": str(submission.submission_id),
        "received": submission.received_count,
        "accepted": submission.accepted_count,
        "updated": submission.updated_count,
        "skipped": submission.skipped_count,
        "failed": submission.failed_count,
    }


__all__ = ["VALIDATION_CHUNK", "process_event_batch", "process_product_bulk_upsert"]
