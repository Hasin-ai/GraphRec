from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal
from graphrec_core.database.models import (
    AuditLog,
    PricingPlan,
    TenantResourceQuota,
    TenantSubscription,
    UsageEvent,
)
from graphrec_core.errors import ApiError
from graphrec_core.schemas.usage import UsageDimension, UsageSummaryResponse
from graphrec_core.subscription.service import SubscriptionService

DIMENSIONS: tuple[tuple[str, str | None, str], ...] = (
    ("accepted_events", "accepted_events", "count"),
    ("recommendation_requests", "recommendation_requests", "count"),
    ("training_jobs", "training_jobs", "count"),
    ("training_cpu_seconds", None, "seconds"),
    ("stored_products", "stored_products", "count"),
    ("artifact_storage_bytes", "artifact_storage_bytes", "bytes"),
    ("active_model_versions", "active_model_versions", "count"),
    ("inference_replicas", "maximum_inference_replicas", "count"),
    ("replica_runtime_minutes", None, "minutes"),
)


class UsageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_current(
        self,
        principal: AuthenticatedPrincipal,
        *,
        correlation_id: UUID,
    ) -> UsageSummaryResponse:
        now = datetime.now(timezone.utc)
        period_start, period_end = self._period(now)
        try:
            quota_row = self.session.execute(
                select(TenantSubscription, PricingPlan, TenantResourceQuota)
                .join(PricingPlan, PricingPlan.id == TenantSubscription.plan_id)
                .join(
                    TenantResourceQuota,
                    TenantResourceQuota.tenant_id == TenantSubscription.tenant_id,
                )
                .where(TenantSubscription.tenant_id == principal.tenant_id)
            ).one_or_none()
            if quota_row is None:
                raise self._unavailable()
            subscription, plan, quota = quota_row
            limits = SubscriptionService._effective_limits(
                plan.limits, quota.limits, quota.overrides
            )

            totals = {
                usage_type: quantity
                for usage_type, quantity in self.session.execute(
                    select(UsageEvent.usage_type, func.sum(UsageEvent.quantity))
                    .where(
                        UsageEvent.tenant_id == principal.tenant_id,
                        UsageEvent.occurred_at >= period_start,
                        UsageEvent.occurred_at < period_end,
                    )
                    .group_by(UsageEvent.usage_type)
                )
            }
            reconciled_at = datetime.now(timezone.utc)
            dimensions = [
                self._dimension(
                    usage_type=usage_type,
                    limit_key=limit_key,
                    unit=unit,
                    used=totals.get(usage_type, Decimal(0)),
                    effective_limits=limits,
                )
                for usage_type, limit_key, unit in DIMENSIONS
            ]
            response = UsageSummaryResponse(
                period_start=period_start,
                period_end=period_end,
                reset_at=period_end,
                dimensions=dimensions,
                last_reconciled_at=reconciled_at,
                project_defaults=subscription.project_defaults,
            )
            self.session.add(
                AuditLog(
                    id=uuid4(),
                    tenant_id=principal.tenant_id,
                    actor_type=principal.actor_type,
                    actor_reference=principal.actor_reference,
                    action_type="usage_read",
                    resource_type="usage_summary",
                    resource_reference=None,
                    outcome="succeeded",
                    correlation_reference=correlation_id,
                    redacted_details={
                        "period_start": period_start.isoformat(),
                        "dimension_count": len(dimensions),
                    },
                    occurred_at=reconciled_at,
                )
            )
            self.session.commit()
            return response
        except ApiError:
            self.session.rollback()
            raise
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            self.session.rollback()
            raise self._unavailable() from exc

    @staticmethod
    def _dimension(
        *,
        usage_type: str,
        limit_key: str | None,
        unit: str,
        used: Decimal,
        effective_limits: dict[str, int],
    ) -> UsageDimension:
        limit = effective_limits.get(limit_key) if limit_key is not None else None
        remaining = None if limit is None else max(Decimal(limit) - used, Decimal(0))
        return UsageDimension(
            type=usage_type,
            used=UsageService._public_number(used),
            limit=limit,
            remaining=(
                UsageService._public_number(remaining) if remaining is not None else None
            ),
            unit=unit,
        )

    @staticmethod
    def _public_number(value: Decimal) -> int | float:
        return int(value) if value == value.to_integral_value() else float(value)

    @staticmethod
    def _period(now: datetime) -> tuple[datetime, datetime]:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        if now.month == 12:
            end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        return start, end

    @staticmethod
    def _unavailable() -> ApiError:
        return ApiError(
            503,
            "metrics_unavailable",
            "Usage information is temporarily unavailable",
            retryable=True,
            retry_after_seconds=5,
        )
