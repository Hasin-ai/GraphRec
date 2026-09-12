"""JSON encoding shared by every request.

The encoder is deliberately the single source of truth for request bytes: the
bulk helpers measure payload size with the same function the transport uses to
send it, so byte-budget chunking is exact.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    """Convert SDK inputs (models, datetimes, decimals, UUIDs...) into JSON types."""

    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump(mode="python", by_alias=True, exclude_none=True))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    return value


def format_datetime(value: datetime) -> str:
    """ISO-8601 with an explicit offset. Naive datetimes are treated as UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def encode_json(value: Any) -> bytes:
    """Compact UTF-8 JSON bytes, exactly as sent on the wire."""

    return json.dumps(
        to_jsonable(value), separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
