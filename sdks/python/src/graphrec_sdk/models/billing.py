from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import Field

from ._base import GraphRecModel

__all__ = ["Subscription", "UsageDimension", "UsageSummary", "UsageTrend", "UsageTrendBucket"]


class Subscription(GraphRecModel):
    #: ``free``, ``basic`` or ``pro``.
    plan_code: str
    status: str
    period_start: datetime
    period_end: datetime
    #: Effective limits after tenant overrides, e.g. ``{"accepted_events": 50000}``.
    limits: Dict[str, int]
    project_defaults: bool


class UsageDimension(GraphRecModel):
    #: One of :class:`graphrec_sdk.UsageType`.
    type: str
    used: Union[int, float]
    #: ``None`` for informational dimensions without a limit.
    limit: Optional[int] = None
    remaining: Optional[Union[int, float]] = None
    #: ``count``, ``seconds``, ``bytes`` or ``minutes``.
    unit: str
    #: ``False`` when GraphRec does not measure this dimension yet; ``used`` is then not a measurement.
    measured: bool = True
    #: ``period`` (ledger sum over the period) or ``current`` (point-in-time inventory).
    scope: str = "period"

    @property
    def utilization(self) -> Optional[float]:
        """Fraction of the limit consumed (0.0-1.0+), or ``None`` without a limit."""

        if not self.limit:
            return None
        return float(self.used) / float(self.limit)

    @property
    def is_exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


class UsageSummary(GraphRecModel):
    period_start: datetime
    period_end: datetime
    reset_at: datetime
    dimensions: List[UsageDimension]
    last_reconciled_at: datetime
    project_defaults: bool
    #: False for a past period requested with ``period="YYYY-MM"``.
    current_period: bool = True

    def get(self, usage_type: str) -> Optional[UsageDimension]:
        """Look up one dimension, e.g. ``summary.get("accepted_events")``."""

        key = getattr(usage_type, "value", usage_type)
        return next((item for item in self.dimensions if item.type == key), None)


class UsageTrendBucket(GraphRecModel):
    """Usage in one period, keyed by usage type."""

    start: datetime
    values: Dict[str, Union[int, float]] = Field(default_factory=dict)


class UsageTrend(GraphRecModel):
    """Usage summarized by period and usage type (``GET /v1/usage/trends``)."""

    tenant_id: str
    start: datetime
    end: datetime
    #: ``hour``, ``day`` or ``week``.
    granularity: str
    usage_types: List[str] = Field(default_factory=list)
    buckets: List[UsageTrendBucket] = Field(default_factory=list)
    totals: Dict[str, Union[int, float]] = Field(default_factory=dict)
