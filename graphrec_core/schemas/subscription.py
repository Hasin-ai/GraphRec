from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: Literal["free", "basic", "pro"]
    status: str
    period_start: datetime
    period_end: datetime
    limits: dict[str, int]
    project_defaults: bool

    @field_validator("limits")
    @classmethod
    def validate_limits(cls, value: dict[str, int]) -> dict[str, int]:
        if any(isinstance(limit, bool) or limit < 0 for limit in value.values()):
            raise ValueError("Limits must be non-negative integers")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "SubscriptionResponse":
        if self.period_end <= self.period_start:
            raise ValueError("Subscription period end must follow its start")
        return self
