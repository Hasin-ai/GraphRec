"""The tenant's own history. One read, administrator-only, redacted.

`[Admin]` in the prototype's route table (dc.html L1420, FRONTEND_BUILD_PROMPT
L212: "Tenant Administrator only"), which is the same line the usage and
service-status pages sit on: a developer integrates, an administrator accounts.

Everything this route must never do is enforced somewhere other than here, and
that is the point of how little code is in this file:

* **Another tenant's rows** are excluded by RLS on the bound session, not by a
  `WHERE` clause a refactor could drop.
* **Platform actions** are excluded by the same policy: they carry no
  `tenant_id`, and `NULL = <tenant>` is not true.
* **Secrets, payloads and actor identities** are excluded by the projection in
  `graphrec.domain.audit.query`, which returns five columns and has no way to
  return a sixth.

So the handler filters, paginates and serialises. If it grows a condition about
who may see what, that condition is in the wrong file.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from apps.control_api.deps import RequireAdministrator
from apps.control_api.schemas import AuditLogListResponse, AuditLogRow
from graphrec.common.enums import AuditAction
from graphrec.domain import audit

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=AuditLogListResponse, summary="A tenant's own history")
async def list_audit_logs(
    principal: RequireAdministrator,
    action: AuditAction | None = None,
    occurred_after: dt.datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogListResponse:
    """The two filters L1204 names, and the two it deliberately does not.

    `action` and `occurred_after` are offered. A filter on `resource_ref` is
    not: it would let a caller ask "does this identifier exist" and read the
    answer off the row count, which is the same oracle gate 4's 404 exists to
    close.

    `total` accompanies the page because D10 fixes limit/offset *with a total*
    for console lists — the table renders "20 of 143", and a cursor cannot
    produce the second number.
    """
    page = await audit.tenant_page(
        principal.session,
        action=action,
        occurred_after=occurred_after,
        limit=limit,
        offset=offset,
    )
    return AuditLogListResponse(
        entries=[
            AuditLogRow(
                occurred_at=row.occurred_at,
                actor_type=row.actor_type,
                action=row.action,
                resource_type=row.resource_type,
                resource_ref=row.resource_ref,
                outcome=row.outcome,
            )
            for row in page.rows
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


__all__ = ["router"]
