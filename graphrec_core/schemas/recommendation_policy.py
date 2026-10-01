from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RecommendationPolicyUpdate(BaseModel):
    diversity_enabled: bool = False
    max_per_category: int = Field(default=3, ge=1, le=100)
    freshness_enabled: bool = False
    freshness_weight: float = Field(default=0.2, ge=0, le=0.3)
    freshness_half_life_days: int = Field(default=30, ge=1, le=3650)


class RecommendationPolicyResource(RecommendationPolicyUpdate):
    tenant_id: UUID
    configured: bool
    version: int
    updated_at: datetime | None = None
