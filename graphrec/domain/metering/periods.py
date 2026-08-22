"""Monthly periods, and the labels the console renders for them.

A billing-adjacent period is a closed question with an easy wrong answer. The
prototype writes "monthly · resets 2026-09-01" (dc.html L710), which fixes three
things at once: a period runs **month to month**, its end is the *next* period's
start rather than the last instant of this one, and the reset date shown to a
tenant is that end.

Half-open `[start, end)` is used throughout. A usage event at exactly
`2026-09-01T00:00:00Z` belongs to September, not to August, and the ledger sum
uses `>= start AND < end` so no event is counted twice or missed at a boundary.

Everything here is UTC. A tenant in Auckland and a tenant in Lisbon reset at the
same instant, because the alternative is a period boundary that depends on a
column nobody has set correctly and a monthly total that changes when a tenant
edits their profile.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: `no reset · standing limit` — the reset text for a limit that is a level
#: rather than an allowance (dc.html L713-714). Products and storage are counted
#: as they stand, so nothing about them "resets".
STANDING_RESET = "no reset · standing limit"

#: `continuous` — service capacity is sampled, not accumulated (L715).
CONTINUOUS_RESET = "continuous"


@dataclass(frozen=True, slots=True)
class Period:
    """One monthly window, half-open: `start <= occurred_at < end`."""

    start: dt.date
    end: dt.date

    @property
    def label(self) -> str:
        """`2026-08` — the trend panel's period column (L1818)."""
        return f"{self.start.year:04d}-{self.start.month:02d}"

    @property
    def reset_label(self) -> str:
        """`monthly · resets 2026-09-01` — L710."""
        return f"monthly · resets {self.end.isoformat()}"

    def contains(self, moment: dt.datetime) -> bool:
        as_date = moment.astimezone(dt.UTC).date()
        return self.start <= as_date < self.end

    def bounds(self) -> tuple[dt.datetime, dt.datetime]:
        """The window as instants, for a ledger query."""
        return (
            dt.datetime.combine(self.start, dt.time.min, tzinfo=dt.UTC),
            dt.datetime.combine(self.end, dt.time.min, tzinfo=dt.UTC),
        )


def current_period(now: dt.datetime) -> Period:
    start = now.astimezone(dt.UTC).date().replace(day=1)
    return Period(start=start, end=_next_month(start))


def period_containing(moment: dt.datetime) -> Period:
    return current_period(moment)


def recent_periods(now: dt.datetime, *, count: int) -> list[Period]:
    """The current period first, then `count - 1` before it.

    The trend panel shows three (L1818). Ordering is newest-first because that
    is the order the panel renders and the order a tenant reads.
    """
    period = current_period(now)
    periods = [period]
    for _ in range(max(count - 1, 0)):
        period = Period(start=_previous_month(period.start), end=period.start)
        periods.append(period)
    return periods


def trend_label(period: Period, *, current: Period) -> str:
    """`2026-08 (current)` for the live period, `2026-07` for a closed one."""
    return f"{period.label} (current)" if period == current else period.label


def _next_month(day: dt.date) -> dt.date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return dt.date(year, month, 1)


def _previous_month(day: dt.date) -> dt.date:
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return dt.date(year, month, 1)


__all__ = [
    "CONTINUOUS_RESET",
    "STANDING_RESET",
    "Period",
    "current_period",
    "period_containing",
    "recent_periods",
    "trend_label",
]
