"""Where each usage type's number comes from — and what to say when nowhere.

Six usage types, three shapes, and the shape decides both the arithmetic and the
reset text the console renders.

* **Accumulated** — `events`, `recommendations`, `training`. A running total for
  the period, summed from the ledger and mirrored in a fast counter. Resets:
  "monthly · resets 2026-09-01" (dc.html L710).
* **Standing** — `products`, `storage`. A level, not an allowance. Counted as it
  stands right now; nothing resets, so the console says "no reset · standing
  limit" (L713).
* **Sampled** — `service_capacity`. Read from the serving layer as it is,
  continuously (L715).

The important part is the fourth case: a type whose source **does not exist
yet**. `storage` is measured from object storage and `service_capacity` from the
serving reconciler, neither of which is built before Phase 11. This module
answers for them with `MeasurementStatus.DELAYED` and a quantity of `None`.

That is the whole of BUILD_PROMPT's step-7 exit criterion, and it is
deliberately structural rather than a special case in the view. A usage type is
`measured` because a function in `MEASUREMENT_SOURCES` returned a number, and
`delayed` because there was no function to call. When Phase 11 registers a
storage prober, the row becomes measured with no change to `service.py` — and
until it does, no amount of view code can accidentally render a zero, because
there is no zero anywhere to render. NR-F-15 asks for usage "where calculable";
this table is the definition of "where".
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import sqlalchemy as sa

from graphrec.common.enums import MeasurementStatus, UsageType
from graphrec.db.models.catalog import Product
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering import ledger
from graphrec.domain.metering.periods import CONTINUOUS_RESET, STANDING_RESET

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.domain.metering.counters import UsageCounters
    from graphrec.domain.metering.periods import Period

#: Totals that accumulate over a period and are enforced against a monthly
#: allowance. These are the types `ledger.grant` is called for.
ACCUMULATED_TYPES: frozenset[UsageType] = frozenset(
    {UsageType.EVENTS, UsageType.RECOMMENDATIONS, UsageType.TRAINING}
)

#: Levels. Counted where they live, not accumulated in the ledger.
STANDING_TYPES: frozenset[UsageType] = frozenset({UsageType.PRODUCTS, UsageType.STORAGE})


@dataclass(frozen=True, slots=True)
class Measurement:
    """A quantity, or an honest account of why there isn't one.

    The constructor enforces the invariant the database also enforces: a
    `measured` status has a quantity and no other status does. Constructing an
    impossible pair fails here rather than at flush time.
    """

    quantity: decimal.Decimal | None
    status: MeasurementStatus

    def __post_init__(self) -> None:
        measured = self.status is MeasurementStatus.MEASURED
        if measured is not (self.quantity is not None):
            raise ValueError(
                f"a {self.status.value} measurement cannot carry quantity {self.quantity!r}"
            )

    @classmethod
    def of(cls, quantity: decimal.Decimal | int) -> Measurement:
        return cls(decimal.Decimal(quantity), MeasurementStatus.MEASURED)

    @classmethod
    def delayed(cls) -> Measurement:
        return cls(None, MeasurementStatus.DELAYED)

    @classmethod
    def unavailable(cls) -> Measurement:
        return cls(None, MeasurementStatus.UNAVAILABLE)


class MeasurementSource(Protocol):
    """One usage type's number, for one tenant, for one period."""

    async def __call__(
        self,
        session: AsyncSession,
        counters: UsageCounters,
        *,
        tenant_id: uuid.UUID,
        period: Period,
        live: bool,
    ) -> Measurement: ...


def reset_label(usage_type: UsageType, *, period: Period) -> str:
    """The "Reset period" column (L1818)."""
    if usage_type in ACCUMULATED_TYPES:
        return period.reset_label
    if usage_type in STANDING_TYPES:
        return STANDING_RESET
    return CONTINUOUS_RESET


def _accumulated(usage_type: UsageType) -> MeasurementSource:
    async def source(
        session: AsyncSession,
        counters: UsageCounters,
        *,
        tenant_id: uuid.UUID,
        period: Period,
        live: bool,
    ) -> Measurement:
        if live:
            # The counter, repaired from the ledger on a miss.
            total = await counter_ops.current(
                session, counters, tenant_id=tenant_id, usage_type=usage_type, period=period
            )
        else:
            # A closed period is read from the ledger directly. Its counter has
            # expired by design and reviving it would warm a key nothing else
            # will ever read.
            total = await ledger.measured(session, usage_type=usage_type, period=period)
        return Measurement.of(total)

    return source


async def _products(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    period: Period,
    live: bool,
) -> Measurement:
    """The catalogue as it stands. Disabled products still count against the
    limit — `deleted_at` is the only thing that removes one — which is why the
    quota message tells a tenant to disable what they no longer sell *and* the
    count is taken the same way here as in `catalog.service` (L1603)."""
    count = await session.scalar(
        sa.select(sa.func.count()).select_from(Product).where(Product.deleted_at.is_(None))
    )
    return Measurement.of(int(count or 0))


#: The registry. A usage type absent from this mapping has no way to be
#: measured and is reported as delayed — see the module docstring.
MEASUREMENT_SOURCES: dict[UsageType, MeasurementSource] = {
    UsageType.EVENTS: _accumulated(UsageType.EVENTS),
    UsageType.RECOMMENDATIONS: _accumulated(UsageType.RECOMMENDATIONS),
    UsageType.TRAINING: _accumulated(UsageType.TRAINING),
    UsageType.PRODUCTS: _products,
    # UsageType.STORAGE — object storage, Phase 11.
    # UsageType.SERVICE_CAPACITY — the serving reconciler, Phase 11 (L1824).
}


async def measure(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    period: Period,
    live: bool,
) -> Measurement:
    source = MEASUREMENT_SOURCES.get(usage_type)
    if source is None:
        return Measurement.delayed()
    return await source(session, counters, tenant_id=tenant_id, period=period, live=live)


__all__ = [
    "ACCUMULATED_TYPES",
    "MEASUREMENT_SOURCES",
    "STANDING_TYPES",
    "Measurement",
    "MeasurementSource",
    "measure",
    "reset_label",
]
