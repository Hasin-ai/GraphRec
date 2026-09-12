from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.auth.platform import platform_administrator
from graphrec_core.database.models import PricingPlan
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.schemas.platform import (
    PlatformAuditItem,
    PlatformAuditListResponse,
    PlatformFailureItem,
    PlatformFailureListResponse,
    PlatformPlanResource,
    PlatformQuotaOverride,
    PlatformTenantListResponse,
    PlatformTenantResource,
)

router = APIRouter(
    prefix="/v1/platform",
    tags=["platform"],
    dependencies=[Depends(platform_administrator)],
)

TENANT_STATUSES = frozenset({"active", "suspended", "deleting", "deleted"})
RECENT_LIMIT = 50


class TenantStatusUpdate(BaseModel):
    status: str = Field(..., max_length=20)


class QuotaOverrideUpdate(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


def _tenant_not_found(tenant_id: UUID) -> ApiError:
    return ApiError(404, "resource_not_found", f"Tenant '{tenant_id}' not found.")


@router.get("/tenants", response_model=PlatformTenantListResponse)
def list_platform_tenants(db: Session = Depends(get_db)) -> PlatformTenantListResponse:
    rows = db.execute(text("SELECT * FROM public.platform_list_tenants()")).mappings().all()
    return PlatformTenantListResponse(items=[PlatformTenantResource(**row) for row in rows])


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantResource)
def get_platform_tenant(tenant_id: UUID, db: Session = Depends(get_db)) -> PlatformTenantResource:
    row = (
        db.execute(
            text("SELECT * FROM public.platform_list_tenants() WHERE id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _tenant_not_found(tenant_id)
    return PlatformTenantResource(**row)


@router.post("/tenants/{tenant_id}/status", response_model=PlatformTenantResource)
def update_platform_tenant_status(
    tenant_id: UUID,
    payload: TenantStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> PlatformTenantResource:
    if payload.status not in TENANT_STATUSES:
        raise ApiError(
            422,
            "validation_failed",
            "Unsupported tenant status",
            details={"fields": [{"field": "status", "message": f"Must be one of {sorted(TENANT_STATUSES)}"}]},
        )
    row = (
        db.execute(
            text(
                "SELECT * FROM public.platform_set_tenant_status"
                "(:tenant_id, :status, :correlation_id)"
            ),
            {
                "tenant_id": tenant_id,
                "status": payload.status,
                "correlation_id": request.state.correlation_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        db.rollback()
        raise _tenant_not_found(tenant_id)
    db.commit()
    return PlatformTenantResource(**row)


@router.get("/plans", response_model=list[PlatformPlanResource])
def list_platform_plans(db: Session = Depends(get_db)) -> list[PlatformPlanResource]:
    plans = db.execute(select(PricingPlan).order_by(PricingPlan.code)).scalars().all()
    return [
        PlatformPlanResource(id=p.id, code=p.code, name=p.name, limits=p.limits, is_active=p.is_active)
        for p in plans
    ]


@router.post("/tenants/{tenant_id}/quotas", response_model=PlatformQuotaOverride)
def set_tenant_quota_override(
    tenant_id: UUID,
    payload: QuotaOverrideUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> PlatformQuotaOverride:
    row = (
        db.execute(
            text(
                "SELECT * FROM public.platform_set_quota_overrides"
                "(:tenant_id, CAST(:overrides AS jsonb), :correlation_id)"
            ),
            {
                "tenant_id": tenant_id,
                "overrides": json.dumps(payload.overrides),
                "correlation_id": request.state.correlation_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        db.rollback()
        raise _tenant_not_found(tenant_id)
    db.commit()
    return PlatformQuotaOverride(limits=row["limits"], overrides=row["overrides"])


@router.get("/failures", response_model=PlatformFailureListResponse)
def list_platform_failures(db: Session = Depends(get_db)) -> PlatformFailureListResponse:
    rows = (
        db.execute(
            text("SELECT * FROM public.platform_recent_security_events(:limit)"),
            {"limit": RECENT_LIMIT},
        )
        .mappings()
        .all()
    )
    return PlatformFailureListResponse(items=[PlatformFailureItem(**row) for row in rows])


@router.get("/audit", response_model=PlatformAuditListResponse)
def list_platform_audit_logs(db: Session = Depends(get_db)) -> PlatformAuditListResponse:
    rows = (
        db.execute(
            text("SELECT * FROM public.platform_recent_audit(:limit)"),
            {"limit": RECENT_LIMIT},
        )
        .mappings()
        .all()
    )
    return PlatformAuditListResponse(items=[PlatformAuditItem(**row) for row in rows])


@router.get("/status")
def get_platform_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        database = "connected"
    except SQLAlchemyError:
        db.rollback()
        database = "unavailable"
    return {
        "status": "healthy" if database == "connected" else "degraded",
        "api_cluster": "online",
        "database": database,
        "worker_pool": "not_deployed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
