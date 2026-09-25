"""Serving status and measured serving metrics.

The status of a tenant's service is its active model version: GraphRec
activates one version per tenant and serves from the API process itself, so
there is no replica set, autoscaler or capacity pool to report. The metrics
summary is computed from ``serving_requests``, the row-per-request ledger the
recommendations route appends to.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import ModelVersion, ServingRequest
from graphrec_core.database.session import get_db
from graphrec_core.schemas.deployment import (
    DeploymentStatus,
    MetricsSummary,
    QualitySummary,
)

router = APIRouter(tags=["deployment"])

#: Default width of the metrics window, in minutes.
DEFAULT_WINDOW_MINUTES = 60


def _active_model(db: Session, tenant_id) -> ModelVersion | None:
    return db.execute(
        select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id, ModelVersion.status == "active"
        )
    ).scalar_one_or_none()


@router.get("/v1/deployment", response_model=DeploymentStatus)
def get_deployment_status(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> DeploymentStatus:
    principal.require_scope("deployments:read")
    active_model = _active_model(db, principal.tenant_id)
    if active_model is None:
        return DeploymentStatus(status="stopped")
    return DeploymentStatus(
        status="available",
        active_model_version_id=active_model.id,
        last_transition_at=active_model.activated_at,
    )


@router.get("/v1/metrics/summary", response_model=MetricsSummary)
def get_metrics_summary(
    window_minutes: int = Query(
        DEFAULT_WINDOW_MINUTES,
        ge=5,
        le=10080,
        description="Width of the measurement window ending now.",
    ),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> MetricsSummary:
    principal.require_scope("metrics:read")
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(minutes=window_minutes)

    counts = db.execute(
        select(
            func.count(),
            func.count(case((ServingRequest.outcome == "error", 1))),
            func.count(case((ServingRequest.fallback_used.is_(True), 1))),
        ).where(
            ServingRequest.tenant_id == principal.tenant_id,
            ServingRequest.occurred_at >= window_start,
            ServingRequest.occurred_at <= window_end,
        )
    ).one()
    total, errors, fallbacks = int(counts[0]), int(counts[1]), int(counts[2])

    p95 = db.execute(
        select(
            func.percentile_disc(0.95).within_group(ServingRequest.latency_ms.asc())
        ).where(
            ServingRequest.tenant_id == principal.tenant_id,
            ServingRequest.occurred_at >= window_start,
            ServingRequest.occurred_at <= window_end,
            ServingRequest.outcome == "served",
        )
    ).scalar()

    active_model = _active_model(db, principal.tenant_id)
    quality = None
    if active_model is not None:
        quality = QualitySummary(
            model_version_id=active_model.id,
            version_tag=active_model.version_tag,
            recorded_at=active_model.created_at,
            metrics=active_model.metrics or {},
        )

    return MetricsSummary(
        window_start=window_start,
        window_end=window_end,
        request_count=total,
        request_rate=total / window_minutes,
        error_rate=errors / total if total else None,
        fallback_rate=fallbacks / total if total else None,
        p95_latency_ms=int(p95) if p95 is not None else None,
        active_model_version_id=active_model.id if active_model else None,
        quality=quality,
    )
