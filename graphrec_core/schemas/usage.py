from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

UsageType = Literal[
    "accepted_events",
    "recommendation_requests",
    "training_jobs",
    "training_cpu_seconds",
    "stored_products",
    "artifact_storage_bytes",
    "active_model_versions",
    "inference_replicas",
    "replica_runtime_minutes",
]
UsageUnit = Literal["count", "seconds", "bytes", "minutes"]
UsageNumber = int | float


class UsageDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: UsageType
    used: UsageNumber
    limit: int | None
    remaining: UsageNumber | None
    unit: UsageUnit
    #: NR-F-15: ``False`` when GraphRec does not measure this dimension yet;
    #: ``used`` is then 0 by convention and must not be shown as a measurement.
    measured: bool = True
    #: UC-24: ``period`` sums the ledger over the requested period; ``current`` is a
    #: point-in-time gauge (stored products, retained versions, storage, replicas)
    #: that always reflects now, whatever period was requested.
    scope: Literal["period", "current"] = "period"

    @model_validator(mode="after")
    def validate_values(self) -> "UsageDimension":
        if self.used < 0:
            raise ValueError("Used quantity must be non-negative")
        if self.limit is not None and self.limit < 0:
            raise ValueError("Limit must be non-negative")
        if self.remaining is not None and self.remaining < 0:
            raise ValueError("Remaining quantity must be non-negative")
        if (self.limit is None) != (self.remaining is None):
            raise ValueError("Informational dimensions require null limit and remaining")
        return self


class UsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: datetime
    period_end: datetime
    reset_at: datetime
    dimensions: list[UsageDimension]
    last_reconciled_at: datetime
    project_defaults: bool
    #: UC-24: False when a past period was requested with ``?period=YYYY-MM``.
    current_period: bool = True

    @model_validator(mode="after")
    def validate_period(self) -> "UsageSummaryResponse":
        if self.period_end <= self.period_start or self.reset_at != self.period_end:
            raise ValueError("Usage period and reset boundary are invalid")
        if len(self.dimensions) != 9 or len({item.type for item in self.dimensions}) != 9:
            raise ValueError("All supported usage dimensions are required")
        return self


Granularity = Literal["hour", "day", "week"]


class UsageTrendBucket(BaseModel):
    start: datetime
    values: dict[str, UsageNumber]


class UsageTrendResponse(BaseModel):
    """XR-F-07: summarized usage by period and usage type, read from the usage ledger."""

    tenant_id: str
    start: datetime
    end: datetime
    granularity: Granularity
    usage_types: list[str]
    buckets: list[UsageTrendBucket]
    totals: dict[str, UsageNumber]
