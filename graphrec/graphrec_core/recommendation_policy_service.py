"""Tenant-scoped storage for XR-F-04 re-ranking rules."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import AuditLog, RecommendationPolicy
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.recommendation_rules import RuleSet
from graphrec_core.schemas.recommendation_policy import RecommendationPolicyResource, RecommendationPolicyUpdate


def load_rules(db: Session, tenant_id: UUID) -> RuleSet | None:
    row = db.scalar(select(RecommendationPolicy).where(RecommendationPolicy.tenant_id == tenant_id))
    if row is None:
        return None
    rules = RuleSet(version=row.version, diversity_enabled=row.diversity_enabled,
                    max_per_category=row.max_per_category, freshness_enabled=row.freshness_enabled,
                    freshness_weight=float(row.freshness_weight), freshness_half_life_days=row.freshness_half_life_days)
    return rules if rules.active else None


class RecommendationPolicyService:
    def __init__(self, db: Session, principal=None, correlation_id: UUID | None = None):
        self.db, self.principal, self.correlation_id = db, principal, correlation_id or uuid4()

    def get(self, tenant_id: UUID) -> RecommendationPolicyResource:
        row = self.db.scalar(select(RecommendationPolicy).where(RecommendationPolicy.tenant_id == tenant_id))
        if row is None:
            return RecommendationPolicyResource(tenant_id=tenant_id, configured=False, version=0)
        return RecommendationPolicyResource(tenant_id=tenant_id, configured=True, version=row.version,
            diversity_enabled=row.diversity_enabled, max_per_category=row.max_per_category,
            freshness_enabled=row.freshness_enabled, freshness_weight=float(row.freshness_weight),
            freshness_half_life_days=row.freshness_half_life_days, updated_at=row.updated_at)

    def update(self, tenant_id: UUID, payload: RecommendationPolicyUpdate) -> RecommendationPolicyResource:
        now = datetime.now(timezone.utc)
        row = self.db.scalar(select(RecommendationPolicy).where(RecommendationPolicy.tenant_id == tenant_id).with_for_update())
        values = dict(diversity_enabled=payload.diversity_enabled, max_per_category=payload.max_per_category,
                      freshness_enabled=payload.freshness_enabled,
                      freshness_weight=Decimal(str(round(payload.freshness_weight, 3))),
                      freshness_half_life_days=payload.freshness_half_life_days)
        if row is None:
            row = RecommendationPolicy(tenant_id=tenant_id, version=1, updated_at=now, **values)
            self.db.add(row)
        else:
            changed = any(getattr(row, k) != v for k, v in values.items())
            for k, v in values.items():
                setattr(row, k, v)
            if changed:
                row.version += 1  # XR-NF-02: every effective change is a new, explainable version
                row.updated_at = now
        self.db.add(AuditLog(id=uuid4(), tenant_id=tenant_id,
            actor_type=self.principal.actor_type if self.principal else "system",
            actor_reference=self.principal.actor_reference if self.principal else None,
            action_type="recommendation_policy_updated", resource_type="recommendation_policy",
            resource_reference=tenant_id, outcome="succeeded", correlation_reference=self.correlation_id,
            redacted_details={**payload.model_dump(), "version": row.version}, occurred_at=now))
        self.db.commit()
        set_local_tenant(self.db, tenant_id)
        return self.get(tenant_id)
