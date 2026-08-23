"""Training — request a run, watch it, stop it.

Six routes and one deliberate absence. There is no "retry" and no "resume":
a failed run is retried by requesting a new one, and a crashed one resumes
itself from its last checkpoint without anybody asking. Offering a control for
something that already happens would be offering a client a way to make it
happen twice.

**Every refusal happens at enqueue.** The four admission checks — an active run,
the cooldown, the quota, enough data — are evaluated before a row exists, so a
refused request leaves nothing behind for a tenant to wonder about later. That
is the whole reason `GET /eligibility` exists as its own route: the console
shows the same four numbers *before* the dialog opens (L1666-1669), computed by
the same function, so the button's state and the request's outcome cannot
disagree.

**The rail is a server-rendered contract.** `stages`, `stage_index` and `note`
all come from `render_stage_rail`, which reproduces the prototype's branch table
at L1707. A client that computed the note from `state` would get the cancelled
case wrong, because "Cancelled at building_graph" needs the stage the run
reached and `state` no longer holds it.

Everything here is session-only. Training is a `[DEV]` surface in the prototype
(L1663) and no credential scope names it, so an API credential presenting itself
at these routes is refused by `CurrentTenant` before the route is reached.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from apps.control_api.deps import CurrentTenant, UsageCountersDep
from apps.control_api.schemas import (
    CancelTrainingRequest,
    RequestTrainingRequest,
    TrainingEligibilityResponse,
    TrainingJobListResponse,
    TrainingJobResponse,
    TrainingMetricBody,
    TrainingMetricsResponse,
    TrainingSnapshotResponse,
)
from graphrec.common.enums import JobState
from graphrec.common.error_copy import resolve_copy
from graphrec.domain.training.service import (
    TrainingRequest,
    TrainingService,
    eligibility_payload,
    render_stage_rail,
)

if TYPE_CHECKING:
    from graphrec.db.models import DatasetSnapshot, TrainingJob

router = APIRouter(prefix="/training-jobs", tags=["training"])

#: A separate router because the resource is a snapshot, not a training job, and
#: nesting it under `/training-jobs/{id}/snapshot` would give the same row two
#: addresses. BACKEND_PLAN L1131 puts it at `/v1/datasets/snapshots/{id}`.
datasets = APIRouter(prefix="/datasets", tags=["training"])


def _service(request: Request) -> TrainingService:
    settings = request.app.state.settings
    return TrainingService(
        concurrency_limit=settings.training_global_concurrency,
        cooldown_seconds=settings.training_cooldown_seconds,
        min_sequences=settings.training_min_sequences,
        job_lease_seconds=settings.job_lease_seconds,
        job_max_attempts=settings.job_max_attempts,
    )


Service = Annotated[TrainingService, Depends(_service)]


# ----------------------------------------------------------------- rendering


def _snapshot(snapshot: DatasetSnapshot) -> TrainingSnapshotResponse:
    return TrainingSnapshotResponse(
        snapshot_id=snapshot.snapshot_id,
        training_job_id=snapshot.training_job_id,
        cutoff_at=snapshot.cutoff_at,
        window_days=snapshot.window_days,
        uri=snapshot.uri,
        checksum=snapshot.checksum,
        sequence_count=snapshot.sequence_count,
        product_count=snapshot.product_count,
        event_count=snapshot.event_count,
        created_at=snapshot.created_at,
    )


def _render(job: TrainingJob, snapshot: DatasetSnapshot | None) -> TrainingJobResponse:
    """One job, with the rail and gate 5 resolved server-side.

    `blocked_reason` is populated only when the control is disabled. A reason
    beside an enabled button is a reason the console has to remember not to
    show, and something eventually shows it.
    """
    rail = render_stage_rail(job)
    can_cancel = job.is_active() and job.job_state is not JobState.CANCELLING
    return TrainingJobResponse(
        training_job_id=job.training_job_id,
        job_id=job.job_id,
        state=job.state,
        stages=list(rail.stages),
        stage_index=rail.stage_index,
        progress=job.progress_text,
        note=rail.note,
        requested_by=job.requested_by,
        request_ref=job.request_ref,
        interaction_window_days=job.interaction_window_days,
        max_epochs=job.max_epochs,
        requested_at=job.requested_at,
        completed_at=job.completed_at,
        failure_reason=job.failure_reason,
        cancel_reason=job.cancel_reason,
        error_reference=job.error_reference,
        snapshot=_snapshot(snapshot) if snapshot is not None else None,
        can_cancel=can_cancel,
        blocked_reason=None if can_cancel else _blocked(job),
    )


def _blocked(job: TrainingJob) -> str:
    """Why the cancel button is off, in the copy the refusal would have used.

    Read from the same catalogue the `409` reads from, so the disabled
    tooltip and the error a determined client provokes say the same thing.
    """
    if job.job_state is JobState.CANCELLING:
        return resolve_copy("job_already_cancelling")
    return resolve_copy("job_not_cancellable")


# -------------------------------------------------------------- eligibility


@router.get(
    "/eligibility",
    response_model=TrainingEligibilityResponse,
    summary="The four admission checks, before anything is requested",
)
async def training_eligibility(
    principal: CurrentTenant,
    service: Service,
    counters: UsageCountersDep,
    window_days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> TrainingEligibilityResponse:
    """Declared above `/{training_job_id}` on purpose.

    FastAPI matches routes in declaration order, so a literal path that could
    also parse as a path parameter has to come first. It cannot here — the
    parameter is a `UUID` and `eligibility` is not one, so the mismatch would be
    a `422` rather than a wrong handler — but relying on that is relying on the
    parameter's type never widening.
    """
    decision = await service.eligibility(
        principal.session,
        counters,
        tenant_id=principal.tenant_id,
        window_days=window_days,
    )
    return TrainingEligibilityResponse.model_validate(eligibility_payload(decision))


# ------------------------------------------------------------------- writes


@router.post(
    "",
    response_model=TrainingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a training run",
)
async def request_training(
    body: RequestTrainingRequest,
    principal: CurrentTenant,
    service: Service,
    counters: UsageCountersDep,
    response: Response,
) -> TrainingJobResponse:
    """`202` for a new run, `200` for a replay of one already requested.

    A repeated `request_ref` is a success, not a `409` (§17.3). The idempotency
    key exists precisely so a client that timed out on the first call can ask
    again; answering `409` would make the safe retry indistinguishable from the
    dangerous one. The status line carries the difference, as it does for
    ingestion — see `_accepted` there for the same argument at more length.

    The four refusals are `409`, `409`, `429` and `422`, and each is raised by
    `Eligibility.raise_if_blocked` in a fixed order: an active run first, then
    the cooldown, then the quota, then the data. Fixed because a tenant blocked
    by two things should be told about the same one on every call.
    """
    outcome = await service.request(
        principal.session,
        counters,
        tenant_id=principal.tenant_id,
        requested_by=principal.user_id,
        request=TrainingRequest(
            request_ref=body.request_ref,
            model_type=body.model_type,
            interaction_window_days=body.interaction_window_days,
            max_epochs=body.max_epochs,
        ),
    )
    response.status_code = status.HTTP_202_ACCEPTED if outcome.created else status.HTTP_200_OK
    snapshot = (
        None
        if outcome.created
        else await service.snapshot_of(
            principal.session, training_job_id=outcome.job.training_job_id
        )
    )
    return _render(outcome.job, snapshot)


@router.post(
    "/{training_job_id}:cancel",
    response_model=TrainingJobResponse,
    summary="Ask a run to stop, with a reason",
)
async def cancel_training(
    training_job_id: uuid.UUID,
    body: CancelTrainingRequest,
    principal: CurrentTenant,
    service: Service,
) -> TrainingJobResponse:
    """L1714: "The job moves to cancelling and then to cancelled."

    Two states because nothing here stops anything. The worker observes the
    request at its next stage boundary and finishes the transition itself, so a
    `200` from this route means the request was recorded — not that training has
    stopped. The response's `state` says `cancelling` for exactly that reason.
    """
    job = await service.cancel(
        principal.session, training_job_id=training_job_id, reason=body.reason
    )
    snapshot = await service.snapshot_of(principal.session, training_job_id=training_job_id)
    return _render(job, snapshot)


# -------------------------------------------------------------------- reads


@router.get("", response_model=TrainingJobListResponse, summary="A tenant's training runs")
async def list_training_jobs(
    principal: CurrentTenant,
    service: Service,
    state: JobState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TrainingJobListResponse:
    """The table at L1668, newest first.

    Snapshots are not joined in. The table shows state and timing; a snapshot
    per row would be one query per row for a column nobody draws.
    """
    jobs = await service.list_jobs(principal.session, state=state, limit=limit)
    return TrainingJobListResponse(jobs=[_render(job, None) for job in jobs])


@router.get(
    "/{training_job_id}",
    response_model=TrainingJobResponse,
    summary="One run, with its stage rail",
)
async def get_training_job(
    training_job_id: uuid.UUID, principal: CurrentTenant, service: Service
) -> TrainingJobResponse:
    job = await service.get(principal.session, training_job_id=training_job_id)
    snapshot = await service.snapshot_of(principal.session, training_job_id=training_job_id)
    return _render(job, snapshot)


@router.get(
    "/{training_job_id}/metrics",
    response_model=TrainingMetricsResponse,
    summary="The per-epoch training curve",
)
async def get_training_metrics(
    training_job_id: uuid.UUID, principal: CurrentTenant, service: Service
) -> TrainingMetricsResponse:
    """Epoch 0 is the popularity baseline, not the first trained epoch.

    That is what makes the curve readable: every later point is above or below
    a line whose meaning a tenant already understands.
    """
    job = await service.get(principal.session, training_job_id=training_job_id)
    rows = await service.metrics(principal.session, training_job_id=job.training_job_id)
    return TrainingMetricsResponse(
        training_job_id=job.training_job_id,
        metrics=[
            TrainingMetricBody(epoch=row.epoch, metric_name=row.metric_name, value=float(row.value))
            for row in rows
        ],
    )


@datasets.get(
    "/snapshots/{snapshot_id}",
    response_model=TrainingSnapshotResponse,
    summary="The frozen window a run trained on",
)
async def get_snapshot(
    snapshot_id: uuid.UUID, principal: CurrentTenant, service: Service
) -> TrainingSnapshotResponse:
    """Gate 4 by policy, not by comparison.

    The session is bound to the caller's tenant, so another tenant's snapshot is
    not a row this query can return; the service turns the empty result into the
    `404` it is. There is no branch here that reads a `tenant_id` and decides,
    because that branch is the one that eventually gets it wrong.
    """
    return _snapshot(await service.snapshot(principal.session, snapshot_id=snapshot_id))


__all__ = ["datasets", "router"]
