from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class RecommendationRequest(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, max_length=256)
    top_n: int = Field(default=10, ge=1, le=100)
    exclude_product_ids: list[str] = Field(default_factory=list, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)
    fallback_allowed: bool = True

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Customer ID cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def require_customer_or_session(self) -> "RecommendationRequest":
        session_id = self.context.get("session_id")
        recent = self.context.get("recent_product_ids")
        has_session = isinstance(session_id, str) and bool(session_id.strip())
        has_recent = isinstance(recent, list) and any(
            isinstance(item, str) and bool(item.strip()) for item in recent
        )
        if not (self.user_id and self.user_id.strip()) and not (has_session or has_recent):
            raise ValueError("Provide a customer ID or usable session context.")
        return self


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
    #: XR-F-04 / XR-NF-02: re-ranking rules applied and the policy version used.
    applied_rules: list[str] = Field(default_factory=list)
    rules_version: int | None = None


class ImpressionFeedback(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    items: list[RecommendationItem] = Field(min_length=1, max_length=100)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)


class ClickFeedback(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    impression_event_id: str | None = None
    external_product_id: str
    position: int
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)


class ConversionFeedback(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
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
