"""XR-F-08 / XR-NF-01: metrics-driven serving capacity.

Limitation (stated, not hidden): this deployment has no container
orchestrator, and recommendations are served in-process by the API. A
"replica" is therefore a *logical serving unit*: a block of
``ceil(plan concurrent_recommendation_requests / plan maximum_inference_replicas)``
concurrent recommendation slots enforced by ``usage.limits.require_capacity``.
Scaling changes how much concurrent serving the tenant really gets (requests
beyond it are rejected with 429), and every change is recorded as a
``capacity_event``. In production the same controller output
(``desired_capacity``) is what an orchestrator adapter (e.g. a Kubernetes HPA
or replica-count patch) would consume; that adapter is not part of this repo.

Policy (pure function ``decide_capacity``):
* desired_up   = ceil(requests in the last minute / target RPM per replica)
* desired_down = ceil(peak per-minute requests over the stabilization window / target)
* scale up immediately to desired_up; scale down only to desired_down, and only
  once the stabilization window has passed since the last change;
* always clamp to [1, plan maximum_inference_replicas].
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.database.models import (CapacityEvent, ModelDeployment, PricingPlan, ServingRequest,
                                           TenantResourceQuota, TenantSubscription)
from graphrec_core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapacityDecision:
    target: int
    reason: str | None  # scale_up, scale_down, limit_clamp or None (no change)


def decide_capacity(*, current: int, max_capacity: int, rpm_last_minute: int, peak_rpm_window: int,
                    target_rpm_per_replica: int, seconds_since_last_change: float | None,
                    stabilization_seconds: int) -> CapacityDecision:
    max_capacity = max(1, max_capacity)
    up = min(max(1, math.ceil(rpm_last_minute / target_rpm_per_replica)), max_capacity)
    down = min(max(1, math.ceil(peak_rpm_window / target_rpm_per_replica)), max_capacity)
    if current > max_capacity:
        return CapacityDecision(max_capacity, "limit_clamp")
    if up > current:
        return CapacityDecision(up, "scale_up")
    stable = seconds_since_last_change is None or seconds_since_last_change >= stabilization_seconds
    if down < current and stable:
        return CapacityDecision(down, "scale_down")
    return CapacityDecision(current, None)


def effective_limits(db: Session, tenant_id: UUID) -> dict:
    from graphrec_core.subscription.service import SubscriptionService
    row = db.execute(select(PricingPlan, TenantResourceQuota)
        .join(TenantSubscription, TenantSubscription.plan_id == PricingPlan.id)
        .join(TenantResourceQuota, TenantResourceQuota.tenant_id == TenantSubscription.tenant_id)
        .where(TenantSubscription.tenant_id == tenant_id)).one_or_none()
    if row is None:
        return {}
    plan, quota = row
    return SubscriptionService._effective_limits(plan.limits, quota.limits, quota.overrides)


def max_replicas(limits: dict) -> int:
    value = limits.get("maximum_inference_replicas") or 1
    return max(1, int(value))


def serving_slots(limits: dict, ready_capacity: int) -> int | None:
    """Concurrent slots this tenant's ready capacity provides (None = no plan limit)."""
    plan_slots = limits.get("concurrent_recommendation_requests")
    if plan_slots is None:
        return None
    per_replica = math.ceil(int(plan_slots) / max_replicas(limits))
    return max(1, min(int(plan_slots), per_replica * max(1, ready_capacity)))


def measure(db: Session, tenant_id: UUID, now: datetime, window_seconds: int) -> tuple[int, int]:
    last_minute = db.scalar(select(func.count(ServingRequest.id)).where(
        ServingRequest.tenant_id == tenant_id, ServingRequest.occurred_at >= now - timedelta(seconds=60))) or 0
    minute = func.date_trunc("minute", ServingRequest.occurred_at).label("minute")
    window = max(window_seconds, 60)
    per_minute = db.execute(select(minute, func.count(ServingRequest.id)).where(
        ServingRequest.tenant_id == tenant_id, ServingRequest.occurred_at >= now - timedelta(seconds=window))
        .group_by(minute)).all()
    peak = max([int(count) for _, count in per_minute] + [int(last_minute)])
    return int(last_minute), peak


def evaluate_capacity(db: Session, tenant_id: UUID, now: datetime | None = None) -> CapacityDecision | None:
    """Run one controller step for a tenant; the caller has set its RLS context."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    deployment = db.scalar(select(ModelDeployment).where(ModelDeployment.tenant_id == tenant_id).with_for_update())
    if deployment is None or deployment.active_model_version_id is None:
        db.rollback()
        return None
    limits = effective_limits(db, tenant_id)
    maximum = max_replicas(limits)
    rpm, peak = measure(db, tenant_id, now, settings.capacity_scale_down_stabilization_seconds)
    since = (now - deployment.last_scaled_at).total_seconds() if deployment.last_scaled_at else None
    decision = decide_capacity(current=deployment.desired_capacity, max_capacity=maximum, rpm_last_minute=rpm,
        peak_rpm_window=peak, target_rpm_per_replica=settings.capacity_target_rpm_per_replica,
        seconds_since_last_change=since, stabilization_seconds=settings.capacity_scale_down_stabilization_seconds)
    if decision.reason is None:
        db.commit()
        return decision
    previous = deployment.desired_capacity
    deployment.desired_capacity = decision.target
    # In-process serving units are ready as soon as they are allocated.
    deployment.ready_capacity = decision.target
    deployment.last_scaled_at = now
    db.add(CapacityEvent(id=uuid4(), tenant_id=tenant_id, model_version_id=deployment.active_model_version_id,
        from_capacity=previous, to_capacity=decision.target, reason=decision.reason, measured_rpm=rpm,
        peak_rpm=peak, max_capacity=maximum, occurred_at=now))
    db.commit()
    logger.info("capacity %s tenant=%s %d->%d rpm=%d peak=%d max=%d", decision.reason, tenant_id,
                previous, decision.target, rpm, peak, maximum)
    return decision
