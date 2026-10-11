"""Plan change requests: filed by a tenant administrator, decided by a platform operator.

GraphRec has no payment flow, so plans change only by operator approval. A
tenant may hold one pending request at a time, for any active plan other than
its current one; it may withdraw it while it is pending. Approval activates
the plan atomically (``platform_decide_plan_request`` -> ``platform_assign_plan``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from graphrec_core.auth.principal import AuthenticatedPrincipal
from graphrec_core.database.models import AuditLog, PlanChangeRequest, PricingPlan, TenantSubscription
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.plan_requests import (
    PlanChangeRequestCreate,
    PlanChangeRequestList,
    PlanChangeRequestResource,
    PlatformPlanChangeRequest,
)

HISTORY_LIMIT = 20


class PlanRequestService:
    def __init__(self, db: Session, principal: AuthenticatedPrincipal, correlation_id: UUID) -> None:
        self.db, self.principal, self.correlation_id = db, principal, correlation_id

    # -- reads --------------------------------------------------------------------------

    def list(self) -> PlanChangeRequestList:
        items = self._resources(
            select(PlanChangeRequest).where(PlanChangeRequest.tenant_id == self.principal.tenant_id)
            .order_by(PlanChangeRequest.created_at.desc()).limit(HISTORY_LIMIT)
        )
        pending = next((item for item in items if item.status == "pending"), None)
        return PlanChangeRequestList(items=items, pending=pending)

    def _resources(self, query) -> list[PlanChangeRequestResource]:
        current, requested = aliased(PricingPlan), aliased(PricingPlan)
        rows = self.db.execute(
            query.add_columns(current.code, current.name, requested.code, requested.name)
            .join(current, current.id == PlanChangeRequest.current_plan_id)
            .join(requested, requested.id == PlanChangeRequest.requested_plan_id)
        ).all()
        return [
            PlanChangeRequestResource(
                id=r.id, status=r.status, current_plan_code=cc, current_plan_name=cn,
                requested_plan_code=rc, requested_plan_name=rn, message=r.message,
                decision_reason=r.decision_reason, created_at=r.created_at, decided_at=r.decided_at,
            )
            for r, cc, cn, rc, rn in rows
        ]

    def _one(self, request_id: UUID) -> PlanChangeRequestResource:
        # The tenant context is transaction-local; a commit ends it.
        set_local_tenant(self.db, self.principal.tenant_id)
        found = self._resources(select(PlanChangeRequest).where(
            PlanChangeRequest.id == request_id, PlanChangeRequest.tenant_id == self.principal.tenant_id))
        if not found:
            raise ApiError(404, "resource_not_found", f"Plan request '{request_id}' not found.")
        return found[0]

    # -- writes -------------------------------------------------------------------------

    def create(self, payload: PlanChangeRequestCreate) -> PlanChangeRequestResource:
        tenant_id = self.principal.tenant_id
        current_plan_id = self.db.scalar(select(TenantSubscription.plan_id).where(TenantSubscription.tenant_id == tenant_id))
        if current_plan_id is None:
            raise ApiError(503, "service_unavailable", "Subscription information is temporarily unavailable",
                           retryable=True, retry_after_seconds=5)
        plan = self.db.scalar(select(PricingPlan).where(PricingPlan.code == payload.plan_code, PricingPlan.is_active.is_(True)))
        if plan is None:
            raise ApiError(422, "plan_not_available", f"The '{payload.plan_code}' plan is not open for requests.")
        if plan.id == current_plan_id:
            raise ApiError(409, "plan_already_active", f"This workspace is already on the {plan.name} plan.")
        pending = self.db.scalar(select(PlanChangeRequest.id).where(
            PlanChangeRequest.tenant_id == tenant_id, PlanChangeRequest.status == "pending"))
        if pending is not None:
            raise ApiError(409, "plan_request_pending",
                           "A plan request is already waiting for approval. Cancel it to ask for a different plan.",
                           details={"request_id": str(pending)})
        now = datetime.now(timezone.utc)
        request = PlanChangeRequest(
            id=uuid4(), tenant_id=tenant_id, current_plan_id=current_plan_id, requested_plan_id=plan.id,
            status="pending", message=payload.message, requested_by=str(self.principal.actor_reference),
            created_at=now,
        )
        self.db.add(request)
        self._audit("plan_request.created", request.id, {"requested_plan_code": plan.code})
        try:
            self.db.commit()
        except IntegrityError as exc:   # a concurrent request won the one-pending index
            self.db.rollback()
            raise ApiError(409, "plan_request_pending",
                           "A plan request is already waiting for approval.") from exc
        return self._one(request.id)

    def cancel(self, request_id: UUID) -> PlanChangeRequestResource:
        request = self.db.scalar(select(PlanChangeRequest).where(
            PlanChangeRequest.id == request_id, PlanChangeRequest.tenant_id == self.principal.tenant_id))
        if request is None:
            raise ApiError(404, "resource_not_found", f"Plan request '{request_id}' not found.")
        if request.status != "pending":
            raise ApiError(409, "plan_request_closed", f"This request was already {request.status}.")
        request.status, request.decided_at = "cancelled", datetime.now(timezone.utc)
        self._audit("plan_request.cancelled", request.id, {})
        self.db.commit()
        return self._one(request_id)

    def _audit(self, action: str, request_id: UUID, details: dict) -> None:
        self.db.add(AuditLog(
            id=uuid4(), tenant_id=self.principal.tenant_id, actor_type=self.principal.actor_type,
            actor_reference=self.principal.actor_reference, action_type=action,
            resource_type="plan_change_request", resource_reference=request_id, outcome="succeeded",
            correlation_reference=self.correlation_id, redacted_details=details,
            occurred_at=datetime.now(timezone.utc),
        ))


# -- platform side --------------------------------------------------------------------

STATUSES = frozenset({"pending", "approved", "rejected", "cancelled"})


def platform_list(db: Session, status: str | None) -> list[PlatformPlanChangeRequest]:
    rows = db.execute(text("SELECT * FROM public.platform_list_plan_requests(:status)"), {"status": status}).mappings().all()
    return [PlatformPlanChangeRequest(**row) for row in rows]


def platform_pending_count(db: Session) -> int:
    return int(db.scalar(text("SELECT public.platform_pending_plan_request_count()")) or 0)


def platform_get(db: Session, request_id: UUID) -> PlatformPlanChangeRequest | None:
    return next((r for r in platform_list(db, None) if r.id == request_id), None)
