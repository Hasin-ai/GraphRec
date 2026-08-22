"""Bounded 2-hop sampling: the shape contract, the bound, and the padding.

The bound is the point of the module — an unbounded neighbourhood over a
bestseller decides the memory ceiling for a whole batch — so most of these tests
are about what happens at the two extremes: a node with far more neighbours than
the fan-out, and a node with none.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from graphrec.common.enums import EventType
from graphrec.ml.features.builder import FeatureBuilder, Interaction, Product
from graphrec.ml.graph.build import build_graph
from graphrec.ml.graph.sample import PAD, SamplingStrategy, sample_two_hop

BASE = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)


def view(user: str, item: str, hours: int) -> Interaction:
    return Interaction(
        user_ref=user,
        item_ref=item,
        event_type=EventType.VIEW,
        occurred_at=BASE + dt.timedelta(hours=hours),
    )


def test_the_sample_has_the_declared_shape(graph, rng) -> None:
    seeds = np.array([0, 1, 2], dtype=np.int64)

    sample = sample_two_hop(graph, seeds, rng, fanouts=(4, 3))

    assert sample.hop1.shape == (3, 4)
    assert sample.hop2.shape == (3, 4, 3)
    assert sample.hop1_mask.shape == sample.hop1.shape
    assert sample.hop2_mask.shape == sample.hop2.shape


def test_a_hot_item_is_bounded_at_the_fanout(rng) -> None:
    rows = [view(f"u{i}", "hot", i) for i in range(200)]
    graph = build_graph(FeatureBuilder().build(rows, [Product(external_id="hot")]))

    sample = sample_two_hop(graph, np.array([0]), rng, fanouts=(5, 5))

    assert int(sample.hop1_mask.sum()) == 5, "five of two hundred, and not one more"


def test_a_cold_item_produces_an_all_false_mask_and_no_index(rng) -> None:
    """A padding bug that silently aggregates item 0 into every cold item is
    exactly the fault that surfaces three phases later as "the model recommends
    the same thing to everyone"."""
    rows = [view("u1", "warm", 0)]
    dataset = FeatureBuilder().build(
        rows, [Product(external_id="warm"), Product(external_id="cold")]
    )
    graph = build_graph(dataset)
    cold = dataset.item_index("cold")

    sample = sample_two_hop(graph, np.array([cold]), rng, fanouts=(3, 3))

    assert not sample.hop1_mask.any()
    assert not sample.hop2_mask.any()
    assert np.all(sample.hop1 == PAD)
    assert np.all(sample.hop2 == PAD)


def test_padding_is_minus_one_and_never_zero(rng) -> None:
    rows = [view("u1", "a", 0), view("u2", "a", 1)]
    graph = build_graph(FeatureBuilder().build(rows, [Product(external_id="a")]))

    sample = sample_two_hop(graph, np.array([0]), rng, fanouts=(5, 5))

    assert set(sample.hop1[~sample.hop1_mask].tolist()) == {PAD}


def test_an_underfull_node_is_padded_rather_than_resampled(rng) -> None:
    """Sampling with replacement would weight a two-neighbour item's single edge
    as heavily as a hundred-neighbour item's ten."""
    rows = [view("u1", "a", 0), view("u2", "a", 1)]
    graph = build_graph(FeatureBuilder().build(rows, [Product(external_id="a")]))

    sample = sample_two_hop(graph, np.array([0]), rng, fanouts=(6, 6))
    present = sample.hop1[0][sample.hop1_mask[0]]

    assert present.size == 2
    assert len(set(present.tolist())) == 2, "distinct — no replacement"


def test_recency_keeps_the_most_recent_edges(rng) -> None:
    rows = [view(f"u{i}", "a", i) for i in range(10)]
    dataset = FeatureBuilder().build(rows, [Product(external_id="a")])
    graph = build_graph(dataset)

    sample = sample_two_hop(
        graph, np.array([0]), rng, fanouts=(3, 3), strategy=SamplingStrategy.RECENT
    )
    kept = {dataset.user_refs[u] for u in sample.hop1[0][sample.hop1_mask[0]].tolist()}

    assert kept == {"u7", "u8", "u9"}


def test_the_seed_is_reachable_from_itself_in_two_hops(rng) -> None:
    """A self-loop with the same standing as any other neighbour — otherwise a
    one-user item's aggregate is empty."""
    rows = [view("u1", "a", 0)]
    graph = build_graph(FeatureBuilder().build(rows, [Product(external_id="a")]))

    sample = sample_two_hop(graph, np.array([0]), rng, fanouts=(3, 3))

    assert 0 in sample.hop2[0][sample.hop2_mask[0]].tolist()


def test_uniform_sampling_is_reproducible_under_the_same_seed(graph) -> None:
    seeds = np.arange(8, dtype=np.int64)

    first = sample_two_hop(
        graph, seeds, np.random.default_rng(7), fanouts=(4, 4), strategy=SamplingStrategy.UNIFORM
    )
    second = sample_two_hop(
        graph, seeds, np.random.default_rng(7), fanouts=(4, 4), strategy=SamplingStrategy.UNIFORM
    )

    assert np.array_equal(first.hop1, second.hop1)
    assert np.array_equal(first.hop2, second.hop2)


def test_uniform_sampling_does_not_touch_the_global_numpy_state(graph) -> None:
    """There is no module-level RNG and no `np.random.*` call; a seeded run has
    to reproduce its samples regardless of what else drew before it."""
    np.random.seed(0)
    before = np.random.get_state()[2]

    sample_two_hop(
        graph,
        np.arange(4, dtype=np.int64),
        np.random.default_rng(1),
        strategy=SamplingStrategy.UNIFORM,
    )

    assert np.random.get_state()[2] == before


def test_every_sampled_index_is_a_real_node(graph, rng) -> None:
    sample = sample_two_hop(graph, np.arange(graph.n_items, dtype=np.int64), rng, fanouts=(6, 6))

    assert sample.hop1[sample.hop1_mask].max() < graph.n_users
    assert sample.hop2[sample.hop2_mask].max() < graph.n_items
    assert sample.hop1[sample.hop1_mask].min() >= 0
