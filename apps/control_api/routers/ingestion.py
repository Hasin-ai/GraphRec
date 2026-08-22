"""Ingestion — the one surface both realms reach.

Four write shapes and two reads, and every one of them accepts either a
developer's session or a tenant's API credential. That is why this module exists
separately from `products.py`: the catalogue's CRUD is session-only (`[DEV]`,
L645-646), but bulk upsert is what an integration runs from the tenant's own
backend at three in the morning, and it cannot require a person to be signed in.

`require_ingest` decides which realm answered and applies the matching gate 3 —
role for a session, scope for a credential. Neither is derived from the other;
see `apps/control_api/deps.py`.

**Idempotency is the theme, and it is not the same mechanism twice.** A single
event is keyed by `event_id` and a repeat is confirmed at `200`. A collection is
keyed by `sync_id` or `batch_id` and a repeat returns the original submission,
unchanged, rather than draining the collection a second time. In both cases a
repeat is a **success**: there is no 409 anywhere on this surface, because an
integration retrying after a timeout has done nothing wrong.

There is no submission index. "This view is reached from the submission that
produced it." (L1393) — so a submission is addressable by its id or by the
identifier the tenant chose, and by nothing else. A list would be a new way to
enumerate a tenant's ingestion history that no screen asks for.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from apps.control_api.deps import IngestPrincipal, UsageCountersDep, require_ingest
from apps.control_api.schemas import (
    BulkUpsertProductsRequest,
    SubmissionCounts,
    SubmissionErrorItem,
    SubmissionResponse,
    SubmitEventBatchRequest,
    SubmitEventRequest,
    SubmitEventResponse,
)
from graphrec.common.enums import CredentialScope, SubmissionKind, SubmissionStatus
from graphrec.domain.ingestion import IngestionService

if TYPE_CHECKING:
    from graphrec.db.models import Submission

router = APIRouter(tags=["ingestion"])

#: Gate 3, per route. A credential needs the scope its operation names; a
#: session needs the developer role, which is the default in `require_ingest`.
WriteEvents = Annotated[IngestPrincipal, Depends(require_ingest(CredentialScope.EVENTS_WRITE))]
WriteCatalog = Annotated[IngestPrincipal, Depends(require_ingest(CredentialScope.CATALOG_WRITE))]
ReadSubmissions = Annotated[
    IngestPrincipal, Depends(require_ingest(CredentialScope.SUBMISSIONS_READ))
]


def _service(request: Request) -> IngestionService:
    settings = request.app.state.settings
    return IngestionService(
        max_events_per_batch=settings.max_events_per_batch,
        max_products_per_sync=settings.max_products_per_sync,
        job_lease_seconds=settings.job_lease_seconds,
        job_max_attempts=settings.job_max_attempts,
    )


Service = Annotated[IngestionService, Depends(_service)]


# ----------------------------------------------------------------- rendering


def _outcome(submission: Submission) -> str:
    """The badge's vocabulary, which is not the rail's.

    `processing` covers `received`, `validating` and `applying` — three rail
    positions and one badge, because until it is finished the only thing the
    badge can honestly say is that it is not finished (L1383).
    """
    if submission.status == SubmissionStatus.FAILED.value:
        return "failed"
    if submission.status == SubmissionStatus.COMPLETED.value:
        return "succeeded"
    return "processing"


def _render(submission: Submission, errors: list[SubmissionErrorItem]) -> SubmissionResponse:
    return SubmissionResponse(
        submission_id=submission.submission_id,
        kind=submission.submission_kind,
        status=_outcome(submission),
        stage=submission.submission_status,
        reference=submission.external_reference,
        submitted_at=submission.submitted_at,
        completed_at=submission.completed_at,
        counts=SubmissionCounts(
            received=submission.received_count,
            accepted=submission.accepted_count,
            updated=submission.updated_count,
            skipped=submission.skipped_count,
            failed=submission.failed_count,
        ),
        error_count=submission.error_count,
        errors=errors,
        failure_code=submission.failure_code,
    )


async def _read(
    service: IngestionService, principal: IngestPrincipal, submission: Submission
) -> SubmissionResponse:
    """A submission plus its kept error samples.

    The samples are read only here, never on the accept path: a submission that
    has just been accepted has none, and issuing the query anyway would put a
    second round trip on the hot path for a guaranteed empty result.
    """
    samples = await service.errors(
        principal.session, submission_id=submission.submission_id, limit=submission.error_count
    )
    return _render(
        submission,
        [SubmissionErrorItem(ref=e.item_reference, reason=e.reason) for e in samples],
    )


def _accepted(
    submission: Submission, outcome_created: bool, response: Response
) -> SubmissionResponse:
    """`202` for a new submission, `200` for a repeat of one already accepted.

    The status line is where the difference goes, because the body cannot carry
    it honestly: a repeat's body is the *original* submission's state, counts
    and all, and a `duplicate` flag beside real counts invites a client to treat
    the counts as this call's. `200` says "this is a read of something that
    already existed", which is exactly what it is.
    """
    response.status_code = status.HTTP_202_ACCEPTED if outcome_created else status.HTTP_200_OK
    return _render(submission, [])


# ------------------------------------------------------------- single event


@router.post(
    "/events",
    response_model=SubmitEventResponse,
    summary="Submit one interaction event",
)
async def submit_event(
    body: SubmitEventRequest,
    principal: WriteEvents,
    service: Service,
    counters: UsageCountersDep,
) -> SubmitEventResponse:
    """`200` whether it was new or a repeat (L1178).

    Not `201`. A repeat created nothing, and returning `201` for one would make
    the status line say something untrue about the second call. `200` with a
    `status` field is the shape the prototype publishes, and it lets both
    answers use one response model.
    """
    outcome = await service.record_event(
        principal.session,
        counters,
        tenant_id=principal.tenant_id,
        raw=body.model_dump(exclude_unset=True),
    )
    return SubmitEventResponse(
        event_id=outcome.event.external_event_id,
        status=outcome.status,
        first_received_at=outcome.first_received_at,
    )


# --------------------------------------------------------------- collections


@router.post(
    "/events/batches",
    response_model=SubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a bounded event batch",
)
async def submit_event_batch(
    body: SubmitEventBatchRequest, principal: WriteEvents, service: Service, response: Response
) -> SubmissionResponse:
    """Accepted, not applied — 413 if the collection is over the bound."""
    outcome = await service.open_submission(
        principal.session,
        tenant_id=principal.tenant_id,
        kind=SubmissionKind.EVENT_BATCH,
        external_reference=body.batch_id,
        items=body.events,
    )
    return _accepted(outcome.submission, outcome.created, response)


@router.post(
    "/products:bulk-upsert",
    response_model=SubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Synchronize a bounded product collection",
)
async def bulk_upsert_products(
    body: BulkUpsertProductsRequest, principal: WriteCatalog, service: Service, response: Response
) -> SubmissionResponse:
    """L1355. "Repeating the same identifier is confirmed as a duplicate rather
    than applied twice."

    The mode travels in `options` rather than as a column, because it is a
    property of *this submission's* instruction and not of the tenant. Two syncs
    an hour apart may legitimately disagree about whether omission means
    "disable".
    """
    options: dict[str, Any] = {"mode": body.mode} if body.mode else {}
    outcome = await service.open_submission(
        principal.session,
        tenant_id=principal.tenant_id,
        kind=SubmissionKind.PRODUCT_SYNC,
        external_reference=body.sync_id,
        items=body.products,
        options=options,
    )
    return _accepted(outcome.submission, outcome.created, response)


# --------------------------------------------------------------------- reads


@router.get(
    "/submissions/{submission_id}",
    response_model=SubmissionResponse,
    summary="One submission, either kind",
)
async def get_submission(
    submission_id: uuid.UUID, principal: ReadSubmissions, service: Service
) -> SubmissionResponse:
    """ "One read covers both product-sync and event-batch submissions." (L1179)

    Gate 4 — a submission belonging to another tenant is not visible under this
    session's binding, so it is the same 404 as one that never existed, and the
    404 does not say the word "submission".
    """
    submission = await service.submission(principal.session, submission_id=submission_id)
    return await _read(service, principal, submission)


@router.get(
    "/events/batches/{batch_id}",
    response_model=SubmissionResponse,
    summary="A batch, by the identifier it was submitted under",
)
async def get_event_batch(
    batch_id: str, principal: ReadSubmissions, service: Service
) -> SubmissionResponse:
    """The alias the prototype publishes (L1180), and it is not a redirect.

    An integration that submitted `batch-4471` holds that identifier; it does
    not necessarily hold the submission id, because the call that would have
    returned it is the call that timed out. Being able to ask under the
    identifier you chose is what makes a retry-free recovery possible.

    Scoped to `event_batch` deliberately: `sync_id` and `batch_id` are separate
    namespaces (migration 0008 puts `kind` in the unique constraint), so this
    route must not answer with a product sync that happens to share a name.
    """
    submission = await service.require_by_reference(
        principal.session, kind=SubmissionKind.EVENT_BATCH, external_reference=batch_id
    )
    return await _read(service, principal, submission)
