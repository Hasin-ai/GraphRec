from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RetrainingPolicyUpdate(BaseModel):
    schedule_enabled: bool = False
    interval_minutes: int = Field(default=1440, ge=1, le=43_200)
    event_trigger_enabled: bool = False
    event_threshold: int = Field(default=1000, ge=1, le=10_000_000)
    epochs: int = Field(default=3, ge=1, le=10)


class RetrainingPolicyResource(BaseModel):
    tenant_id: UUID
    configured: bool
    schedule_enabled: bool
    interval_minutes: int
    next_run_at: datetime | None = None
    event_trigger_enabled: bool
    event_threshold: int
    epochs: int
    new_events_since_last_training: int
    last_training_requested_at: datetime | None = None
    training_in_progress: bool
    minimum_interval_minutes: int
    last_evaluated_at: datetime | None = None
    last_trigger: str | None = None
    last_outcome: str | None = None
    last_outcome_detail: str | None = None
    last_outcome_at: datetime | None = None
    last_job_id: UUID | None = None
    updated_at: datetime | None = None
