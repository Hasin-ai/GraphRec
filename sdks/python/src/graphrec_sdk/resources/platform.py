"""Platform-operator endpoints (``/v1/platform/*``).

Authenticated with the server's ``PLATFORM_ADMIN_TOKEN`` sent as a bearer token;
the routes are disabled when that setting is empty. Exposed on the client as
``client.platform.tenants``, ``client.platform.plans`` and operations methods on
``client.platform`` itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Union, cast
from uuid import UUID

from ..enums import TenantStatus
from ..errors import InputValidationError
from ..models.billing import UsageSummary
from ..models.platform import (
    PlatformUsageList,
    AuditRecordList,
    PlatformFailureList,
    PlatformStatus,
    PlatformTenant,
    PlatformTenantList,
    PricingPlan,
    PricingPlanList,
    QuotaOverride,
    RecoveryToken,
    TenantQuota,
)
from ._base import AsyncResource, SyncResource

__all__ = [
    "AsyncPlatformOperations",
    "AsyncPlatformPlans",
    "AsyncPlatformTenants",
    "PlatformOperations",
    "PlatformPlans",
    "PlatformTenants",
]

StatusLike = Union[TenantStatus, str]
Id = Union[str, UUID]
MAX_LIMIT = 9_000_000_000_000_000


def _status_body(status: StatusLike) -> Dict[str, str]:
    value = str(getattr(status, "value", status))
    if not value.strip() or len(value) > 20:
        raise InputValidationError("status must be 1-20 characters, e.g. TenantStatus.SUSPENDED")
    return {"status": value}


def _quota_body(
    overrides: Mapping[str, Any], acknowledge_below_usage: bool = False
) -> Dict[str, Any]:
    if not isinstance(overrides, Mapping):
        raise InputValidationError("overrides must be a mapping of limit name to value")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in overrides.values()):
        raise InputValidationError("quota overrides must be non-negative integers")
    body: Dict[str, Any] = {"overrides": dict(overrides)}
    if acknowledge_below_usage:
        body["acknowledge_below_usage"] = True
    return body


def _plan_body(
    name: str, limits: Mapping[str, int], is_active: bool, acknowledge_below_usage: bool = False
) -> Dict[str, Any]:
    if not name.strip() or len(name) > 100 or not limits:
        raise InputValidationError("name and all supported plan limits are required")
    if any(
        not key
        or isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_LIMIT
        for key, value in limits.items()
    ):
        raise InputValidationError("plan limits must be non-negative integers")
    body: Dict[str, Any] = {"name": name.strip(), "limits": dict(limits), "is_active": is_active}
    if acknowledge_below_usage:
        body["acknowledge_below_usage"] = True
    return body


def _assign_body(plan_id: Id, acknowledge_below_usage: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {"plan_id": str(plan_id)}
    if acknowledge_below_usage:
        body["acknowledge_below_usage"] = True
    return body


def _tid(tenant_id: Id) -> Dict[str, Id]:
    return {"tenant_id": tenant_id}



def _reason_body(reason: Optional[str]) -> Dict[str, str]:
    """ER-F-11: an optional human reason stored with the action's audit record."""
    if reason is None:
        return {}
    if not 3 <= len(reason.strip()) <= 500:
        raise InputValidationError("reason must be 3-500 characters")
    return {"reason": reason.strip()}


class PlatformTenants(SyncResource):
    """Tenant lifecycle, quotas and usage across the platform."""

    def list(self) -> PlatformTenantList:
        """Every tenant with its status. ``GET /v1/platform/tenants``."""

        return cast(
            PlatformTenantList,
            self._client.request("platform.list_tenants", cast_to=PlatformTenantList),
        )

    def get(self, tenant_id: Id) -> PlatformTenant:
        """``GET /v1/platform/tenants/{tenant_id}``. Raises :class:`~graphrec_sdk.NotFoundError`."""

        return cast(
            PlatformTenant,
            self._client.request(
                "platform.get_tenant", path_params=_tid(tenant_id), cast_to=PlatformTenant
            ),
        )

    def set_status(self, tenant_id: Id, status: StatusLike, *, reason: str) -> PlatformTenant:
        """Change a tenant's lifecycle status (see :class:`~graphrec_sdk.TenantStatus`).

        ``POST /v1/platform/tenants/{tenant_id}/status``. The change is audited.
        """

        return cast(
            PlatformTenant,
            self._client.request(
                "platform.set_tenant_status",
                path_params=_tid(tenant_id),
                json={**_status_body(status), **_reason_body(reason)},
                cast_to=PlatformTenant,
            ),
        )

    def get_quota(self, tenant_id: Id) -> TenantQuota:
        """Plan, overrides and effective limits. ``GET /v1/platform/tenants/{tenant_id}/quotas``."""

        return cast(
            TenantQuota,
            self._client.request(
                "platform.get_tenant_quota", path_params=_tid(tenant_id), cast_to=TenantQuota
            ),
        )

    def set_quota_override(
        self, tenant_id: Id, *, overrides: Mapping[str, int], acknowledge_below_usage: bool = False,
        reason: Optional[str] = None
    ) -> QuotaOverride:
        """Replace a tenant's quota overrides; returns effective limits and stored overrides.

        ``POST /v1/platform/tenants/{tenant_id}/quotas``, e.g.
        ``overrides={"accepted_events": 1_000_000}``. Lowering an inventory limit
        below what the tenant stores raises :class:`~graphrec_sdk.LimitBelowUsageError`
        unless ``acknowledge_below_usage=True``; the result's ``warnings`` then
        lists the exceeded limits. The change is audited.
        """

        return cast(
            QuotaOverride,
            self._client.request(
                "platform.set_quota_override",
                path_params=_tid(tenant_id),
                json={**_quota_body(overrides, acknowledge_below_usage), **_reason_body(reason)},
                cast_to=QuotaOverride,
            ),
        )

    def assign_plan(
        self, tenant_id: Id, plan_id: Id, *, acknowledge_below_usage: bool = False,
        reason: Optional[str] = None
    ) -> TenantQuota:
        """Move a tenant to another active plan. ``POST /v1/platform/tenants/{tenant_id}/plan``.

        Raises :class:`~graphrec_sdk.LimitBelowUsageError` when the new plan is below
        the tenant's stored inventory, unless ``acknowledge_below_usage=True``.
        """

        return cast(
            TenantQuota,
            self._client.request(
                "platform.assign_tenant_plan",
                path_params=_tid(tenant_id),
                json={**_assign_body(plan_id, acknowledge_below_usage), **_reason_body(reason)},
                cast_to=TenantQuota,
            ),
        )

    def get_usage(self, tenant_id: Id) -> UsageSummary:
        """Month-to-date usage of one tenant. ``GET /v1/platform/tenants/{tenant_id}/usage``."""

        return cast(
            UsageSummary,
            self._client.request(
                "platform.get_tenant_usage", path_params=_tid(tenant_id), cast_to=UsageSummary
            ),
        )

    def issue_recovery(self, tenant_id: Id, *, email: str, reason: Optional[str] = None) -> RecoveryToken:
        """Issue a one-time account-recovery token for a user of an active tenant.

        ``POST /v1/platform/tenants/{tenant_id}/recovery``. Hand the token to the
        user, who redeems it with ``client.tenant.auth.recover_password``.
        """

        return cast(
            RecoveryToken,
            self._client.request(
                "platform.issue_recovery",
                path_params=_tid(tenant_id),
                json={**{"email": email}, **_reason_body(reason)},
                cast_to=RecoveryToken,
            ),
        )


class AsyncPlatformTenants(AsyncResource):
    """Async variant of :class:`PlatformTenants`."""

    async def list(self) -> PlatformTenantList:
        """Async variant of :meth:`PlatformTenants.list`."""

        return cast(
            PlatformTenantList,
            await self._client.request("platform.list_tenants", cast_to=PlatformTenantList),
        )

    async def get(self, tenant_id: Id) -> PlatformTenant:
        """Async variant of :meth:`PlatformTenants.get`."""

        return cast(
            PlatformTenant,
            await self._client.request(
                "platform.get_tenant", path_params=_tid(tenant_id), cast_to=PlatformTenant
            ),
        )

    async def set_status(self, tenant_id: Id, status: StatusLike, *, reason: str) -> PlatformTenant:
        """Async variant of :meth:`PlatformTenants.set_status`."""

        return cast(
            PlatformTenant,
            await self._client.request(
                "platform.set_tenant_status",
                path_params=_tid(tenant_id),
                json={**_status_body(status), **_reason_body(reason)},
                cast_to=PlatformTenant,
            ),
        )

    async def get_quota(self, tenant_id: Id) -> TenantQuota:
        """Async variant of :meth:`PlatformTenants.get_quota`."""

        return cast(
            TenantQuota,
            await self._client.request(
                "platform.get_tenant_quota", path_params=_tid(tenant_id), cast_to=TenantQuota
            ),
        )

    async def set_quota_override(
        self, tenant_id: Id, *, overrides: Mapping[str, int], acknowledge_below_usage: bool = False,
        reason: Optional[str] = None
    ) -> QuotaOverride:
        """Async variant of :meth:`PlatformTenants.set_quota_override`."""

        return cast(
            QuotaOverride,
            await self._client.request(
                "platform.set_quota_override",
                path_params=_tid(tenant_id),
                json={**_quota_body(overrides, acknowledge_below_usage), **_reason_body(reason)},
                cast_to=QuotaOverride,
            ),
        )

    async def assign_plan(
        self, tenant_id: Id, plan_id: Id, *, acknowledge_below_usage: bool = False,
        reason: Optional[str] = None
    ) -> TenantQuota:
        """Async variant of :meth:`PlatformTenants.assign_plan`."""

        return cast(
            TenantQuota,
            await self._client.request(
                "platform.assign_tenant_plan",
                path_params=_tid(tenant_id),
                json={**_assign_body(plan_id, acknowledge_below_usage), **_reason_body(reason)},
                cast_to=TenantQuota,
            ),
        )

    async def get_usage(self, tenant_id: Id) -> UsageSummary:
        """Async variant of :meth:`PlatformTenants.get_usage`."""

        return cast(
            UsageSummary,
            await self._client.request(
                "platform.get_tenant_usage", path_params=_tid(tenant_id), cast_to=UsageSummary
            ),
        )

    async def issue_recovery(self, tenant_id: Id, *, email: str, reason: Optional[str] = None) -> RecoveryToken:
        """Async variant of :meth:`PlatformTenants.issue_recovery`."""

        return cast(
            RecoveryToken,
            await self._client.request(
                "platform.issue_recovery",
                path_params=_tid(tenant_id),
                json={**{"email": email}, **_reason_body(reason)},
                cast_to=RecoveryToken,
            ),
        )


class PlatformPlans(SyncResource):
    """Pricing plans and their limits."""

    def list(self) -> PricingPlanList:
        """Every plan, ordered by code. ``GET /v1/platform/plans``."""

        items = self._client.request("platform.list_plans", cast_to=List[PricingPlan])
        return PricingPlanList(items=items)

    def update(
        self,
        plan_id: Id,
        *,
        name: str,
        limits: Mapping[str, int],
        is_active: bool,
        acknowledge_below_usage: bool = False,
        reason: Optional[str] = None
    ) -> PricingPlan:
        """Rename, re-limit or (de)activate a plan. ``PUT /v1/platform/plans/{plan_id}``.

        ``limits`` must name every limit the plan already has, exactly once.
        Raises :class:`~graphrec_sdk.LimitBelowUsageError` when tenants on the plan
        store more than the new inventory limits, unless ``acknowledge_below_usage=True``.
        """

        return cast(
            PricingPlan,
            self._client.request(
                "platform.update_plan",
                path_params={"plan_id": plan_id},
                json={**_plan_body(name, limits, is_active, acknowledge_below_usage), **_reason_body(reason)},
                cast_to=PricingPlan,
            ),
        )


class AsyncPlatformPlans(AsyncResource):
    """Async variant of :class:`PlatformPlans`."""

    async def list(self) -> PricingPlanList:
        """Async variant of :meth:`PlatformPlans.list`."""

        items = await self._client.request("platform.list_plans", cast_to=List[PricingPlan])
        return PricingPlanList(items=items)

    async def update(
        self,
        plan_id: Id,
        *,
        name: str,
        limits: Mapping[str, int],
        is_active: bool,
        acknowledge_below_usage: bool = False,
        reason: Optional[str] = None
    ) -> PricingPlan:
        """Async variant of :meth:`PlatformPlans.update`."""

        return cast(
            PricingPlan,
            await self._client.request(
                "platform.update_plan",
                path_params={"plan_id": plan_id},
                json={**_plan_body(name, limits, is_active, acknowledge_below_usage), **_reason_body(reason)},
                cast_to=PricingPlan,
            ),
        )


class PlatformOperations(SyncResource):
    """Cross-tenant monitoring: service health, failures and audit trail."""

    def status(self) -> PlatformStatus:
        """Shared service health (``GET /v1/platform/status``)."""

        return cast(PlatformStatus, self._client.request("platform.status", cast_to=PlatformStatus))

    def list_usage(self) -> PlatformUsageList:
        """UC-29: every tenant's usage against its limits (``GET /v1/platform/usage``)."""

        return cast(PlatformUsageList, self._client.request("platform.list_usage", cast_to=PlatformUsageList))

    def list_failures(self) -> PlatformFailureList:
        """The 50 latest security/failure events (``GET /v1/platform/failures``)."""

        return cast(
            PlatformFailureList,
            self._client.request("platform.list_failures", cast_to=PlatformFailureList),
        )

    def list_audit_logs(
        self,
        *,
        tenant_id: Optional[Id] = None,
        action: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        before: Optional[datetime] = None,
        limit: int = 50,
    ) -> AuditRecordList:
        """Audit records across tenants, newest first (``GET /v1/platform/audit``).

        Filter by tenant, action, outcome or time range; page with ``before=result.next_before``.
        """

        query: Dict[str, object] = {"limit": limit}
        for key, value in (("tenant_id", tenant_id), ("action", action), ("outcome", outcome),
                           ("since", since), ("until", until), ("before", before)):
            if value is not None:
                query[key] = value.isoformat() if isinstance(value, datetime) else str(value)
        return cast(
            AuditRecordList,
            self._client.request("platform.list_audit_logs", query=query, cast_to=AuditRecordList),
        )


class AsyncPlatformOperations(AsyncResource):
    """Async variant of :class:`PlatformOperations`."""

    async def status(self) -> PlatformStatus:
        """Async variant of :meth:`PlatformOperations.status`."""

        return cast(
            PlatformStatus, await self._client.request("platform.status", cast_to=PlatformStatus)
        )

    async def list_usage(self) -> PlatformUsageList:
        """UC-29: every tenant's usage against its limits (``GET /v1/platform/usage``)."""

        return cast(PlatformUsageList, await self._client.request("platform.list_usage", cast_to=PlatformUsageList))

    async def list_failures(self) -> PlatformFailureList:
        """Async variant of :meth:`PlatformOperations.list_failures`."""

        return cast(
            PlatformFailureList,
            await self._client.request("platform.list_failures", cast_to=PlatformFailureList),
        )

    async def list_audit_logs(
        self,
        *,
        tenant_id: Optional[Id] = None,
        action: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        before: Optional[datetime] = None,
        limit: int = 50,
    ) -> AuditRecordList:
        """Audit records across tenants, newest first (``GET /v1/platform/audit``).

        Filter by tenant, action, outcome or time range; page with ``before=result.next_before``.
        """

        query: Dict[str, object] = {"limit": limit}
        for key, value in (("tenant_id", tenant_id), ("action", action), ("outcome", outcome),
                           ("since", since), ("until", until), ("before", before)):
            if value is not None:
                query[key] = value.isoformat() if isinstance(value, datetime) else str(value)
        return cast(
            AuditRecordList,
            await self._client.request("platform.list_audit_logs", query=query, cast_to=AuditRecordList),
        )