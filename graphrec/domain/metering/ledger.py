"""Writing to the ledger, and reading it back.

Two functions and a rule. The rule is that `grant` runs **inside the caller's
transaction** — the one already creating the submission, the job or the
recommendation being metered (BUILD_PROMPT 7.5). It does not open its own
session and it does not commit. If the work rolls back, so does the charge; if
the work commits, the charge committed with it. There is no window in which a
tenant is billed for something that did not happen, because there is no second
transaction in which that window could open.

`grant` is idempotent on `(tenant_id, idempotency_key)`. The caller supplies a
key derived from the thing being metered — a submission id, a job id — so that a
retried transaction re-attempts the same grant and the second attempt is a
no-op. `ON CONFLICT DO NOTHING` makes that a normal outcome rather than an
error, and the boolean return says which happened, because the Redis counter
must only be incremented for a grant that was actually written.

`measured` reads the ledger back. It is the slow, correct answer, and everything
in `counters.py` exists to avoid calling it on a hot path — never to replace it.
"""

from __future__ import annotations

import decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.common.enums import UsageType
    from graphrec.domain.metering.periods import Period


async def grant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    quantity: decimal.Decimal | int,
    idempotency_key: str,
    occurred_at: dt.datetime,
    source_ref: str | None = None,
) -> bool:
    """Record usage. Returns `True` if this call wrote the row.

    `False` means an identical grant was already recorded — a retry, not a
    failure. Callers use the return value to decide whether to move the fast
    counter, never to decide whether to fail.
    """
    if quantity < 0:
        # The check constraint would catch this, but as an integrity error at
        # flush time, attributed to whatever statement happened to flush. A
        # negative quantity is a caller bug and deserves to name itself.
        raise ValueError(f"usage quantity must be non-negative, got {quantity!r}")

    result = await session.execute(
        sa.text(
            "INSERT INTO usage_events "
            "  (tenant_id, usage_type, quantity, source_ref, idempotency_key, occurred_at) "
            "VALUES (:tenant_id, :usage_type, :quantity, :source_ref, :key, :occurred_at) "
            "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING "
            "RETURNING usage_event_id"
        ),
        {
            "tenant_id": tenant_id,
            "usage_type": usage_type.value,
            "quantity": decimal.Decimal(quantity),
            "source_ref": source_ref,
            "key": idempotency_key,
            "occurred_at": occurred_at,
        },
    )
    return result.scalar_one_or_none() is not None


async def measured(
    session: AsyncSession, *, usage_type: UsageType, period: Period
) -> decimal.Decimal:
    """The ledger's total for one type in one period.

    `COALESCE` to zero is safe *here* and only here: this is the sum of rows we
    hold, and a tenant with no rows genuinely used nothing. The zero that the
    plan forbids is a different one — substituting zero for a measurement we
    could not take. That decision is made in `service.py`, by whether a
    measurement source exists at all, not by this query.
    """
    start, end = period.bounds()
    total = await session.scalar(
        sa.text(
            "SELECT COALESCE(SUM(quantity), 0) FROM usage_events "
            "WHERE usage_type = :usage_type "
            "  AND occurred_at >= :start AND occurred_at < :end"
        ),
        {"usage_type": usage_type.value, "start": start, "end": end},
    )
    return decimal.Decimal(total or 0)


__all__ = ["grant", "measured"]
