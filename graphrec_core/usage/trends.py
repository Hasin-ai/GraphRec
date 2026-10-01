"""XR-F-07: usage trends over time from the append-only usage ledger.

Buckets are aligned in UTC (``date_trunc``); weeks start on Monday. Empty
buckets are returned as zero so charts show gaps honestly. Values are raw
ledger sums, so they reconcile exactly with ``usage_events``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.database.models import UsageEvent
from graphrec_core.errors import ApiError

STEP = {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}
MAX_SPAN = {"hour": timedelta(days=31), "day": timedelta(days=366), "week": timedelta(weeks=104)}
METERED_TYPES = ("accepted_events", "recommendation_requests", "training_jobs", "training_cpu_seconds",
                 "artifact_storage_bytes", "inference_replicas", "replica_runtime_minutes")


def floor_to(value: datetime, granularity: str) -> datetime:
    value = value.astimezone(timezone.utc)
    if granularity == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    day = value.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "day":
        return day
    return day - timedelta(days=day.weekday())


def bucket_starts(start: datetime, end: datetime, granularity: str) -> list[datetime]:
    current, out = floor_to(start, granularity), []
    while current < end:
        out.append(current)
        current += STEP[granularity]
    return out


def validate_range(start: datetime, end: datetime, granularity: str) -> None:
    fields = []
    if start.tzinfo is None or end.tzinfo is None:
        fields.append({"field": "start", "message": "Use ISO-8601 timestamps with a time zone."})
    elif end <= start:
        fields.append({"field": "end", "message": "End must be after start."})
    elif end - start > MAX_SPAN[granularity]:
        fields.append({"field": "granularity", "message": f"A {granularity} trend can cover at most {MAX_SPAN[granularity].days} days."})
    if fields:
        raise ApiError(422, "validation_failed", "One or more request fields are invalid", details={"fields": fields})


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def usage_trend(db: Session, tenant_id: UUID, *, start: datetime, end: datetime, granularity: str,
                usage_types: list[str] | None = None) -> dict:
    validate_range(start, end, granularity)
    types = list(usage_types or METERED_TYPES)
    unknown = sorted(set(types) - set(METERED_TYPES))
    if unknown:
        raise ApiError(422, "validation_failed", "One or more request fields are invalid",
                       details={"fields": [{"field": "types", "message": f"Unsupported usage type: {', '.join(unknown)}"}]})
    starts = bucket_starts(start, end, granularity)
    bucket = func.date_trunc(granularity, func.timezone("UTC", UsageEvent.occurred_at)).label("bucket")
    rows = db.execute(select(UsageEvent.usage_type, bucket, func.sum(UsageEvent.quantity))
        .where(UsageEvent.tenant_id == tenant_id, UsageEvent.usage_type.in_(types),
               UsageEvent.occurred_at >= (starts[0] if starts else start), UsageEvent.occurred_at < end)
        .group_by(UsageEvent.usage_type, bucket)).all()
    table: dict[datetime, dict[str, Decimal]] = {s: {t: Decimal(0) for t in types} for s in starts}
    for usage_type, bucket_start, quantity in rows:
        key = bucket_start.replace(tzinfo=timezone.utc)
        if key in table:
            table[key][usage_type] += quantity
    totals = {t: _number(sum((table[s][t] for s in starts), Decimal(0))) for t in types}
    return {"tenant_id": str(tenant_id), "start": starts[0] if starts else start, "end": end,
            "granularity": granularity, "usage_types": types,
            "buckets": [{"start": s, "values": {t: _number(v) for t, v in table[s].items()}} for s in starts],
            "totals": totals}
