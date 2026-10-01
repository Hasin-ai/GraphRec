from __future__ import annotations

from typing import Any, Dict, List, Mapping, Union, cast
from uuid import UUID

from ..enums import TenantStatus
from ..errors import InputValidationError
from ..models.billing import UsageSummary
from ..models.platform import (
    AuditRecordList,
    PlatformFailureList,
    PlatformTenant,
    PlatformTenantList,
    PricingPlan,
    PricingPlanList,
    QuotaOverride,
    TenantQuota,
)
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncPlatform", "Platform"]

StatusLike = Union[TenantStatus, str]


def _status_body(status: StatusLike) -> Dict[str, str]:
    value = str(getattr(status, "value", status))
    if not value.strip() or len(value) > 20:
        raise InputValidationError("status must be 1-20 characters, e.g. TenantStatus.SUSPENDED")
    return {"status": value}


def _quota_body(overrides: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(overrides, Mapping):
        raise InputValidationError("overrides must be a mapping of limit name to value")
    return {"overrides": dict(overrides)}


def _plan_body(name: str, limits: Mapping[str, int], is_active: bool) -> Dict[str, Any]:
    if not name.strip() or len(name) > 100 or not limits:
        raise InputValidationError("name and all supported plan limits are required")
    if any(not key or isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 9_000_000_000_000_000
           for key, value in limits.items()):
        raise InputValidationError("plan limits must be non-negative integers")
    return {"name": name.strip(), "limits": dict(limits), "is_active": is_active}


class Platform(SyncResource):
    """Platform-operator endpoints (``/v1/platform/*``).

    Authenticated with the server's ``PLATFORM_ADMIN_TOKEN`` shared secret sent
    as a bearer token. The routes are disabled when that setting is empty::

        ops = GraphRec(access_token=os.environ["PLATFORM_ADMIN_TOKEN"])
        for tenant in ops.platform.list_tenants():
            print(tenant.slug, tenant.status)
    """

    def list_tenants(self) -> PlatformTenantList:
        """``GET /v1/platform/tenants``."""

        return cast(
            PlatformTenantList,
            self._client.request("platform.list_tenants", cast_to=PlatformTenantList),
        )

    def get_tenant(self, tenant_id: Union[str, UUID]) -> PlatformTenant:
        """``GET /v1/platform/tenants/{tenant_id}``. Raises :class:`~graphrec_sdk.NotFoundError`."""

        return cast(
            PlatformTenant,
            self._client.request(
                "platform.get_tenant", path_params={"tenant_id": tenant_id}, cast_to=PlatformTenant
            ),
        )

    def get_tenant_quota(self, tenant_id: Union[str, UUID]) -> TenantQuota:
        return cast(TenantQuota, self._client.request(
            "platform.get_tenant_quota", path_params={"tenant_id": tenant_id}, cast_to=TenantQuota,
        ))

    def get_tenant_usage(self, tenant_id: Union[str, UUID]) -> UsageSummary:
        return cast(UsageSummary, self._client.request(
            "platform.get_tenant_usage", path_params={"tenant_id": tenant_id}, cast_to=UsageSummary,
        ))

    def issue_recovery(self, tenant_id: Union[str, UUID], *, email: str) -> Dict[str, str]:
        return cast(Dict[str, str], self._client.request(
            "platform.issue_recovery", path_params={"tenant_id": tenant_id},
            json={"email": email}, cast_to=Dict[str, str],
        ))

    def assign_tenant_plan(self, tenant_id: Union[str, UUID], plan_id: Union[str, UUID]) -> TenantQuota:
        return cast(TenantQuota, self._client.request(
            "platform.assign_tenant_plan", path_params={"tenant_id": tenant_id},
            json={"plan_id": str(plan_id)}, cast_to=TenantQuota,
        ))

    def set_tenant_status(self, tenant_id: Union[str, UUID], status: StatusLike) -> PlatformTenant:
        """Change a tenant's lifecycle status (see :class:`~graphrec_sdk.TenantStatus`).

        ``POST /v1/platform/tenants/{tenant_id}/status``. The change is audited.
        """

        return cast(
            PlatformTenant,
            self._client.request(
                "platform.set_tenant_status",
                path_params={"tenant_id": tenant_id},
                json=_status_body(status),
                cast_to=PlatformTenant,
            ),
        )

    def list_plans(self) -> PricingPlanList:
        """``GET /v1/platform/plans``."""

        items = self._client.request("platform.list_plans", cast_to=List[PricingPlan])
        return PricingPlanList(items=items)

    def update_plan(self, plan_id: Union[str, UUID], *, name: str, limits: Mapping[str, int], is_active: bool) -> PricingPlan:
        return cast(PricingPlan, self._client.request(
            "platform.update_plan", path_params={"plan_id": plan_id},
            json=_plan_body(name, limits, is_active), cast_to=PricingPlan,
        ))

    def set_quota_override(
        self, tenant_id: Union[str, UUID], *, overrides: Mapping[str, Any]
    ) -> QuotaOverride:
        """Replace a tenant's quota overrides; returns plan limits and the stored overrides.

        ``POST /v1/platform/tenants/{tenant_id}/quotas``, e.g.
        ``overrides={"accepted_events": 1_000_000}``. The change is audited.
        """

        return cast(
            QuotaOverride,
            self._client.request(
                "platform.set_quota_override",
                path_params={"tenant_id": tenant_id},
                json=_quota_body(overrides),
                cast_to=QuotaOverride,
            ),
        )

    def list_failures(self) -> PlatformFailureList:
        """Latest security/failure events (``GET /v1/platform/failures``)."""

        return cast(
            PlatformFailureList,
            self._client.request("platform.list_failures", cast_to=PlatformFailureList),
        )

    def list_audit_logs(self) -> AuditRecordList:
        """Latest audit records across tenants (``GET /v1/platform/audit``)."""

        return cast(
            AuditRecordList,
            self._client.request("platform.list_audit_logs", cast_to=AuditRecordList),
        )

    def status(self) -> Dict[str, Any]:
        """Shared service health (``GET /v1/platform/status``)."""

        return cast(Dict[str, Any], self._client.request("platform.status", cast_to=Dict[str, Any]))


class AsyncPlatform(AsyncResource):
    async def list_tenants(self) -> PlatformTenantList:
        """Async variant of :meth:`Platform.list_tenants`."""

        return cast(
            PlatformTenantList,
            await self._client.request("platform.list_tenants", cast_to=PlatformTenantList),
        )

    async def get_tenant(self, tenant_id: Union[str, UUID]) -> PlatformTenant:
        """Async variant of :meth:`Platform.get_tenant`."""

        return cast(
            PlatformTenant,
            await self._client.request(
                "platform.get_tenant", path_params={"tenant_id": tenant_id}, cast_to=PlatformTenant
            ),
        )

    async def get_tenant_quota(self, tenant_id: Union[str, UUID]) -> TenantQuota:
        return cast(TenantQuota, await self._client.request(
            "platform.get_tenant_quota", path_params={"tenant_id": tenant_id}, cast_to=TenantQuota,
        ))

    async def get_tenant_usage(self, tenant_id: Union[str, UUID]) -> UsageSummary:
        return cast(UsageSummary, await self._client.request(
            "platform.get_tenant_usage", path_params={"tenant_id": tenant_id}, cast_to=UsageSummary,
        ))

    async def issue_recovery(self, tenant_id: Union[str, UUID], *, email: str) -> Dict[str, str]:
        return cast(Dict[str, str], await self._client.request(
            "platform.issue_recovery", path_params={"tenant_id": tenant_id},
            json={"email": email}, cast_to=Dict[str, str],
        ))

    async def assign_tenant_plan(self, tenant_id: Union[str, UUID], plan_id: Union[str, UUID]) -> TenantQuota:
        return cast(TenantQuota, await self._client.request(
            "platform.assign_tenant_plan", path_params={"tenant_id": tenant_id},
            json={"plan_id": str(plan_id)}, cast_to=TenantQuota,
        ))

    async def set_tenant_status(
        self, tenant_id: Union[str, UUID], status: StatusLike
    ) -> PlatformTenant:
        """Async variant of :meth:`Platform.set_tenant_status`."""

        return cast(
            PlatformTenant,
            await self._client.request(
                "platform.set_tenant_status",
                path_params={"tenant_id": tenant_id},
                json=_status_body(status),
                cast_to=PlatformTenant,
            ),
        )

    async def list_plans(self) -> PricingPlanList:
        """Async variant of :meth:`Platform.list_plans`."""

        items = await self._client.request("platform.list_plans", cast_to=List[PricingPlan])
        return PricingPlanList(items=items)

    async def update_plan(self, plan_id: Union[str, UUID], *, name: str, limits: Mapping[str, int], is_active: bool) -> PricingPlan:
        return cast(PricingPlan, await self._client.request(
            "platform.update_plan", path_params={"plan_id": plan_id},
            json=_plan_body(name, limits, is_active), cast_to=PricingPlan,
        ))

    async def set_quota_override(
        self, tenant_id: Union[str, UUID], *, overrides: Mapping[str, Any]
    ) -> QuotaOverride:
        """Async variant of :meth:`Platform.set_quota_override`."""

        return cast(
            QuotaOverride,
            await self._client.request(
                "platform.set_quota_override",
                path_params={"tenant_id": tenant_id},
                json=_quota_body(overrides),
                cast_to=QuotaOverride,
            ),
        )

    async def list_failures(self) -> PlatformFailureList:
        """Async variant of :meth:`Platform.list_failures`."""

        return cast(
            PlatformFailureList,
            await self._client.request("platform.list_failures", cast_to=PlatformFailureList),
        )

    async def list_audit_logs(self) -> AuditRecordList:
        """Async variant of :meth:`Platform.list_audit_logs`."""

        return cast(
            AuditRecordList,
            await self._client.request("platform.list_audit_logs", cast_to=AuditRecordList),
        )

    async def status(self) -> Dict[str, Any]:
        """Async variant of :meth:`Platform.status`."""

        return cast(
            Dict[str, Any], await self._client.request("platform.status", cast_to=Dict[str, Any])
        )
