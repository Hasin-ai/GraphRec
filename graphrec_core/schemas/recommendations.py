from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    user_id: str | None = None
    top_n: int = Field(default=10, ge=1, le=100)
    exclude_product_ids: list[str] = Field(default_factory=list, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)


class RecommendationItem(BaseModel):
    external_product_id: str
    position: int


class RecommendationResponse(BaseModel):
    request_id: str
    items: list[RecommendationItem]
    model_version_id: UUID | None = None
    strategy: str
    fallback_used: bool
    fallback_tier: str


class ImpressionFeedback(BaseModel):
    event_id: str
    request_id: str
    items: list[RecommendationItem]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)


class ClickFeedback(BaseModel):
    event_id: str
    request_id: str
    impression_event_id: str | None = None
    external_product_id: str
    position: int
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)


class ConversionFeedback(BaseModel):
    event_id: str
    request_id: str
    external_product_id: str
    position: int | None = None
    value: Decimal | None = Field(default=None, ge=0)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackResponse(BaseModel):
    event_id: str
    feedback_type: str
    accepted: bool
    duplicate: bool
    received_at: datetime
