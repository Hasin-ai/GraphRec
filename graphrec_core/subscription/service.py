from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal
from graphrec_core.database.models import (
    AuditLog,
    PricingPlan,
    TenantResourceQuota,
    TenantSubscription,
)
from graphrec_core.errors import ApiError
from graphrec_core.schemas.subscription import SubscriptionResponse


class SubscriptionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_current(
        self,
        principal: AuthenticatedPrincipal,
        *,
        correlation_id: UUID,
    ) -> SubscriptionResponse:
        try:
            row = self.session.execute(
                select(TenantSubscription, PricingPlan, TenantResourceQuota)
                .join(PricingPlan, PricingPlan.id == TenantSubscription.plan_id)
                .join(
                    TenantResourceQuota,
                    TenantResourceQuota.tenant_id == TenantSubscription.tenant_id,
                )
                .where(TenantSubscription.tenant_id == principal.tenant_id)
            ).one_or_none()
            if row is None:
                raise self._unavailable()

            subscription, plan, quota = row
            limits = self._effective_limits(plan.limits, quota.limits, quota.overrides)
            if plan.code not in {"free", "basic", "pro"}:
                raise self._unavailable()

            response = SubscriptionResponse(
                plan_code=plan.code,
                status=subscription.status,
                period_start=subscription.period_start,
                period_end=subscription.period_end,
                limits=limits,
                project_defaults=subscription.project_defaults,
            )
            self.session.add(
                AuditLog(
                    id=uuid4(),
                    tenant_id=principal.tenant_id,
                    actor_type=principal.actor_type,
                    actor_reference=principal.actor_reference,
                    action_type="subscription_read",
                    resource_type="tenant_subscription",
                    resource_reference=subscription.id,
                    outcome="succeeded",
                    correlation_reference=correlation_id,
                    redacted_details={
                        "plan_code": plan.code,
                        "project_defaults": subscription.project_defaults,
                    },
                    occurred_at=datetime.now(timezone.utc),
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
    def _effective_limits(
        plan_limits: object,
        quota_limits: object,
        overrides: object,
    ) -> dict[str, int]:
        if not isinstance(plan_limits, dict) or not isinstance(quota_limits, dict):
            raise ValueError("invalid quota source")
        override_values = overrides if isinstance(overrides, dict) else {}
        effective: dict[str, int] = {}
        for key, plan_value in plan_limits.items():
            value = quota_limits.get(key, plan_value)
            if key in override_values:
                value = override_values[key]
            if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("invalid effective limit")
            effective[key] = value
        return effective

    @staticmethod
    def _unavailable() -> ApiError:
        return ApiError(
            503,
            "service_unavailable",
            "Subscription information is temporarily unavailable",
            retryable=True,
            retry_after_seconds=5,
        )
