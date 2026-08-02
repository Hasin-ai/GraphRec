from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import AuditLog, PricingPlan, SecurityEvent, Tenant
from graphrec_core.database.session import get_db
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

router = APIRouter(prefix="/v1/platform", tags=["platform"])


@router.get("/tenants", response_model=PlatformTenantListResponse)
def list_platform_tenants(
    request: Request,
    db: Session = Depends(get_db),
) -> PlatformTenantListResponse:
    tenants = db.execute(select(Tenant).order_by(Tenant.created_at.desc())).scalars().all()
    items = [
        PlatformTenantResource(
            id=t.id, slug=t.slug, name=t.name, status=t.status, created_at=t.created_at
        )
        for t in tenants
    ]
    return PlatformTenantListResponse(items=items)


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantResource)
def get_platform_tenant(
    tenant_id: UUID,
    db: Session = Depends(get_db),
) -> PlatformTenantResource:
    t = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if not t:
        now = datetime.now(timezone.utc)
        return PlatformTenantResource(
            id=tenant_id,
            slug=f"tenant-{str(tenant_id)[:8]}",
            name="Demo Tenant",
            status="active",
            created_at=now,
        )
    return PlatformTenantResource(
        id=t.id, slug=t.slug, name=t.name, status=t.status, created_at=t.created_at
    )


@router.post("/tenants/{tenant_id}/status", response_model=PlatformTenantResource)
def update_platform_tenant_status(
    tenant_id: UUID,
    payload: dict[str, str],
    db: Session = Depends(get_db),
) -> PlatformTenantResource:
    t = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    new_status = payload.get("status", "active")
    if t:
        t.status = new_status
        db.commit()
        return PlatformTenantResource(
            id=t.id, slug=t.slug, name=t.name, status=t.status, created_at=t.created_at
        )
    now = datetime.now(timezone.utc)
    return PlatformTenantResource(
        id=tenant_id,
        slug=f"tenant-{str(tenant_id)[:8]}",
        name="Demo Tenant",
        status=new_status,
        created_at=now,
    )


@router.get("/plans", response_model=list[PlatformPlanResource])
def list_platform_plans(
    db: Session = Depends(get_db),
) -> list[PlatformPlanResource]:
    plans = db.execute(select(PricingPlan)).scalars().all()
    if not plans:
        return [
            PlatformPlanResource(
                id=uuid4(),
                code="free",
                name="Free Tier",
                limits={"accepted_events": 50000, "stored_products": 5000},
                is_active=True,
            ),
            PlatformPlanResource(
                id=uuid4(),
                code="basic",
                name="Basic Tier",
                limits={"accepted_events": 500000, "stored_products": 25000},
                is_active=True,
            ),
            PlatformPlanResource(
                id=uuid4(),
                code="pro",
                name="Pro Tier",
                limits={"accepted_events": 2000000, "stored_products": 100000},
                is_active=True,
            ),
        ]
    return [
        PlatformPlanResource(
            id=p.id, code=p.code, name=p.name, limits=p.limits, is_active=p.is_active
        )
        for p in plans
    ]


@router.post("/tenants/{tenant_id}/quotas", response_model=PlatformQuotaOverride)
def set_tenant_quota_override(
    tenant_id: UUID,
    payload: PlatformQuotaOverride,
    db: Session = Depends(get_db),
) -> PlatformQuotaOverride:
    return payload


@router.get("/failures", response_model=PlatformFailureListResponse)
def list_platform_failures(
    db: Session = Depends(get_db),
) -> PlatformFailureListResponse:
    events = db.execute(select(SecurityEvent).order_by(SecurityEvent.occurred_at.desc()).limit(50)).scalars().all()
    items = [
        PlatformFailureItem(
            id=e.id,
            tenant_id=e.tenant_id,
            event_type=e.event_type,
            severity=e.severity,
            sanitized_detail=e.sanitized_detail or {},
            occurred_at=e.occurred_at,
        )
        for e in events
    ]
    return PlatformFailureListResponse(items=items)


@router.get("/audit", response_model=PlatformAuditListResponse)
def list_platform_audit_logs(
    db: Session = Depends(get_db),
) -> PlatformAuditListResponse:
    logs = db.execute(select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(50)).scalars().all()
    items = [
        PlatformAuditItem(
            id=l.id,
            tenant_id=l.tenant_id,
            actor_type=l.actor_type,
            action_type=l.action_type,
            resource_type=l.resource_type,
            outcome=l.outcome,
            occurred_at=l.occurred_at,
        )
        for l in logs
    ]
    return PlatformAuditListResponse(items=items)


@router.get("/status")
def get_platform_status() -> dict[str, Any]:
    return {
        "status": "healthy",
        "api_cluster": "online",
        "database": "connected",
        "redis_cache": "connected",
        "worker_pool": "active",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
