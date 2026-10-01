from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


#: Single source of the accepted interaction types. The console's list
#: (frontend_02/src/api/eventTypes.ts) is checked against this by tests.
EVENT_TYPES = ("view", "click", "add_to_cart", "remove_from_cart", "purchase", "rating", "search", "add_to_wishlist")
EventType = Literal["view", "click", "add_to_cart", "remove_from_cart", "purchase", "rating", "search", "add_to_wishlist"]


class EventSubmit(BaseModel):
    event_id: str = Field(..., max_length=100)
    # UC-09: unsupported interaction types are rejected (matches the SDK EventType enum).
    event_type: EventType
    user_id: str | None = Field(default=None, max_length=256)
    external_product_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Customer ID cannot be blank.")
        return normalized


class EventBatchSubmit(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    events: list[EventSubmit] = Field(..., min_length=1, max_length=1000)


class EventItemOutcome(BaseModel):
    event_id: str
    status: str
    reason: str | None = None


class EventBatchResponse(BaseModel):
    id: UUID
    status: str
    request_id: str | None = None
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    outcomes: list[EventItemOutcome] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True
