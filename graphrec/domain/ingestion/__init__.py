"""Ingestion: single events, bounded collections, and the report on each."""

from __future__ import annotations

from graphrec.domain.ingestion.service import (
    SYNC_MODE_UPSERT,
    SYNC_MODE_UPSERT_AND_DISABLE_MISSING,
    SYNC_MODES,
    EventOutcome,
    IngestionService,
    SubmissionOutcome,
)
from graphrec.domain.ingestion.validation import (
    ItemInvalid,
    normalise_event,
    normalise_product,
    reference_for,
)

__all__ = [
    "SYNC_MODES",
    "SYNC_MODE_UPSERT",
    "SYNC_MODE_UPSERT_AND_DISABLE_MISSING",
    "EventOutcome",
    "IngestionService",
    "ItemInvalid",
    "SubmissionOutcome",
    "normalise_event",
    "normalise_product",
    "reference_for",
]
