"""Graph construction, checked against a hand-built adjacency.

The CSR arrays are the sort of thing that is right or subtly transposed, and a
transposed graph does not raise — it trains a model that has learned the wrong
relation. So the small tests here spell the expected adjacency out by hand
rather than comparing the structure to itself.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from graphrec.common.enums import EventType
from graphrec.ml.features.builder import FeatureBuilder, Interaction, Product
from graphrec.ml.graph.build import build_graph

BASE = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)


def view(user: str, item: str, hours: int) -> Interaction:
    return Interaction(
        user_ref=user,
        item_ref=item,
        event_type=EventType.VIEW,
        occurred_at=BASE + dt.timedelta(hours=hours),
    )


def build(rows: list[Interaction], items: list[str] | None = None):
    products = [Product(external_id=ref) for ref in (items or [])]
    return build_graph(FeatureBuilder().build(rows, products)), FeatureBuilder().build(
        rows, products
    )


def test_both_directions_hold_the_same_edges() -> None:
    graph, _ = build([view("u1", "a", 0), view("u1", "b", 1), view("u2", "a", 2)], ["a", "b"])

    assert graph.n_edges == 3
    assert graph.user_indices.size == graph.item_indices.size


def test_the_adjacency_matches_a_hand_built_one() -> None:
    graph, dataset = build([view("u1", "a", 0), view("u1", "b", 1), view("u2", "a", 2)], ["a", "b"])
    a, b = dataset.item_index("a"), dataset.item_index("b")
    u1, u2 = dataset.user_index("u1"), dataset.user_index("u2")

    assert sorted(graph.items_of(u1).tolist()) == sorted([a, b])
    assert graph.items_of(u2).tolist() == [a]
    assert sorted(graph.users_of(a).tolist()) == sorted([u1, u2])
    assert graph.users_of(b).tolist() == [u1]


def test_indptr_is_cumulative_and_ends_at_the_edge_count() -> None:
    graph, _ = build([view("u1", "a", 0), view("u1", "b", 1), view("u2", "a", 2)], ["a", "b"])

    assert graph.user_indptr[0] == 0
    assert graph.user_indptr[-1] == graph.n_edges
    assert graph.item_indptr[-1] == graph.n_edges
    assert np.all(np.diff(graph.user_indptr) >= 0)


def test_a_node_s_edges_are_oldest_first() -> None:
    """The sampler reads the tail of a slice for recency, so the ordering here
    is what makes `SamplingStrategy.RECENT` mean what it says."""
    graph, _ = build([view("u1", "a", 5), view("u1", "b", 1), view("u1", "c", 3)], ["a", "b", "c"])

    start, end = graph.user_indptr[0], graph.user_indptr[1]
    times = graph.user_times[start:end]
    assert times.tolist() == sorted(times.tolist())


def test_repeat_interactions_are_kept_as_separate_edges() -> None:
    """Collapsing them would make a browsed-to-death product indistinguishable
    from one seen once."""
    graph, _ = build([view("u1", "a", 0), view("u1", "a", 1), view("u1", "a", 2)], ["a"])

    assert graph.n_edges == 3
    assert graph.degree_of_item(0) == 3


def test_a_product_nobody_touched_is_isolated_and_reported() -> None:
    graph, dataset = build([view("u1", "a", 0)], ["a", "cold"])
    cold = dataset.item_index("cold")

    assert graph.isolated_items().tolist() == [cold]
    assert graph.degree_of_item(cold) == 0
    assert graph.users_of(cold).size == 0


def test_the_purchase_weight_survives_into_the_edge() -> None:
    rows = [
        Interaction(user_ref="u1", item_ref="a", event_type=EventType.PURCHASE, occurred_at=BASE)
    ]
    graph, _ = build(rows, ["a"])

    assert graph.user_weights[0] == 5.0


def test_the_fixture_graph_is_almost_entirely_connected(graph, split) -> None:
    """A sanity floor on the fixture itself: a corpus where much of the
    catalogue is isolated would make the coverage metric meaningless.

    Not zero isolated items — a handful is honest. The temporal split removes
    two interactions per user, and at 60 users that is enough to strand a
    long-tail product whose only two touches were both held out. That is exactly
    what happens to a real catalogue, and the model still has to place the item
    from its static features alone.
    """
    assert graph.n_users == split.train.n_users
    assert graph.n_items == split.train.n_items
    assert graph.isolated_items().size / graph.n_items < 0.05
