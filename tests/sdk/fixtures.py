"""Wire-shaped response fixtures, checked against `frontend/openapi.json`.

Hand-written fixtures that agree with a hand-written decoder catch nothing, so
`test_routes.py` validates each of these against the response schema the API
publishes. A fixture invented from memory that omits a field the SDK reads fails
there rather than in a customer's integration.
"""

from __future__ import annotations

from typing import Any

RECOMMENDATION: dict[str, Any] = {
    "request_id": "req-1",
    "model_version": {"version_id": "mv-1", "version_number": 7},
    "strategy": "personalized",
    "fallback_applied": False,
    "items": [
        {
            "external_product_id": "sku-1",
            "rank": 1,
            "score": 0.91,
            "candidate_source": "co_view",
        }
    ],
    "ordering_policy_version": 2,
    "latency_ms": 41,
}

FEEDBACK: dict[str, Any] = {
    "request_id": "req-1",
    "received": 1,
    "accepted": 1,
    "duplicates": 0,
    "unknown_products": [],
}

RECEIPT: dict[str, Any] = {
    "event_id": "11111111-1111-4111-8111-111111111111",
    "status": "duplicate_confirmed",
    "first_received_at": "2026-08-24T09:00:00Z",
}


def submission(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "submission_id": "sub-1",
        "kind": "product_sync",
        "status": "processing",
        "stage": "received",
        "reference": "2026-08-24-nightly",
        "counts": {"received": 1, "accepted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "errors": [],
        "error_count": 0,
        "failure_code": None,
        "submitted_at": "2026-08-24T10:00:00Z",
        "completed_at": None,
    }
    base.update(over)
    return base


ACCEPTED = submission()
SUCCEEDED = submission(
    status="succeeded",
    stage="completed",
    counts={"received": 1, "accepted": 1, "updated": 0, "skipped": 0, "failed": 0},
    completed_at="2026-08-24T10:00:30Z",
)
FAILED = submission(
    status="failed",
    stage="failed",
    counts={"received": 1, "accepted": 0, "updated": 0, "skipped": 0, "failed": 1},
    errors=[{"ref": "sku-1", "reason": "Title is required."}],
    error_count=1,
    failure_code="items_rejected",
    completed_at="2026-08-24T10:00:30Z",
)
