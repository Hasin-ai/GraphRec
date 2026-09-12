from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Union

from ._base import GraphRecModel

__all__ = ["Subscription", "UsageDimension", "UsageSummary"]


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

    def get(self, usage_type: str) -> Optional[UsageDimension]:
        """Look up one dimension, e.g. ``summary.get("accepted_events")``."""

        key = getattr(usage_type, "value", usage_type)
        return next((item for item in self.dimensions if item.type == key), None)
