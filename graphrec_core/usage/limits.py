"""Transactional admission checks shared by bounded tenant operations."""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from graphrec_core.database.models import ModelDeployment, ModelVersion, PricingPlan, Product, ServingRequest, TenantResourceQuota, TenantSubscription, TrainingJob, UsageEvent
from graphrec_core.errors import ApiError
from graphrec_core.subscription.service import SubscriptionService


def lock_dimension(db: Session, tenant_id: UUID, dimension: str) -> None:
    key = int.from_bytes(hashlib.sha256(f"quota:{tenant_id}:{dimension}".encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def require_capacity(db: Session, tenant_id: UUID, dimension: str, quantity: int = 1) -> None:
    if dimension != "concurrent_recommendation_requests":
        lock_dimension(db, tenant_id, dimension)
    row = db.execute(select(PricingPlan, TenantResourceQuota)
        .join(TenantSubscription, TenantSubscription.plan_id == PricingPlan.id)
        .join(TenantResourceQuota, TenantResourceQuota.tenant_id == TenantSubscription.tenant_id)
        .where(TenantSubscription.tenant_id == tenant_id)).one_or_none()
    if row is None:
        raise ApiError(503, "quota_unavailable", "Usage limits are temporarily unavailable.", retryable=True)
    plan, quota = row
    limits = SubscriptionService._effective_limits(plan.limits, quota.limits, quota.overrides)
    limit = limits.get(dimension)
    if limit is None:
        raise ApiError(503, "quota_unavailable", "The required usage limit is unavailable.", retryable=True)
    if dimension == "concurrent_recommendation_requests":
        # XR-F-08: an active deployment serves with the slots its scaled
        # capacity provides; without one the plan limit applies unchanged.
        from graphrec_core.capacity import serving_slots
        ready = db.scalar(select(ModelDeployment.ready_capacity).where(
            ModelDeployment.tenant_id == tenant_id, ModelDeployment.active_model_version_id.is_not(None)))
        if ready:
            limit = serving_slots(limits, ready) or limit
        # A bounded number of transaction-scoped slots, shared across API workers.
        for slot in range(min(limit, 30)):
            key = int.from_bytes(hashlib.sha256(f"serving-slot:{tenant_id}:{slot}".encode()).digest()[:8], "big", signed=True)
            if db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
                return
        raise ApiError(429, "quota_exceeded", "Concurrent recommendation capacity is in use.", retryable=True,
            retry_after_seconds=1, details={"limit_name": dimension, "limit": min(limit, 30)})
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    reset = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    if dimension == "requests_per_minute":
        used = db.scalar(select(func.count(ServingRequest.id)).where(ServingRequest.tenant_id == tenant_id,
            ServingRequest.occurred_at >= now - timedelta(seconds=60))) or 0
        if used + quantity > limit:
            raise ApiError(429, "quota_exceeded", "The recommendation request rate limit has been reached.",
                retryable=True, retry_after_seconds=60, details={"limit_name": dimension, "limit": limit, "used": used})
        return
    if dimension == "stored_products":
        used = db.scalar(select(func.count(Product.id)).where(Product.tenant_id == tenant_id)) or 0
    elif dimension == "artifact_storage_bytes":
        used = artifact_storage_used(db, tenant_id)
    elif dimension == "active_model_versions":
        used = db.scalar(select(func.count(ModelVersion.id)).where(ModelVersion.tenant_id == tenant_id, ModelVersion.status == 'active')) or 0
    else:
        used = db.scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.usage_type == dimension,
            UsageEvent.occurred_at >= start, UsageEvent.occurred_at < reset)) or 0
        if dimension == "training_jobs":
            used = max(0, used - unstarted_cancelled_training_jobs(db, tenant_id, start, reset))
    if used + quantity > limit:
        raise ApiError(429, "quota_exceeded", f"The {dimension} limit has been reached.",
            details={"limit_name": dimension, "limit": limit, "used": int(used),
                     "requested": quantity, "reset_at": reset.isoformat() if dimension != "stored_products" else None})


def unstarted_cancelled_training_jobs(db: Session, tenant_id: UUID, start: datetime, end: datetime) -> int:
    """Jobs cancelled while still queued never used capacity. The usage ledger is
    append-only, so they are credited back when quota is evaluated."""
    return db.scalar(select(func.count(TrainingJob.id)).where(
        TrainingJob.tenant_id == tenant_id, TrainingJob.status == "cancelled",
        TrainingJob.progress == 0, TrainingJob.attempts == 0,
        TrainingJob.created_at >= start, TrainingJob.created_at < end)) or 0


def artifact_storage_used(db: Session, tenant_id: UUID) -> int:
    metrics = db.scalars(select(ModelVersion.metrics).where(ModelVersion.tenant_id == tenant_id, ModelVersion.status != 'archived'))
    total = 0
    for value in metrics:
        size = (value or {}).get('source', {}).get('artifact_bytes', 0)
        if isinstance(size, int) and not isinstance(size, bool):
            total += max(0, size)
    return total
