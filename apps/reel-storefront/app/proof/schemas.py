"""Schemas for the GraphRec Capability Proof Battery (P1–P19)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProofCheckResult(BaseModel):
    id: str = Field(description="Proof identifier, e.g. P1, P2... P19")
    name: str = Field(description="Descriptive title of the capability")
    passed: bool = Field(description="Whether the verification passed")
    duration_ms: float = Field(description="Execution latency of the check in milliseconds")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Concrete measurements, IDs, and metrics")
    detail: Optional[str] = Field(default=None, description="Diagnostic notes or error explanations")


class ProofBatterySummary(BaseModel):
    run_id: str
    profile: str
    started_at: datetime
    completed_at: datetime
    total_checks: int
    passed_checks: int
    failed_checks: int
    success_rate: float
    total_duration_ms: float


class ProofReport(BaseModel):
    summary: ProofBatterySummary
    checks: List[ProofCheckResult]
