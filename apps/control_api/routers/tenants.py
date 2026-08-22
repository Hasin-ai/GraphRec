"""The caller's own tenant. There is no route to anyone else's.

`GET /v1/tenant` is singular and takes no identifier. That is deliberate: a
`/v1/tenants/{tenant_id}` shape invites a handler to trust the path segment, and
the fix for that mistake is to not offer the shape.
"""

from __future__ import annotations

from fastapi import APIRouter

from apps.control_api.deps import CurrentTenant
from apps.control_api.schemas import TenantResponse

router = APIRouter(tags=["tenant"])


@router.get("/tenant", response_model=TenantResponse, summary="The caller's own tenant")
async def get_tenant(principal: CurrentTenant) -> TenantResponse:
    tenant = principal.tenant
    return TenantResponse(
        tenant_id=tenant.tenant_id,
        tenant_code=tenant.tenant_code,
        tenant_name=tenant.tenant_name,
        status=tenant.status,
        plan_code=tenant.plan.plan_code if tenant.plan else None,
        created_at=tenant.created_at,
        status_reason=tenant.status_reason,
    )
