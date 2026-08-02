from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EventSubmit(BaseModel):
    event_id: str = Field(..., max_length=100)
    event_type: str = Field(..., max_length=48)
    user_id: str | None = None
    external_product_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class EventBatchSubmit(BaseModel):
    events: list[EventSubmit] = Field(..., min_items=1)


class EventBatchResponse(BaseModel):
    id: UUID
    status: str
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    created_at: datetime

    class Config:
        from_attributes = True
