"""`FeatureBuilder`: determinism, ordering, and the things it refuses to invent.

The builder is the shared surface between training, evaluation and serving, so
the properties tested here are the ones that would silently produce a
train/serve skew rather than an exception: index assignment that depends on
iteration order, a sequence that is not in time order, a feature substituted for
an item nobody merged.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from graphrec.common.enums import Availability, EventType
from graphrec.ml.features.builder import (
    EVENT_WEIGHTS,
    POSITIVE_EVENTS,
    PRICE_BUCKET_BOUNDS,
    FeatureBuilder,
    Interaction,
    Product,
)

BASE = dt.datetime(2026, 3, 1, 12, 0, tzinfo=dt.UTC)


def at(hours: int) -> dt.datetime:
    return BASE + dt.timedelta(hours=hours)


def view(user: str, item: str, hours: int) -> Interaction:
    return Interaction(
        user_ref=user, item_ref=item, event_type=EventType.VIEW, occurred_at=at(hours)
    )


def test_the_same_rows_in_a_different_order_build_the_same_dataset() -> None:
    rows = [view("u1", "a", 0), view("u2", "b", 1), view("u1", "b", 2)]
    builder = FeatureBuilder()

    forwards = builder.build(rows)
    backwards = builder.build(list(reversed(rows)))

    assert forwards.user_refs == backwards.user_refs
    assert forwards.item_refs == backwards.item_refs
    assert forwards.sequences == backwards.sequences


def test_simultaneous_interactions_still_order_deterministically() -> None:
    """Two events in the same millisecond are common in a batch import, and an
    order left to the query planner would move an interaction across the
    train/test boundary between runs."""
    rows = [view("u1", "b", 0), view("u1", "a", 0)]
    builder = FeatureBuilder()

    first = builder.build(rows)
    second = builder.build(list(reversed(rows)))

    assert first.sequences == second.sequences
    assert [first.item_refs[i] for i in first.sequences[0]] == ["a", "b"], "tie broken by item_ref"


def test_a_sequence_is_in_ascending_time_order() -> None:
    rows = [view("u1", "c", 5), view("u1", "a", 1), view("u1", "b", 3)]
    dataset = FeatureBuilder().build(rows)

    times = dataset.timestamps[0]
    assert times == sorted(times)
    assert [dataset.item_refs[i] for i in dataset.sequences[0]] == ["a", "b", "c"]


def test_remove_from_cart_is_kept_out_of_the_sequence() -> None:
    """An edge meaning "not this" is not an edge a similarity model can use."""
    rows = [
        view("u1", "a", 0),
        Interaction(
            user_ref="u1", item_ref="b", event_type=EventType.REMOVE_FROM_CART, occurred_at=at(1)
        ),
    ]
    dataset = FeatureBuilder().build(rows)

    assert len(dataset.sequences[0]) == 1
    assert EventType.REMOVE_FROM_CART not in POSITIVE_EVENTS
    assert EVENT_WEIGHTS[EventType.REMOVE_FROM_CART] < 0, "kept, and negative"


def test_a_product_with_no_interaction_still_gets_an_index() -> None:
    """Cold-start items are the point of having a graph; an item with no index
    can never be recommended."""
    dataset = FeatureBuilder().build(
        [view("u1", "a", 0)],
        [Product(external_id="a"), Product(external_id="never-touched")],
    )

    assert dataset.item_index("never-touched") is not None
    assert dataset.n_items == 2


def test_an_interaction_against_an_unmerged_product_gets_zeroed_features() -> None:
    """Not an invented average — a truthful "we know nothing about this item"."""
    dataset = FeatureBuilder().build([view("u1", "ghost", 0)], [])

    index = dataset.item_index("ghost")
    assert index is not None
    assert np.all(dataset.item_features[index] == 0.0)
    assert dataset.item_categories[index] == 0, "the reserved no-category row"


def test_the_purchase_weight_reaches_the_dataset() -> None:
    rows = [
        Interaction(user_ref="u1", item_ref="a", event_type=EventType.PURCHASE, occurred_at=at(0))
    ]
    dataset = FeatureBuilder().build(rows)

    assert dataset.weights[0][0] == EVENT_WEIGHTS[EventType.PURCHASE]


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (None, 0),
        (0, 0),
        (999, 0),
        (1_000, 1),
        (5_000, 2),
        (20_000, 3),
        (100_000, 4),
        (10_000_000, 4),
    ],
)
def test_price_buckets_are_inclusive_at_the_lower_bound(price: int | None, expected: int) -> None:
    dataset = FeatureBuilder().build([], [Product(external_id="a", price_minor=price)])

    assert dataset.item_features[0, 0] == pytest.approx(expected / len(PRICE_BUCKET_BOUNDS))


@pytest.mark.parametrize(
    ("availability", "score"),
    [(Availability.IN_STOCK, 1.0), (Availability.LOW_STOCK, 0.5), (Availability.OUT_OF_STOCK, 0.0)],
)
def test_availability_is_ordinal(availability: Availability, score: float) -> None:
    dataset = FeatureBuilder().build([], [Product(external_id="a", availability=availability)])

    assert dataset.item_features[0, 1] == pytest.approx(score)


def test_recency_uses_the_reference_time_and_not_the_clock() -> None:
    """A snapshot evaluated a week after it was built must produce the features
    it produced when it was built."""
    product = Product(external_id="a", updated_at=at(0))
    builder = FeatureBuilder()

    fresh = builder.build([], [product], reference_time=at(0))
    stale = builder.build([], [product], reference_time=at(24 * 60))

    assert fresh.item_features[0, 2] == pytest.approx(1.0)
    assert stale.item_features[0, 2] < 0.2


def test_recent_truncates_from_the_left() -> None:
    builder = FeatureBuilder(max_sequence_length=3)

    assert builder.recent([1, 2, 3, 4, 5]) == [3, 4, 5], "the tail, not the head"


def test_item_popularity_counts_repeats(builder: FeatureBuilder) -> None:
    rows = [view("u1", "a", 0), view("u2", "a", 1), view("u1", "b", 2)]
    counts = builder.build(rows).item_popularity()

    assert counts.tolist() == [2, 1]


def test_categories_are_indexed_from_one(builder: FeatureBuilder) -> None:
    """Zero is reserved, so `n_categories` is one more than the catalogue has."""
    dataset = builder.build(
        [],
        [
            Product(external_id="a", category="shoes"),
            Product(external_id="b", category="hats"),
            Product(external_id="c"),
        ],
    )

    assert dataset.category_refs == ["hats", "shoes"], "sorted, so the index is reproducible"
    assert dataset.n_categories == 3
    assert dataset.item_categories.tolist() == [2, 1, 0]
