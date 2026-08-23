"""Reading the history, twice, for two audiences.

The tenant projection and the platform projection are separate functions rather
than one function with a flag. A flag would put the redaction rule one boolean
away from being wrong, and the rule here is not a preference: SRS §5.2.16 makes
the tenant-facing view *specifically* the one that must never carry another
tenant's data or any hint that another tenant exists.

Three things keep that true, and they are independent so no single mistake
defeats all three:

1. **The connection.** The tenant read runs on a session bound to the tenant, so
   RLS filters every foreign row and every unattributed platform row before this
   code sees them. There is no `WHERE tenant_id = …` here, deliberately: writing
   one would suggest the filter is this module's job and invite someone to
   "optimise" it away later.
2. **The projection.** `AuditRow` has five fields, the five columns L1288 lists.
   `actor_id`, `details` and `tenant_id` are not among them. A platform user's
   identity is not a tenant's business, and `details` is the free-form column.
3. **The ordering and bounds.** Newest first, limit capped. An unbounded audit
   read is how one slow query becomes an outage on the one table nobody prunes.

Counts are returned with the page because D10 fixes limit/offset *with a total*
for console lists, and the audit table renders "20 of 143".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.db.models.audit import AuditLog, SecurityEvent

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.common.enums import AuditAction, Severity

#: The console's page size, and the ceiling a caller cannot argue past.
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class AuditRow:
    """What a tenant is shown: L1288's five columns and nothing else."""

    occurred_at: dt.datetime
    actor_type: str
    action: str
    resource_type: str
    resource_ref: str | None
    outcome: str


@dataclass(frozen=True, slots=True)
class PlatformAuditRow:
    """What an operator is shown: the same, plus who and which tenant.

    `details` is still absent. The Failures and Audit tabs are read by people
    with an `audit permission`, not by people with a licence to read whatever a
    handler once put in a jsonb column — and nothing in the console renders it
    (FRONTEND_BUILD_PROMPT L311 lists six columns, none of them details).
    """

    occurred_at: dt.datetime
    tenant_id: uuid.UUID | None
    actor_type: str
    actor_id: str | None
    action: str
    resource_type: str
    resource_ref: str | None
    outcome: str
    correlation_ref: str | None


@dataclass(frozen=True, slots=True)
class AuditPage:
    rows: list[Any]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class FailureRow:
    """One terminal failure, as the Failures tab renders it.

    `tenant_id` is `None` unless the caller opened the tab *from* a tenant
    context (L1550). It is not that the platform role cannot read the column —
    it can — but that the default view is redacted, and defaulting to redacted
    is the only version of this rule that survives a hurried change.
    """

    occurred_at: dt.datetime
    severity: str
    area: str
    summary: str
    reference: str
    tenant_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class FailurePage:
    rows: list[FailureRow]
    total: int
    limit: int
    offset: int


async def tenant_page(
    session: AsyncSession,
    *,
    action: AuditAction | None = None,
    occurred_after: dt.datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AuditPage:
    """The tenant's own history, on a bound session.

    Note the absence of a `tenant_id` parameter. There is nothing to pass: the
    session carries the context, RLS applies the filter, and a caller who wanted
    someone else's history would have to hold someone else's connection.
    """
    limit = min(max(limit, 1), MAX_LIMIT)
    conditions = _conditions(action=action, occurred_after=occurred_after)

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(AuditLog).where(*conditions)
    )
    result = await session.execute(
        sa.select(
            AuditLog.occurred_at,
            AuditLog.actor_type,
            AuditLog.action,
            AuditLog.resource_type,
            AuditLog.resource_ref,
            AuditLog.outcome,
        )
        .where(*conditions)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.audit_log_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return AuditPage(
        rows=[AuditRow(*row) for row in result.all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


async def platform_page(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    occurred_after: dt.datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AuditPage:
    """Every tenant's history, on the platform connection.

    Here `tenant_id` *is* a parameter, and it is a filter rather than a scope —
    the distinction §12.10 opens with. Passing none means "all tenants",
    including the unattributed rows a tenant can never see.
    """
    limit = min(max(limit, 1), MAX_LIMIT)
    conditions = _conditions(action=action, occurred_after=occurred_after)
    if tenant_id is not None:
        conditions.append(AuditLog.tenant_id == tenant_id)

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(AuditLog).where(*conditions)
    )
    result = await session.execute(
        sa.select(
            AuditLog.occurred_at,
            AuditLog.tenant_id,
            AuditLog.actor_type,
            AuditLog.actor_id,
            AuditLog.action,
            AuditLog.resource_type,
            AuditLog.resource_ref,
            AuditLog.outcome,
            AuditLog.correlation_ref,
        )
        .where(*conditions)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.audit_log_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return AuditPage(
        rows=[PlatformAuditRow(*row) for row in result.all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


async def failures(
    session: AsyncSession,
    *,
    severity: Severity | None = None,
    occurred_after: dt.datetime | None = None,
    tenant_id: uuid.UUID | None = None,
    reveal_tenant: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> FailurePage:
    """The Failures tab: what failed, how badly, and where.

    `reveal_tenant` defaults to `False` and is set only when the caller arrived
    from a tenant context — which, in practice, means they passed `tenant_id`
    and therefore already know which tenant they are looking at. Telling them
    again costs nothing; volunteering it on the unfiltered list would turn a
    severity ranking into a public league table of which tenants are struggling.
    """
    limit = min(max(limit, 1), MAX_LIMIT)
    conditions: list[Any] = []
    if severity is not None:
        conditions.append(SecurityEvent.severity == severity.value)
    if occurred_after is not None:
        conditions.append(SecurityEvent.occurred_at >= occurred_after)
    if tenant_id is not None:
        conditions.append(SecurityEvent.tenant_id == tenant_id)

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(SecurityEvent).where(*conditions)
    )
    result = await session.execute(
        sa.select(
            SecurityEvent.occurred_at,
            SecurityEvent.severity,
            SecurityEvent.area,
            SecurityEvent.summary,
            SecurityEvent.reference,
            SecurityEvent.tenant_id,
        )
        .where(*conditions)
        .order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.security_event_id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = [
        FailureRow(
            occurred_at=row.occurred_at,
            severity=row.severity,
            area=row.area,
            summary=row.summary,
            reference=row.reference,
            tenant_id=row.tenant_id if reveal_tenant else None,
        )
        for row in result.all()
    ]
    return FailurePage(rows=rows, total=int(total or 0), limit=limit, offset=offset)


def _conditions(*, action: AuditAction | None, occurred_after: dt.datetime | None) -> list[Any]:
    """The two filters the console offers, and no others (L1204).

    A `resource_ref` filter would be the obvious third, and it is absent on
    purpose: it invites a caller to probe for the existence of an identifier by
    watching whether the count changes.
    """
    conditions: list[Any] = []
    if action is not None:
        conditions.append(AuditLog.action == action.value)
    if occurred_after is not None:
        conditions.append(AuditLog.occurred_at >= occurred_after)
    return conditions


__all__ = [
    "MAX_LIMIT",
    "AuditPage",
    "AuditRow",
    "FailurePage",
    "FailureRow",
    "PlatformAuditRow",
    "failures",
    "platform_page",
    "tenant_page",
]
