"""The popularity baseline — the thing the model has to beat, and its own rules.

The baseline has to be *good*, not a straw man: it gets the same protocol, the
same history exclusion and the same full-catalogue ranking the model gets. What
it must never get is the held-out row, and that is the first test here.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from graphrec.common.enums import EventType
from graphrec.ml.eval.baseline import PopularityRanker, evaluate_popularity
from graphrec.ml.eval.split import leave_last_out
from graphrec.ml.features.builder import FeatureBuilder, Interaction, Product

BASE = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)


def view(user: str, item: str, hours: int) -> Interaction:
    return Interaction(
        user_ref=user,
        item_ref=item,
        event_type=EventType.VIEW,
        occurred_at=BASE + dt.timedelta(hours=hours),
    )


def test_the_baseline_is_fitted_on_training_rows_only(dataset, split) -> None:
    """Counting the held-out interaction would let the baseline predict the
    answer from the answer."""
    full = PopularityRanker().fit(dataset)
    trained = PopularityRanker().fit(split.train)

    assert int(full.counts.sum()) == dataset.n_interactions
    assert int(trained.counts.sum()) == split.train.n_interactions
    assert int(trained.counts.sum()) < int(full.counts.sum())


def test_ranking_is_by_descending_count() -> None:
    rows = [view("u1", "a", 0), view("u2", "a", 1), view("u3", "b", 2), view("u4", "c", 3)]
    dataset = FeatureBuilder().build(rows, [Product(external_id=x) for x in "abc"])
    ranker = PopularityRanker().fit(dataset)

    assert [dataset.item_refs[i] for i in ranker.rank(k=3)] == ["a", "b", "c"]


def test_ties_are_broken_by_item_index_and_not_by_argsort_internals() -> None:
    """A catalogue's long tail is mostly ties at one interaction; leaving their
    order to `argsort` would make coverage differ between numpy builds."""
    rows = [view("u1", ref, n) for n, ref in enumerate("abcd")]
    dataset = FeatureBuilder().build(rows, [Product(external_id=x) for x in "abcd"])
    ranker = PopularityRanker().fit(dataset)

    assert ranker.rank(k=4) == [0, 1, 2, 3]


def test_the_user_s_history_is_excluded() -> None:
    """Without it the baseline recommends the bestseller to a user who bought it
    yesterday — and scores better than it deserves on exactly the users who make
    the comparison interesting."""
    rows = [view("u1", "a", 0), view("u2", "a", 1), view("u3", "b", 2)]
    dataset = FeatureBuilder().build(rows, [Product(external_id=x) for x in "ab"])
    ranker = PopularityRanker().fit(dataset)

    assert ranker.rank(exclude=[0], k=2) == [1]


def test_an_unfitted_ranker_refuses_to_rank() -> None:
    with pytest.raises(RuntimeError, match="fit has not been called"):
        PopularityRanker().rank()


def test_the_baseline_scores_something_on_the_fixture(split) -> None:
    """A baseline that scores zero is not a baseline; it means the protocol is
    broken rather than that popularity is useless."""
    metrics = evaluate_popularity(split.train, split.test)

    assert metrics.n_users == len(split.test)
    assert 0.0 < metrics.recall < 1.0
    assert metrics.recall == metrics.hit_rate


def test_the_baseline_has_poor_coverage_by_construction(split) -> None:
    """It offers every user the same head of the catalogue, so its coverage is
    bounded by roughly K over the catalogue size."""
    metrics = evaluate_popularity(split.train, split.test)

    assert metrics.coverage < 0.35


def test_the_same_split_gives_the_same_baseline_twice(split) -> None:
    first = evaluate_popularity(split.train, split.test)
    second = evaluate_popularity(split.train, split.test)

    assert first == second


def test_a_cold_item_is_reachable_in_the_ordering() -> None:
    """It ranks last, but it ranks — an item that cannot appear in any ordering
    cannot be recommended by anything downstream either."""
    rows = [view("u1", "hot", 0)]
    dataset = FeatureBuilder().build(
        rows, [Product(external_id="hot"), Product(external_id="cold")]
    )
    ranker = PopularityRanker().fit(dataset)

    assert set(ranker.rank(k=2)) == {0, 1}
    assert np.count_nonzero(ranker.counts) == 1


def test_a_user_whose_history_covers_the_catalogue_gets_a_short_list() -> None:
    """Truncated rather than padded with items they have already seen."""
    rows = [view("u1", ref, n) for n, ref in enumerate("abc")]
    dataset = FeatureBuilder().build(rows, [Product(external_id=x) for x in "abc"])
    ranker = PopularityRanker().fit(dataset)

    assert ranker.rank(exclude=[0, 1], k=10) == [2]


def test_the_split_the_baseline_is_scored_on_has_no_leakage(split) -> None:
    split.assert_no_leakage()
    assert leave_last_out(split.train).test != []
