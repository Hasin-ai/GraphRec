"""Recall@10, HR@10, NDCG@10 and coverage, against numbers computed by hand.

Every expected value in this file was worked out on paper from the definitions
in the module docstring, not read off a run. That is the only way a metric test
is worth anything: a test that asserts what the code currently returns pins a
bug as firmly as it pins a feature, and these are the numbers Phase 10's
eligibility floor will accept or reject a tenant's model on.

`1/log2(3) = 0.630929…` and `1/log2(4) = 0.5` recur below; they are written as
literals so the arithmetic is visible.
"""

from __future__ import annotations

import math

import pytest

from graphrec.ml.eval.metrics import (
    Metrics,
    coverage,
    evaluate_rankings,
    hit_rate_at_k,
    ndcg_at_k,
    recall_at_k,
)

RANKED = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]


# ------------------------------------------------------------------- recall


@pytest.mark.parametrize(
    ("relevant", "expected"),
    [
        ({10}, 1.0),
        ({19}, 1.0),
        ({20}, 0.0),
        ({21}, 0.0),
        ({99}, 0.0),
        ({10, 11}, 1.0),
        ({10, 20}, 0.5),
        ({10, 20, 21}, 1 / 3),
        (set(), 0.0),
    ],
)
def test_recall_at_10(relevant: set[int], expected: float) -> None:
    assert recall_at_k(RANKED, relevant, 10) == pytest.approx(expected)


def test_recall_counts_the_cut_off_at_exactly_k() -> None:
    """Position 10 is in, position 11 is out."""
    assert recall_at_k(RANKED, {19}, 10) == 1.0
    assert recall_at_k(RANKED, {20}, 10) == 0.0
    assert recall_at_k(RANKED, {20}, 11) == 1.0


# ----------------------------------------------------------------- hit rate


@pytest.mark.parametrize(
    ("relevant", "expected"),
    [({10}, 1.0), ({10, 20}, 1.0), ({20, 21}, 0.0), (set(), 0.0)],
)
def test_hit_rate_at_10(relevant: set[int], expected: float) -> None:
    assert hit_rate_at_k(RANKED, relevant, 10) == pytest.approx(expected)


def test_hit_rate_is_binary_where_recall_is_fractional() -> None:
    assert recall_at_k(RANKED, {10, 20}, 10) == 0.5
    assert hit_rate_at_k(RANKED, {10, 20}, 10) == 1.0


# --------------------------------------------------------------------- ndcg


@pytest.mark.parametrize(
    ("relevant", "expected"),
    [
        ({10}, 1.0),
        ({11}, 1 / math.log2(3)),
        ({12}, 1 / math.log2(4)),
        ({19}, 1 / math.log2(11)),
        ({20}, 0.0),
        (set(), 0.0),
    ],
)
def test_ndcg_at_10_for_a_single_relevant_item(relevant: set[int], expected: float) -> None:
    assert ndcg_at_k(RANKED, relevant, 10) == pytest.approx(expected)


def test_ndcg_normalises_by_the_ideal_for_two_relevant_items() -> None:
    """Hits at ranks 1 and 3: DCG = 1 + 1/log2(4) = 1.5. Ideal = 1 + 1/log2(3)
    = 1.630929…, so NDCG = 0.919721…"""
    dcg = 1.0 + 1 / math.log2(4)
    ideal = 1.0 + 1 / math.log2(3)

    assert ndcg_at_k(RANKED, {10, 12}, 10) == pytest.approx(dcg / ideal)


def test_a_perfect_ranking_scores_one() -> None:
    assert ndcg_at_k(RANKED, {10, 11, 12}, 10) == pytest.approx(1.0)


def test_ndcg_rewards_a_higher_position() -> None:
    assert ndcg_at_k(RANKED, {10}, 10) > ndcg_at_k(RANKED, {11}, 10) > ndcg_at_k(RANKED, {12}, 10)


def test_the_ideal_is_capped_at_k() -> None:
    """A user with more relevant items than there are slots must still be able
    to score 1.0, or the metric penalises them for being well served."""
    assert ndcg_at_k(RANKED, set(range(10, 22)), 10) == pytest.approx(1.0)


# ----------------------------------------------------------------- coverage


def test_coverage_is_the_fraction_of_the_catalogue_ever_surfaced() -> None:
    assert coverage([[0, 1], [1, 2]], n_items=10, k=10) == pytest.approx(0.3)


def test_coverage_counts_the_whole_catalogue_including_untouched_items() -> None:
    """The denominator is what a tenant means when they ask what fraction of
    their products the system will ever recommend."""
    assert coverage([[0]], n_items=100, k=10) == pytest.approx(0.01)


def test_coverage_respects_the_cut_off() -> None:
    assert coverage([[0, 1, 2, 3]], n_items=4, k=2) == pytest.approx(0.5)


def test_coverage_of_an_empty_catalogue_is_zero_not_an_error() -> None:
    assert coverage([[0]], n_items=0) == 0.0


def test_one_list_for_everybody_scores_terribly_on_coverage() -> None:
    """The failure accuracy alone cannot see: a model that recommends the same
    ten products to every user."""
    identical = [[0, 1, 2] for _ in range(50)]

    assert coverage(identical, n_items=300, k=10) == pytest.approx(0.01)


# ---------------------------------------------------------------- aggregate


def test_the_aggregate_is_macro_averaged() -> None:
    """Each user counts once. A micro average would let the ten most active
    users decide whether a model version is eligible."""
    metrics = evaluate_rankings([[1, 2], [3, 4]], [{1}, {9}], n_items=10, k=2)

    assert metrics.recall == pytest.approx(0.5)
    assert metrics.hit_rate == pytest.approx(0.5)
    assert metrics.ndcg == pytest.approx(0.5)
    assert metrics.n_users == 2


def test_recall_equals_hit_rate_under_leave_one_out(split, dataset) -> None:
    """Stated rather than hidden: with exactly one relevant item per user the
    two are the same number by definition."""
    rankings = [[row.item] for row in split.test]
    metrics = evaluate_rankings(
        rankings, [{row.item} for row in split.test], n_items=dataset.n_items
    )

    assert metrics.recall == metrics.hit_rate == 1.0


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="2 ranked lists against 1 relevant sets"):
        evaluate_rankings([[1], [2]], [{1}], n_items=5)


def test_an_empty_evaluation_reports_zero_users() -> None:
    metrics = evaluate_rankings([], [], n_items=5)

    assert metrics.n_users == 0
    assert metrics.recall == 0.0


def test_beats_requires_winning_on_both_accuracy_metrics() -> None:
    """A model that wins on NDCG by reordering the same hits while finding fewer
    of them has not beaten the baseline."""
    baseline = Metrics(k=10, n_users=100, recall=0.20, hit_rate=0.20, ndcg=0.10, coverage=0.3)
    reordered = Metrics(k=10, n_users=100, recall=0.18, hit_rate=0.18, ndcg=0.15, coverage=0.9)
    better = Metrics(k=10, n_users=100, recall=0.25, hit_rate=0.25, ndcg=0.14, coverage=0.5)

    assert not reordered.beats(baseline)
    assert better.beats(baseline)


def test_the_metric_names_carry_their_cut_off() -> None:
    metrics = Metrics(k=10, n_users=1, recall=0.1, hit_rate=0.1, ndcg=0.05, coverage=0.4)

    assert set(metrics.as_dict()) == {
        "recall_at_10",
        "hit_rate_at_10",
        "ndcg_at_10",
        "coverage",
    }
