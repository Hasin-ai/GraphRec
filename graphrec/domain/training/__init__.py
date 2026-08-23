"""Training: admission, the frozen dataset, and the nine stages that run over it."""

from __future__ import annotations

from graphrec.domain.training.eligibility import Eligibility
from graphrec.domain.training.pipeline import TrainingPipeline
from graphrec.domain.training.service import (
    RequestOutcome,
    StageRail,
    TrainingRequest,
    TrainingService,
    eligibility_payload,
    render_stage_rail,
)
from graphrec.domain.training.snapshot import SnapshotContents

__all__ = [
    "Eligibility",
    "RequestOutcome",
    "SnapshotContents",
    "StageRail",
    "TrainingPipeline",
    "TrainingRequest",
    "TrainingService",
    "eligibility_payload",
    "render_stage_rail",
]
