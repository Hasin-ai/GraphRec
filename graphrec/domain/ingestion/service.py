"""Accepting what a tenant sends, and reporting what became of it.

Two arrival shapes and one report.

A **single event** is applied synchronously, because there is nothing to defer:
one row, one answer, and a caller that wants to know now. A **collection** —
`POST /v1/events/batches` or `POST /v1/products:bulk-upsert` — is accepted with
a `202`, a submission and a job, because five thousand items is not work to do
while an HTTP connection waits.

Both are idempotent by the identifier the tenant chose, and in both cases a
repeat is a **success**:

* an event identifier seen before is `duplicate_confirmed` — "This is a success
  outcome, not an error." (dc.html L1622);
* a synchronization identifier seen before returns the submission it already
  produced — "Repeating the same identifier is confirmed as a duplicate rather
  than applied twice." (L1355).

Neither of those is a `409`. A retry after a timeout is the ordinary case for an
integration, and answering it with an error would mean the safe response to an
uncertain outcome is to *not* retry.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from graphrec.common.enums import SubmissionKind, SubmissionStatus
from graphrec.common.error_copy import resolve_field_copy, resolve_item_copy
from graphrec.common.errors import NotFoundError, ValidationError
from graphrec.common.ids import uuid7
from graphrec.db.models import Customer, InteractionEvent, Product, Submission, SubmissionError
from graphrec.domain.ingestion.validation import ItemInvalid, normalise_event
from graphrec.jobs.queue import JobQueue
from graphrec.jobs.states import JobType

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.db.models import Job

#: A bounded collection that is too large is a `413`, not a `422`. The
#: distinction matters to a client: a 422 says "this request is wrong", a 413
#: says "this request is too big" and names the bound it exceeded, which is the
#: only thing that tells an integration how to split it (L1612, L1627).
PAYLOAD_TOO_LARGE = 413

#: Which bound, and which sentence, per collection kind. Both codes carry a
#: `{limit}` placeholder so the number comes from settings rather than from the
#: copy — the console's "5,000" and the server's bound are one figure.
_OVERSIZE_CODE: dict[SubmissionKind, str] = {
    SubmissionKind.EVENT_BATCH: "event_batch_oversize",
    SubmissionKind.PRODUCT_SYNC: "product_sync_oversize",
}
_REFERENCE_CODE: dict[SubmissionKind, str] = {
    SubmissionKind.EVENT_BATCH: "batch_id_required",
    SubmissionKind.PRODUCT_SYNC: "sync_id_required",
}
_COLLECTION_CODE: dict[SubmissionKind, str] = {
    SubmissionKind.EVENT_BATCH: "event_collection_required",
    SubmissionKind.PRODUCT_SYNC: "product_collection_required",
}
#: The body field each identifier arrives in, so the 422 highlights the control
#: the console actually rendered.
_REFERENCE_FIELD: dict[SubmissionKind, str] = {
    SubmissionKind.EVENT_BATCH: "batch_id",
    SubmissionKind.PRODUCT_SYNC: "sync_id",
}
_COLLECTION_FIELD: dict[SubmissionKind, str] = {
    SubmissionKind.EVENT_BATCH: "events",
    SubmissionKind.PRODUCT_SYNC: "products",
}

#: The job that will drain each kind of collection.
_JOB_TYPE: dict[SubmissionKind, JobType] = {
    SubmissionKind.EVENT_BATCH: JobType.EVENT_BATCH,
    SubmissionKind.PRODUCT_SYNC: JobType.PRODUCT_BULK_UPSERT,
}

#: The sync form's Mode control (L1357). Stored on the submission rather than
#: passed to the job, because it is a property of what the tenant submitted and
#: has to still be readable when the report is.
SYNC_MODE_UPSERT = "upsert"
SYNC_MODE_UPSERT_AND_DISABLE_MISSING = "upsert_and_disable_missing"
SYNC_MODES = (SYNC_MODE_UPSERT, SYNC_MODE_UPSERT_AND_DISABLE_MISSING)


@dataclasses.dataclass(frozen=True, slots=True)
class EventOutcome:
    """The answer to a single `POST /v1/events`.

    `duplicate` is not a failure and is not rendered as one: the console shows
    it with the `succeeded` badge (L1622). `first_received_at` is populated only
    then, because it is the one fact a duplicate carries that an acceptance does
    not — "First received 2026-08-14 09:41:02".
    """

    event: InteractionEvent
    duplicate: bool
    first_received_at: dt.datetime | None = None

    @property
    def status(self) -> str:
        return "duplicate_confirmed" if self.duplicate else "accepted"


@dataclasses.dataclass(frozen=True, slots=True)
class SubmissionOutcome:
    submission: Submission
    created: bool


class IngestionService:
    """Event and catalogue arrivals, within one tenant."""

    def __init__(
        self,
        *,
        max_events_per_batch: int = 5_000,
        max_products_per_sync: int = 5_000,
        job_lease_seconds: int = 300,
        job_max_attempts: int = 3,
    ) -> None:
        self._limits: dict[SubmissionKind, int] = {
            SubmissionKind.EVENT_BATCH: max_events_per_batch,
            SubmissionKind.PRODUCT_SYNC: max_products_per_sync,
        }
        self._queue = JobQueue(
            lease_seconds=job_lease_seconds,
            max_attempts=job_max_attempts,
            # Enqueueing takes no lease, so this identity never reaches
            # `lease_owner`. It is here because `JobQueue` is one object with one
            # constructor, and naming the process that enqueued is more useful
            # in a stack trace than an empty string.
            owner="control_api",
        )

    def limit_for(self, kind: SubmissionKind) -> int:
        return self._limits[kind]

    # ----------------------------------------------------------- single event

    async def record_event(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        raw: dict[str, Any],
        now: dt.datetime | None = None,
    ) -> EventOutcome:
        """Apply one interaction event. A repeat is confirmed, not refused."""
        now = now or dt.datetime.now(dt.UTC)
        item = self._validate_single(raw, now=now)

        product = await session.scalar(
            sa.select(Product).where(
                Product.external_product_id == item["external_product_id"],
                Product.deleted_at.is_(None),
            )
        )
        if product is None:
            # Not a 404: the caller is not addressing a resource, they are
            # describing one inside a body. The answer is the same whether the
            # identifier belongs to another tenant or to nobody at all, so it
            # discloses nothing (NR-NF-02).
            raise ValidationError("event_unknown_product").with_field(
                "external_product_id", resolve_field_copy("event_unknown_product") or ""
            )

        existing = await session.scalar(
            sa.select(InteractionEvent).where(
                InteractionEvent.external_event_id == item["external_event_id"]
            )
        )
        if existing is not None:
            return EventOutcome(
                event=existing, duplicate=True, first_received_at=existing.received_at
            )

        occurred_at = dt.datetime.fromisoformat(item["occurred_at"])
        customer = await self._customer(session, tenant_id=tenant_id, item=item, when=occurred_at)

        event = InteractionEvent(
            event_id=uuid7(),
            tenant_id=tenant_id,
            external_event_id=item["external_event_id"],
            customer_id=customer.customer_id,
            product_id=product.product_id,
            event_type=item["event_type"],
            occurred_at=occurred_at,
            received_at=now,
            value=decimal.Decimal(item["value"]) if item["value"] is not None else None,
            context=item["context"],
            submission_id=None,
        )
        # Inside a savepoint, so that losing the race for an identifier does
        # not poison the caller's transaction. A `unique_violation` aborts
        # everything back to the last savepoint and nothing further; without one
        # the recovery below would be the first of several statements refused.
        try:
            async with session.begin_nested():
                session.add(event)
                await session.flush()
        except IntegrityError:
            # Two identical events in flight at once. The loser reads the
            # winner's row and reports the duplicate confirmation a sequential
            # repeat would have got — the tenant asked for the event to exist,
            # and it does.
            settled = await session.scalar(
                sa.select(InteractionEvent).where(
                    InteractionEvent.external_event_id == item["external_event_id"]
                )
            )
            if settled is None:  # pragma: no cover - only a different constraint
                raise
            return EventOutcome(
                event=settled, duplicate=True, first_received_at=settled.received_at
            )
        return EventOutcome(event=event, duplicate=False)

    def _validate_single(self, raw: dict[str, Any], *, now: dt.datetime) -> dict[str, Any]:
        """Turn a per-item verdict into a request-level 422.

        The single-event route has no submission to report a per-item failure
        through, so the item reason becomes the field marker beside the input
        and the banner names what the form as a whole got wrong. The prototype
        separates those two halves for every form it validates (L1621, L1623).
        """
        try:
            return normalise_event(raw, now=now)
        except ItemInvalid as exc:
            raise self._single_event_error(exc.code) from exc

    @staticmethod
    def _single_event_error(code: str) -> ValidationError:
        if code in {"item_event_id_missing", "item_event_id_too_long"}:
            return ValidationError("event_id_required").with_field(
                "event_id", resolve_field_copy("event_id_required") or ""
            )
        if code in {"item_customer_id_missing", "item_customer_id_too_long"}:
            return ValidationError("event_identifiers_required").with_field(
                "customer_id", resolve_field_copy("event_identifiers_required") or ""
            )
        if code in {"item_product_id_missing", "item_product_id_too_long"}:
            return ValidationError("event_identifiers_required").with_field(
                "external_product_id", resolve_field_copy("event_identifiers_required") or ""
            )
        # Everything else is a shape problem in a field the prototype's form
        # does not validate individually: the generic banner (L1583) plus the
        # item reason as the marker, which is short by construction.
        field = _SINGLE_EVENT_FIELDS.get(code, "event")
        return ValidationError("invalid_request").with_field(field, resolve_item_copy(code))

    async def _customer(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        item: dict[str, Any],
        when: dt.datetime,
    ) -> Customer:
        """Created on first reference, like a category. See `merge.merge_events`."""
        external_id = item["external_customer_id"]
        customer = await session.scalar(
            sa.select(Customer).where(Customer.external_customer_id == external_id)
        )
        if customer is None:
            customer = Customer(
                customer_id=uuid7(),
                tenant_id=tenant_id,
                external_customer_id=external_id,
                first_seen_at=when,
                last_seen_at=when,
            )
            session.add(customer)
            await session.flush()
            return customer
        if when < customer.first_seen_at:
            customer.first_seen_at = when
        if when > customer.last_seen_at:
            customer.last_seen_at = when
        return customer

    # ------------------------------------------------------------ collections

    async def open_submission(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        kind: SubmissionKind,
        external_reference: str | None,
        items: Sequence[Any] | None,
        options: dict[str, Any] | None = None,
        now: dt.datetime | None = None,
    ) -> SubmissionOutcome:
        """Accept a bounded collection: one submission, one job, `202`."""
        now = now or dt.datetime.now(dt.UTC)
        reference = self._reference(kind, external_reference)
        collection = self._collection(kind, items)

        existing = await self.submission_by_reference(
            session, kind=kind, external_reference=reference
        )
        if existing is not None:
            return SubmissionOutcome(submission=existing, created=False)

        submission = Submission(
            submission_id=uuid7(),
            tenant_id=tenant_id,
            kind=kind.value,
            external_reference=reference,
            status=SubmissionStatus.RECEIVED.value,
            received_count=len(collection),
            # The collection as submitted. Cleared when the job finishes — see
            # migration 0008.
            raw_payload={"items": list(collection)},
            options=options or {},
            submitted_at=now,
        )
        try:
            async with session.begin_nested():
                session.add(submission)
                await session.flush()
        except IntegrityError:
            # Two identical submissions raced. The unique constraint decided;
            # this one reads the winner and reports the same duplicate
            # confirmation a sequential repeat would have got. Note that the
            # loser's job was never enqueued, because enqueueing happens below
            # this point — the collection is drained once.
            settled = await self.submission_by_reference(
                session, kind=kind, external_reference=reference
            )
            if settled is None:  # pragma: no cover - only a different constraint
                raise
            return SubmissionOutcome(submission=settled, created=False)

        job = await self._enqueue(session, tenant_id=tenant_id, kind=kind, submission=submission)
        submission.job_id = job.job_id
        await session.flush()
        return SubmissionOutcome(submission=submission, created=True)

    async def _enqueue(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        kind: SubmissionKind,
        submission: Submission,
    ) -> Job:
        """The job carries the submission id and nothing else.

        Not the payload. A job row is read by a worker that has already bound
        the tenant's context, so it can read the collection from the submission
        under the tenant's own policy — and a payload copied into `jobs.payload`
        would be a second copy of the tenant's raw data with its own retention
        story.
        """
        return await self._queue.enqueue(
            session,
            tenant_id=tenant_id,
            job_type=_JOB_TYPE[kind],
            payload={"submission_id": str(submission.submission_id)},
        )

    def _reference(self, kind: SubmissionKind, value: str | None) -> str:
        code = _REFERENCE_CODE[kind]
        trimmed = (value or "").strip()
        if not trimmed or len(trimmed) > 120:
            raise ValidationError(code).with_field(
                _REFERENCE_FIELD[kind], resolve_field_copy(code) or ""
            )
        return trimmed

    def _collection(self, kind: SubmissionKind, items: Sequence[Any] | None) -> Sequence[Any]:
        if not items:
            code = _COLLECTION_CODE[kind]
            raise ValidationError(code).with_field(_COLLECTION_FIELD[kind], "Required.")
        limit = self._limits[kind]
        if len(items) > limit:
            # 413, and the bound is in the sentence. An integration that is told
            # only "too large" has to guess how far to split.
            raise ValidationError(
                _OVERSIZE_CODE[kind],
                copy_args={"limit": limit},
                status_code=PAYLOAD_TOO_LARGE,
            )
        return items

    # ------------------------------------------------------------------ reads

    async def submission(self, session: AsyncSession, *, submission_id: uuid.UUID) -> Submission:
        """Gate 4 — a foreign submission and an absent one are the same 404."""
        found = await session.scalar(
            sa.select(Submission).where(Submission.submission_id == submission_id)
        )
        if found is None:
            raise NotFoundError("not_found")
        return found

    async def submission_by_reference(
        self, session: AsyncSession, *, kind: SubmissionKind, external_reference: str
    ) -> Submission | None:
        found: Submission | None = await session.scalar(
            sa.select(Submission).where(
                Submission.kind == kind.value,
                Submission.external_reference == external_reference,
            )
        )
        return found

    async def require_by_reference(
        self, session: AsyncSession, *, kind: SubmissionKind, external_reference: str
    ) -> Submission:
        found = await self.submission_by_reference(
            session, kind=kind, external_reference=external_reference
        )
        if found is None:
            raise NotFoundError("not_found")
        return found

    async def errors(
        self, session: AsyncSession, *, submission_id: uuid.UUID, limit: int = 100
    ) -> Sequence[SubmissionError]:
        """The kept samples, in the order the items were submitted."""
        result = await session.scalars(
            sa.select(SubmissionError)
            .where(SubmissionError.submission_id == submission_id)
            .order_by(SubmissionError.ordinal)
            .limit(limit)
        )
        return list(result)


#: Which input a shape failure belongs beside, for the single-event form. The
#: batch path needs none of this: there the item reason stands alone in a table.
_SINGLE_EVENT_FIELDS: dict[str, str] = {
    "item_not_an_object": "event",
    "item_event_type_unknown": "event_type",
    "item_occurred_at_missing": "occurred_at",
    "item_occurred_at_invalid": "occurred_at",
    "item_occurred_at_in_future": "occurred_at",
    "item_value_not_decimal": "value",
    "item_context_not_an_object": "context",
}


__all__ = [
    "SYNC_MODES",
    "SYNC_MODE_UPSERT",
    "SYNC_MODE_UPSERT_AND_DISABLE_MISSING",
    "EventOutcome",
    "IngestionService",
    "SubmissionOutcome",
]
