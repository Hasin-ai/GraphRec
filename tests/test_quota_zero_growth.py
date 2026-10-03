"""require_capacity admits zero-growth writes even when inventory is over its limit."""
from uuid import uuid4

from graphrec_core.usage.limits import require_capacity


class _ExplodingSession:
    """Any database access means the check did not short-circuit."""
    def __getattr__(self, name):
        raise AssertionError(f"database touched via {name}")


def test_zero_quantity_is_admitted_without_reading_limits():
    require_capacity(_ExplodingSession(), uuid4(), "stored_products", 0)
    require_capacity(_ExplodingSession(), uuid4(), "accepted_events", 0)
