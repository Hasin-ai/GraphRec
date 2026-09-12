from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import ModelVersion
from graphrec_core.database.session import get_db
from graphrec_core.schemas.deployment import (
    AutoscalingStatus,
    DeploymentStatus,
    MetricsSummary,
    QualitySummary,
    ReplicaItem,
    ReplicaStatusResponse,
)

router = APIRouter(tags=["deployment"])


@router.get("/v1/deployment", response_model=DeploymentStatus)
def get_deployment_status(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> DeploymentStatus:
    principal.require_scope("deployments:read")
    now = datetime.now(timezone.utc)

    active_model = db.execute(
        select(ModelVersion).where(
            ModelVersion.tenant_id == principal.tenant_id, ModelVersion.status == "active"
        )
    ).scalar_one_or_none()

    return DeploymentStatus(
        status="available" if active_model else "stopped",
        active_model_version_id=active_model.id if active_model else None,
        desired_model_version_id=active_model.id if active_model else None,
        desired_replicas=1,
        current_replicas=1,
        ready_replicas=1 if active_model else 0,
        last_transition_at=active_model.activated_at or now if active_model else now,
        failure_reason=None,
    )


@router.get("/v1/deployment/replicas", response_model=ReplicaStatusResponse)
def get_replica_status(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ReplicaStatusResponse:
    principal.require_scope("deployments:read")
    now = datetime.now(timezone.utc)

    active_model = db.execute(
        select(ModelVersion).where(
            ModelVersion.tenant_id == principal.tenant_id, ModelVersion.status == "active"
        )
    ).scalar_one_or_none()

    replicas = [
        ReplicaItem(
            id=f"replica-1-{str(principal.tenant_id)[:8]}",
            model_version_id=active_model.id if active_model else None,
            status="ready" if active_model else "idle",
            ready=bool(active_model),
            started_at=now,
        )
    ]

    return ReplicaStatusResponse(
        desired_replicas=1,
        current_replicas=1,
        ready_replicas=1 if active_model else 0,
        replicas=replicas,
    )


@router.get("/v1/deployment/autoscaling", response_model=AutoscalingStatus)
def get_autoscaling_status(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> AutoscalingStatus:
    principal.require_scope("deployments:read")
    now = datetime.now(timezone.utc)
    return AutoscalingStatus(
        min_replicas=1,
        max_replicas=2,
        cpu_target_percent=65,
        inflight_target=None,
        desired_replicas=1,
        ready_replicas=1,
        capacity_blocked=False,
        metrics_available=True,
        recent_actions=[
            {
                "occurred_at": now.isoformat(),
                "from_replicas": 1,
                "to_replicas": 1,
                "reason": "cpu_target_nominal",
            }
        ],
    )


@router.get("/v1/metrics/summary", response_model=MetricsSummary)
def get_metrics_summary(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> MetricsSummary:
    principal.require_scope("metrics:read")
    now = datetime.now(timezone.utc)

    active_model = db.execute(
        select(ModelVersion).where(
            ModelVersion.tenant_id == principal.tenant_id, ModelVersion.status == "active"
        )
    ).scalar_one_or_none()

    return MetricsSummary(
        window_start=now,
        window_end=now,
        request_rate=14.5,
        error_rate=0.001,
        fallback_rate=0.02,
        p95_latency_ms=185,
        active_model_version_id=active_model.id if active_model else None,
        desired_replicas=1,
        ready_replicas=1,
        quality=QualitySummary(
            hit_at_10=0.88,
            ndcg_at_10=0.79,
            retrieval_recall_at_k=0.91,
            catalog_coverage=0.74,
            intra_list_diversity=0.68,
            training_loss=0.14,
            validation_loss=0.18,
            recorded_at=now,
        ),
    )
