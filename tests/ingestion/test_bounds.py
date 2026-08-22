"""The collection bounds — decided before a single row is read.

These need no database, and that is a property worth having rather than a
convenience: an oversize collection must be refused *before* it is staged, or
the bound is not protecting anything. If any of these assertions needed a
transaction, the check would be happening too late.
"""

from __future__ import annotations

import pytest

from graphrec.common.enums import SubmissionKind
from graphrec.common.errors import ErrorClass, GraphRecError
from graphrec.domain.ingestion import IngestionService

BOUND = 5_000


@pytest.fixture
def service() -> IngestionService:
    """The prototype's own bounds: "Bounded to 5,000 products per submission."
    (L1356) and "Bounded to 5,000 events per batch." (L1370).
    """
    return IngestionService(max_events_per_batch=BOUND, max_products_per_sync=BOUND)


def _refuse(service: IngestionService, kind: SubmissionKind, items) -> GraphRecError:
    with pytest.raises(GraphRecError) as caught:
        service._collection(kind, items)
    return caught.value


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_the_bound_is_five_thousand_for_both_kinds(service, kind) -> None:
    assert service.limit_for(kind) == BOUND


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_exactly_the_bound_is_accepted(service, kind) -> None:
    """A limit of 5,000 means 5,000 is allowed. Off-by-one here is a support ticket."""
    assert len(service._collection(kind, [{}] * BOUND)) == BOUND


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_one_over_the_bound_is_413(service, kind) -> None:
    """413, not 422.

    Both are `validation` to the console — `DEFAULT_STATUS` in
    `graphrec/common/errors.py` records exactly this — but the status line has
    to distinguish them, because "your body was too big" and "your body was
    wrong" call for different fixes. An integration that retries a 422 unchanged
    is confused; one that retries a 413 unchanged is in a loop.
    """
    error = _refuse(service, kind, [{}] * (BOUND + 1))
    assert error.status_code == 413
    assert error.error_class is ErrorClass.VALIDATION


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_the_rejection_names_the_bound(service, kind) -> None:
    """L1612 and L1627: "A batch is bounded to 5,000 events. Split the
    collection and submit it in parts." — the number is in the sentence, so a
    caller told only "too large" does not have to guess how far to split.
    """
    error = _refuse(service, kind, [{}] * (BOUND + 1))
    assert "5,000" in error.reason()


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_an_empty_collection_is_a_field_error_not_a_bound_error(service, kind) -> None:
    """Nothing to do is a mistake in the request, not an oversize one."""
    error = _refuse(service, kind, [])
    assert error.status_code == 422
    assert [fe.field for fe in error.field_errors] in (["events"], ["products"])


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_a_missing_identifier_is_refused_with_the_prototypes_field_marker(service, kind) -> None:
    """L1611: "A synchronization identifier is required so a repeated submission
    is not applied twice." — the *reason* the field exists, in the banner.
    """
    with pytest.raises(GraphRecError) as caught:
        service._reference(kind, "   ")
    error = caught.value
    assert error.status_code == 422
    assert [fe.field for fe in error.field_errors] in (["batch_id"], ["sync_id"])
    assert error.field_errors[0].reason == "Required."


@pytest.mark.parametrize("kind", list(SubmissionKind))
def test_the_identifier_is_trimmed_not_rejected_for_whitespace(service, kind) -> None:
    """A trailing newline from a shell pipeline must not fork the idempotency key."""
    assert service._reference(kind, "  batch-4471\n") == "batch-4471"
