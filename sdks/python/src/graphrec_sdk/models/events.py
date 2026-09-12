from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from pydantic import Field, field_validator

from .._ids import new_id
from .._serialization import utcnow
from ._base import GraphRecModel, InputModel, ItemList

__all__ = ["EventBatch", "EventBatchList", "EventBatchResult", "EventInput", "EventReceipt"]


class EventInput(InputModel):
    """A customer interaction (``EventSubmit`` on the server).

    ``event_id`` is the idempotency key: sending the same ID twice is recorded
    once. It defaults to a random ID; pass a deterministic one (see
    :func:`graphrec_sdk.deterministic_id`) when the same fact can be replayed.
    """

    event_id: str = Field(default_factory=lambda: new_id("evt"), min_length=1, max_length=100)
    #: See :class:`graphrec_sdk.EventType` (``view``, ``click``, ``add_to_cart``, ``purchase``...).
    event_type: str = Field(min_length=1, max_length=48)
    #: Your customer identifier. Omit for anonymous sessions.
    user_id: Optional[str] = None
    external_product_id: Optional[str] = Field(default=None, max_length=100)
    context: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utcnow)

    @field_validator("event_type", mode="before")
    @classmethod
    def _enum_value(cls, value: Any) -> Any:
        return getattr(value, "value", value)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class EventReceipt(GraphRecModel):
    """Result of ``POST /v1/events``."""

    event_id: str
    accepted: bool
    #: ``True`` when GraphRec had already recorded this ``event_id``.
    duplicate: bool
    received_at: datetime


class EventBatch(GraphRecModel):
    id: UUID
    status: str
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    created_at: datetime


class EventBatchList(ItemList[EventBatch]):
    pass


class EventBatchResult(GraphRecModel):
    """Aggregate of one logical batch that the SDK may have split into several requests."""

    batches: List[EventBatch] = Field(default_factory=list)
    accepted_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0

    @classmethod
    def from_batches(cls, batches: Iterable[EventBatch]) -> EventBatchResult:
        items = list(batches)
        return cls(
            batches=items,
            accepted_count=sum(b.accepted_count for b in items),
            duplicate_count=sum(b.duplicate_count for b in items),
            rejected_count=sum(b.rejected_count for b in items),
        )

    @property
    def batch_ids(self) -> List[UUID]:
        return [batch.id for batch in self.batches]
