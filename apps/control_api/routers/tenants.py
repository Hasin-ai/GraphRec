"""The caller's own tenant. There is no route to anyone else's.

`GET /v1/tenant` is singular and takes no identifier. That is deliberate: a
`/v1/tenants/{tenant_id}` shape invites a handler to trust the path segment, and
the fix for that mistake is to not offer the shape.

It is also the one tenant-realm read that is exempt from gate 2, because
`/account/tenant-status` — the page gate 2 sends people to — has to read the
status from somewhere. See `current_tenant_principal_any_state` for the shape of
the exemption and its limits.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.control_api.deps import TenantPrincipal, current_tenant_principal_any_state
from apps.control_api.schemas import TenantResponse

router = APIRouter(tags=["tenant"])

AnyState = Annotated[TenantPrincipal, Depends(current_tenant_principal_any_state)]


@router.get("/tenant", response_model=TenantResponse, summary="The caller's own tenant")
async def get_tenant(principal: AnyState) -> TenantResponse:
    """Readable by a suspended tenant's own members, and by nobody else.

    `status` and `status_reason` are the two fields the gate-2 page renders: what
    the lifecycle position is, and what the platform said about it. Neither
    discloses anything a member of this tenant is not entitled to know, and the
    row is still read under this tenant's own RLS policy.
    """
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
