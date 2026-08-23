"""The model registry: versions, their metrics, and their lifecycle."""

from __future__ import annotations

from graphrec.domain.registry.lifecycle import (
    Action,
    MetricFloor,
    Verdict,
    VersionContext,
    can_activate,
    can_archive,
    can_rollback,
    judge,
)
from graphrec.domain.registry.registration import Registration, register
from graphrec.domain.registry.service import RegistryService, VersionSummary

__all__ = [
    "Action",
    "MetricFloor",
    "Registration",
    "RegistryService",
    "Verdict",
    "VersionContext",
    "VersionSummary",
    "can_activate",
    "can_archive",
    "can_rollback",
    "judge",
    "register",
]
