"""Tenant policies: recommendation re-ranking rules and automatic retraining."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel, InputModel

__all__ = [
    "RecommendationPolicy",
    "RecommendationPolicyUpdate",
    "RetrainingPolicy",
    "RetrainingPolicyUpdate",
]


class RecommendationPolicyUpdate(InputModel):
    """Body of ``PUT /v1/recommendation-policy`` (mirrors the server defaults and bounds)."""

    diversity_enabled: bool = False
    max_per_category: int = Field(default=3, ge=1, le=100)
    freshness_enabled: bool = False
    freshness_weight: float = Field(default=0.2, ge=0, le=0.3)
    freshness_half_life_days: int = Field(default=30, ge=1, le=3650)


class RecommendationPolicy(GraphRecModel):
    """Diversity and freshness re-ranking rules applied to recommendations."""

    tenant_id: UUID
    #: ``False`` while the tenant still runs on the server defaults.
    configured: bool
    version: int
    diversity_enabled: bool
    max_per_category: int
    freshness_enabled: bool
    freshness_weight: float
    freshness_half_life_days: int
    updated_at: Optional[datetime] = None


class RetrainingPolicyUpdate(InputModel):
    """Body of ``PUT /v1/retraining-policy`` (mirrors the server defaults and bounds)."""

    schedule_enabled: bool = False
    interval_minutes: int = Field(default=1440, ge=1, le=43_200)
    event_trigger_enabled: bool = False
    event_threshold: int = Field(default=1000, ge=1, le=10_000_000)
    epochs: int = Field(default=3, ge=1, le=10)


class RetrainingPolicy(GraphRecModel):
    """Scheduled and event-triggered retraining settings plus the evaluator's last outcome."""

    tenant_id: UUID
    configured: bool
    schedule_enabled: bool
    interval_minutes: int
    next_run_at: Optional[datetime] = None
    event_trigger_enabled: bool
    event_threshold: int
    epochs: int
    new_events_since_last_training: int
    last_training_requested_at: Optional[datetime] = None
    training_in_progress: bool
    minimum_interval_minutes: int
    last_evaluated_at: Optional[datetime] = None
    last_trigger: Optional[str] = None
    last_outcome: Optional[str] = None
    last_outcome_detail: Optional[str] = None
    last_outcome_at: Optional[datetime] = None
    last_job_id: Optional[UUID] = None
    updated_at: Optional[datetime] = None
