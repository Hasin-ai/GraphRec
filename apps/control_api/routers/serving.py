"""The control plane's view of serving, and the two writes that change it.

Five reads and two writes. The reads are `/service-status` (dc.html L1826-1843);
the writes are the activate and roll-back dialogs on `/models/:versionId`.

**Neither write makes anything serve.** `:activate` and `:rollback` return `202`
because they record an intention — a `deployment_revisions` row and a new
`desired_version_id` — and the reconciler swaps `active_version_id` only after a
replica has been observed answering with the new version. That is ER-F-06's
load-before-swap, and `202` is the honest status code for it: the request was
accepted, and what it asked for has not happened yet. A `200` here would be a
claim the server cannot make.

**The refusals are the console's own sentences.** Every `409` carries a reason
from `graphrec.common.error_copy`, and the same functions that produce them
(`graphrec.domain.registry.lifecycle`) produce the `actions` block on
`/v1/model-versions/{id}`. A button disabled with "Only an eligible version can
be activated" and a `409` that said something else would be two answers to one
question.

**The errors panel is redacted by construction.** L1842 forbids request payloads
and recommendation results here. `error_class` is a closed enum and
`error_reason` is written from approved copy at insert time, so this router does
not filter anything — there is nothing on those rows to filter.

Everything here is session-only and Administrator-only, matching ROUTES.md: a
tenant application has no scope naming these, and `/service-status`, `/models`
and their dialogs are all `[ADM]`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from apps.control_api.deps import RequireAdministrator, TenantAudit
from apps.control_api.schemas import (
    ActivateVersionRequest,
    AutoscalingResponse,
    DeploymentReplicasResponse,
    DeploymentResponse,
    DeploymentRevisionBody,
    DeploymentVersionBody,
    MetricsSummaryResponse,
    ReplicaBody,
    RollbackRequest,
    ServingErrorBody,
    ServingErrorsResponse,
)
from graphrec.common.enums import AuditAction, AuditActor
from graphrec.domain.serving.activation import ActivationService
from graphrec.domain.serving.deployment import DeploymentService
from graphrec.domain.serving.metrics import MetricsService

if TYPE_CHECKING:
    from graphrec.db.models import DeploymentRevision, ServingReplica
    from graphrec.domain.serving.deployment import DeploymentView
    from graphrec.domain.serving.metrics import ServingMetrics
    from graphrec.storage.store import ArtifactStore

router = APIRouter(tags=["serving"])


def _deployments() -> DeploymentService:
    return DeploymentService()


def _metrics() -> MetricsService:
    return MetricsService()


def _activation() -> ActivationService:
    return ActivationService()


def _store(request: Request) -> ArtifactStore | None:
    """The artifact store, when this process was configured with one.

    A roll back validates that the target's bytes are still there before it
    changes desired state (ER-F-07), and a process with no store cannot make
    that check. `ActivationService` logs the gap rather than passing silently.
    """
    found: ArtifactStore | None = getattr(request.app.state, "artifact_store", None)
    return found


Deployments = Annotated[DeploymentService, Depends(_deployments)]
Metrics = Annotated[MetricsService, Depends(_metrics)]
Activations = Annotated[ActivationService, Depends(_activation)]
Store = Annotated["ArtifactStore | None", Depends(_store)]


# ----------------------------------------------------------------- rendering


def _version_body(version_id: uuid.UUID | None, number: int | None) -> DeploymentVersionBody | None:
    if version_id is None or number is None:
        return None
    return DeploymentVersionBody(version_id=version_id, version_number=number)


def _replica_body(replica: ServingReplica) -> ReplicaBody:
    return ReplicaBody(
        replica_ref=replica.replica_ref,
        status=replica.status,
        ready=replica.ready,
        version_id=replica.version_id,
        started_at=replica.started_at,
        ended_at=replica.ended_at,
        observed_at=replica.observed_at,
    )


def _revision_body(revision: DeploymentRevision) -> DeploymentRevisionBody:
    return DeploymentRevisionBody(
        revision=revision.revision,
        kind=revision.kind,
        status=revision.status,
        from_version_id=revision.from_version_id,
        to_version_id=revision.to_version_id,
        reason=revision.reason,
        failure_reason=revision.failure_reason,
        started_at=revision.started_at,
        completed_at=revision.completed_at,
    )


def _deployment_body(view: DeploymentView, measures: ServingMetrics) -> DeploymentResponse:
    return DeploymentResponse(
        deployment_id=view.deployment_id,
        state=view.state,
        active_version=_version_body(view.active_version_id, view.active_version_number),
        desired_version=_version_body(view.desired_version_id, view.desired_version_number),
        serving_previous=view.serving_previous,
        desired_replicas=view.desired_replicas,
        ready_replicas=view.ready_replicas,
        last_transition_at=view.last_transition_at,
        recent_error_count_24h=measures.errors,
        fallback_rate=measures.fallback_rate,
        latency_p95_ms=measures.latency_p95_ms,
        measurement_status=measures.status_label,
        measurement_freshness_seconds=measures.freshness_seconds,
    )


# --------------------------------------------------------------------- reads


@router.get(
    "/deployment",
    response_model=DeploymentResponse,
    summary="Deployment state, active version and the board's measurements",
)
async def read_deployment(
    principal: RequireAdministrator, deployments: Deployments, measurements: Metrics
) -> DeploymentResponse:
    """A `404` when the tenant has never deployed.

    Not an empty `stopped / 0 / 0`: "no deployment" and "a deployment with
    nothing running" are different states, and a tenant debugging the second
    must not be shown the first.
    """
    view = await deployments.view(principal.session)
    measures = await measurements.summary(principal.session)
    return _deployment_body(view, measures)


@router.get(
    "/deployment/replicas",
    response_model=DeploymentReplicasResponse,
    summary="Desired versus ready, and every replica behind those two numbers",
)
async def read_replicas(
    principal: RequireAdministrator, deployments: Deployments
) -> DeploymentReplicasResponse:
    """Includes stopped and failed replicas.

    A replica that died two minutes ago is the row somebody opened this page
    for. Pruning belongs to the reconciler, and it prunes what the driver stops
    reporting rather than what looks finished.
    """
    view = await deployments.view(principal.session)
    replicas = await deployments.replicas(principal.session)
    return DeploymentReplicasResponse(
        desired_replicas=view.desired_replicas,
        ready_replicas=view.ready_replicas,
        replicas=[_replica_body(replica) for replica in replicas],
    )


@router.get(
    "/deployment/autoscaling",
    response_model=AutoscalingResponse,
    summary="Capacity bounds and the recent changes to what serves",
)
async def read_autoscaling(
    principal: RequireAdministrator,
    deployments: Deployments,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AutoscalingResponse:
    """XR-F-08's bounds, read from the deployment rather than from the plan.

    A plan change must not retroactively rewrite what the reconciler was
    converging toward while it was converging, so the bounds are copied onto the
    deployment when they change and read from there afterwards.
    """
    view = await deployments.view(principal.session)
    revisions = await deployments.revisions(principal.session, limit=limit)
    return AutoscalingResponse(
        min_replicas=view.min_replicas,
        max_replicas=view.max_replicas,
        desired_replicas=view.desired_replicas,
        ready_replicas=view.ready_replicas,
        target_rps_per_replica=view.target_rps_per_replica,
        recent_actions=[_revision_body(revision) for revision in revisions],
    )


@router.get(
    "/metrics/summary",
    response_model=MetricsSummaryResponse,
    summary="Availability, latency and fallback rate over the last 24 hours",
)
async def read_metrics_summary(
    principal: RequireAdministrator, measurements: Metrics
) -> MetricsSummaryResponse:
    """No deployment is not an error here.

    Unlike `/deployment`, this answers for a tenant that has never served — with
    `measurement delayed` and nulls. The board draws six stats and a tenant
    whose first request has not landed yet should see a board, not a `404`.
    """
    measures = await measurements.summary(principal.session)
    return MetricsSummaryResponse(
        window_hours=measures.window_hours,
        requests=measures.requests,
        errors=measures.errors,
        availability=measures.availability,
        latency_p95_ms=measures.latency_p95_ms,
        fallback_rate=measures.fallback_rate,
        measurement_status=measures.status_label,
        measurement_freshness_seconds=measures.freshness_seconds,
    )


@router.get(
    "/service-status/errors",
    response_model=ServingErrorsResponse,
    summary="Recent serving errors, classes only",
)
async def read_serving_errors(
    principal: RequireAdministrator,
    measurements: Metrics,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ServingErrorsResponse:
    """L1842, verbatim: "Error classes only. Request payloads and recommendation
    results are never rendered here."

    This is the only trace of the serving path the console has, which is exactly
    why it stays redacted: the temptation to add "just the product ids" is the
    temptation this endpoint exists to refuse.
    """
    errors = await measurements.errors(principal.session, limit=limit)
    return ServingErrorsResponse(
        errors=[
            ServingErrorBody(
                occurred_at=error.occurred_at,
                error_class=error.error_class.value,
                reason=error.reason,
                reference=error.reference,
            )
            for error in errors
        ]
    )


# -------------------------------------------------------------------- writes


@router.post(
    "/model-versions/{version_id}:activate",
    response_model=DeploymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a version to serve",
)
async def activate_model_version(
    version_id: uuid.UUID,
    body: ActivateVersionRequest,
    principal: RequireAdministrator,
    activations: Activations,
    deployments: Deployments,
    measurements: Metrics,
    audit: TenantAudit,
) -> DeploymentResponse:
    """`202`, and the previous version is still answering when it returns.

    The response is the deployment, not the version: what a caller wants to know
    after activating is what is serving now, and the answer for the next minute
    or so is "the previous one, while the new one loads". `serving_previous` is
    that fact, and it is the same field the console watches until the swap.
    """
    async with audit.action(
        AuditAction.ACTIVATION,
        resource_type="model_version",
        resource_ref=version_id,
        details={"reason": body.reason},
    ) as entry:
        request = await activations.activate(
            principal.session,
            tenant_id=principal.tenant_id,
            version_id=version_id,
            actor_id=principal.user_id,
            actor_type=AuditActor.TENANT_USER,
            reason=body.reason,
        )
        # The revision number, because that is what the operator and the
        # reconciler both name this attempt: the audit row and
        # `deployment_revisions` can be joined without guessing from timestamps.
        entry.details["revision"] = request.revision.revision
        # `succeeded` here means the *request* was accepted and the previous
        # version is still serving. Whether the new one ever becomes ready is a
        # later fact, recorded by the reconciler against the same revision.
        entry.details["outcome_scope"] = "requested"
    view = await deployments.view(principal.session)
    measures = await measurements.summary(principal.session)
    return _deployment_body(view, measures)


@router.post(
    "/models/{model_id}:rollback",
    response_model=DeploymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for the retained previous version back",
)
async def rollback_model(
    model_id: uuid.UUID,
    body: RollbackRequest,
    principal: RequireAdministrator,
    activations: Activations,
    deployments: Deployments,
    measurements: Metrics,
    store: Store,
    audit: TenantAudit,
) -> DeploymentResponse:
    """The target is validated before anything changes (ER-F-07).

    `model_id` is in the path because BACKEND_PLAN L1166 puts it there and
    because a roll back is an operation on the model rather than on a version.
    A tenant has one model, so it identifies the same deployment `require`
    finds; passing it to the service as a second scope would be a second,
    weaker copy of a check RLS already made.
    """
    async with audit.action(
        AuditAction.ROLLBACK,
        resource_type="model",
        resource_ref=model_id,
        details={"reason": body.reason},
    ) as entry:
        request = await activations.rollback(
            principal.session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type=AuditActor.TENANT_USER,
            target_version_id=body.target_version_id,
            reason=body.reason,
            store=store,
        )
        entry.details["revision"] = request.revision.revision
        # The version rolled *to*, which may have been chosen for the caller:
        # `target_version_id` is optional and the service resolves the retained
        # previous version when it is absent. Recording the resolved id is the
        # difference between "rolled back" and "rolled back to 7".
        entry.details["target_version_id"] = str(request.target.model_version_id)
    view = await deployments.view(principal.session)
    measures = await measurements.summary(principal.session)
    return _deployment_body(view, measures)
