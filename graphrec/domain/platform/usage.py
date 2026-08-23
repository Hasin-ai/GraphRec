"""Cross-tenant usage: aggregate quantities, and nothing under them.

One table is read here — `monthly_usage_aggregates` — and that is the whole
privacy argument. The ledger beneath it, `usage_events`, carries a row per
submitted batch with a source reference that names the tenant's own work, and
`interaction_events` beneath *that* is their customers' behaviour. Neither is
granted to `graphrec_platform`, so "private event payloads are excluded from
every platform view" (L1438, UC-29) is enforced by an absent privilege rather
than by this module remembering not to ask.

The second rule this module holds is the one that keeps the aggregate honest: a
period that has not been rolled up has `quantity IS NULL` and
`measurement_status = 'delayed'`, and both travel to the console. A row that
reported `0` for an unmeasured period would be a claim that the tenant did
nothing, which is a different statement from "we have not counted yet" and the
one an operator would act on.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.enums import MeasurementStatus, UsageType
from graphrec.common.errors import NotFoundError, ValidationError
from graphrec.db.models import MonthlyUsageAggregate, Tenant
from graphrec.domain.metering.periods import current_period

if TYPE_CHECKING:
    import decimal
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class PlatformUsageRow:
    """One tenant, one period, one usage type.

    `tenant_code` travels with `tenant_id` because the operator reading
    `/admin/usage` knows tenants by their code, and a table of uuids would send
    them back to `/admin/tenants` for every row.
    """

    tenant_id: uuid.UUID
    tenant_code: str
    period: str
    usage_type: str
    quantity: decimal.Decimal | None
    measurement_status: str


async def cross_tenant_usage(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    usage_type: UsageType | None = None,
    period: str | None = None,
    now: dt.datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[PlatformUsageRow], int]:
    """`GET /v1/platform/usage`, filtered three ways.

    A named tenant that does not exist is a 404, not an empty page (L1524). The
    distinction matters because an empty page reads as "that tenant used
    nothing", and an operator investigating a billing dispute would take it as
    an answer rather than as a typo in the identifier they pasted.
    """
    limit = min(max(limit, 1), MAX_LIMIT)
    moment = now or dt.datetime.now(dt.UTC)

    conditions: list[Any] = []
    if tenant_id is not None:
        if (
            await session.scalar(sa.select(Tenant.tenant_id).where(Tenant.tenant_id == tenant_id))
            is None
        ):
            raise NotFoundError()
        conditions.append(MonthlyUsageAggregate.tenant_id == tenant_id)
    if usage_type is not None:
        conditions.append(MonthlyUsageAggregate.usage_type == usage_type.value)
    conditions.append(MonthlyUsageAggregate.period_start == _period_start(period, now=moment))

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(MonthlyUsageAggregate).where(*conditions)
    )
    result = await session.execute(
        sa.select(
            MonthlyUsageAggregate.tenant_id,
            Tenant.tenant_code,
            MonthlyUsageAggregate.period_start,
            MonthlyUsageAggregate.usage_type,
            MonthlyUsageAggregate.quantity,
            MonthlyUsageAggregate.measurement_status,
        )
        .join(Tenant, Tenant.tenant_id == MonthlyUsageAggregate.tenant_id)
        .where(*conditions)
        .order_by(Tenant.tenant_code, MonthlyUsageAggregate.usage_type)
        .limit(limit)
        .offset(offset)
    )
    return [_row(record) for record in result.all()], int(total or 0)


async def tenant_usage(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> list[PlatformUsageRow]:
    """The usage section of the composed tenant detail.

    Every usage type appears, whether or not an aggregate row exists for it. A
    type with no row is reported `unavailable` rather than omitted: a table that
    silently dropped `storage` would leave the operator to decide whether the
    tenant stores nothing or whether the rollup is behind, and those need
    different actions.
    """
    moment = now or dt.datetime.now(dt.UTC)
    period = current_period(moment)
    tenant_code = await session.scalar(
        sa.select(Tenant.tenant_code).where(Tenant.tenant_id == tenant_id)
    )
    if tenant_code is None:
        raise NotFoundError()

    result = await session.execute(
        sa.select(
            MonthlyUsageAggregate.usage_type,
            MonthlyUsageAggregate.quantity,
            MonthlyUsageAggregate.measurement_status,
        ).where(
            MonthlyUsageAggregate.tenant_id == tenant_id,
            MonthlyUsageAggregate.period_start == period.start,
        )
    )
    stored = {row.usage_type: row for row in result.all()}
    rows: list[PlatformUsageRow] = []
    for usage_type in UsageType:
        record = stored.get(usage_type.value)
        rows.append(
            PlatformUsageRow(
                tenant_id=tenant_id,
                tenant_code=tenant_code,
                period=period.label,
                usage_type=usage_type.value,
                quantity=record.quantity if record is not None else None,
                measurement_status=(
                    record.measurement_status
                    if record is not None
                    else MeasurementStatus.UNAVAILABLE.value
                ),
            )
        )
    return rows


def _row(record: Any) -> PlatformUsageRow:
    return PlatformUsageRow(
        tenant_id=record.tenant_id,
        tenant_code=record.tenant_code,
        period=f"{record.period_start.year:04d}-{record.period_start.month:02d}",
        usage_type=record.usage_type,
        quantity=record.quantity,
        measurement_status=record.measurement_status,
    )


def _period_start(period: str | None, *, now: dt.datetime) -> dt.date:
    """`2026-08` to the first of that month. Defaults to the open period.

    Parsed here rather than by a Pydantic type because the wire form is the
    console's own label (`Period.label`), and giving the parser and the label
    the same home is what keeps a filter that round-trips a value from one
    response into the next request working.
    """
    if period is None:
        return current_period(now).start
    try:
        year, month = period.split("-", 1)
        return dt.date(int(year), int(month), 1)
    except (ValueError, TypeError) as exc:
        raise ValidationError("invalid_request").with_field(
            "period", "Correct the highlighted field and submit again."
        ) from exc


__all__ = ["MAX_LIMIT", "PlatformUsageRow", "cross_tenant_usage", "tenant_usage"]
