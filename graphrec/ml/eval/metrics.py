"""Recall@K, HR@K, NDCG@K and catalogue coverage.

Four numbers, each hand-checkable, because a metric nobody can compute by hand
is a metric nobody can dispute — and these are the numbers Phase 10's eligibility
floor will accept or reject a model version on. The tests for this module score
ranked lists written out by hand.

**Recall and hit rate are the same number here, and that is stated rather than
hidden.** With leave-last-out there is exactly one relevant item per user, so
`|relevant ∩ top-K| / |relevant|` is either 0 or 1 and its mean equals the
fraction of users with a hit. Both are reported because the console shows both
and because the functions are written for a general relevant *set*: the day a
session-level evaluation holds out three items, recall stops agreeing with hit
rate and neither function needs changing.

**Coverage is a property of the run, not of a user**, so it takes every ranked
list at once. It answers the question a metric-floor cannot ask of accuracy
alone: a model that recommends the same forty products to everybody can score
respectably and still be useless, and coverage is what makes that visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence

#: The cut-off the console reports and the metric floor is written against.
DEFAULT_K = 10


@dataclass(frozen=True, slots=True)
class Metrics:
    """One evaluation's results.

    `n_users` travels with them because a Recall@10 of 1.0 over four users is
    not a result, and a metric floor applied without the population it was
    measured over is a floor that can be cleared by evaluating almost nothing.
    """

    k: int
    n_users: int
    recall: float
    hit_rate: float
    ndcg: float
    coverage: float

    def beats(self, other: Metrics) -> bool:
        """Strictly better on both accuracy metrics.

        Both, not either: the Phase 8 exit criterion is that the model beats the
        popularity baseline, and a model that wins on NDCG by reordering the
        same hits while finding fewer of them has not.
        """
        return self.recall > other.recall and self.ndcg > other.ndcg

    def as_dict(self) -> dict[str, float]:
        return {
            f"recall_at_{self.k}": self.recall,
            f"hit_rate_at_{self.k}": self.hit_rate,
            f"ndcg_at_{self.k}": self.ndcg,
            "coverage": self.coverage,
        }


def recall_at_k(ranked: Sequence[int], relevant: Collection[int], k: int = DEFAULT_K) -> float:
    """Fraction of the relevant items that appear in the top K.

    Zero when nothing is relevant — not undefined and not one. A user with no
    relevant item contributes no information, and the caller is expected not to
    score them; returning zero rather than raising keeps a stray empty case from
    aborting an evaluation run.
    """
    if not relevant:
        return 0.0
    hits = len(set(ranked[:k]) & set(relevant))
    return hits / len(relevant)


def hit_rate_at_k(ranked: Sequence[int], relevant: Collection[int], k: int = DEFAULT_K) -> float:
    """1.0 if any relevant item is in the top K, else 0.0."""
    return 1.0 if set(ranked[:k]) & set(relevant) else 0.0


def ndcg_at_k(ranked: Sequence[int], relevant: Collection[int], k: int = DEFAULT_K) -> float:
    """Binary-gain NDCG at K.

    Gain is 1 for a relevant item and 0 otherwise; discount is
    `1 / log2(rank + 1)` with rank counted from one, so a hit at position 1
    scores 1.0 and a hit at position 2 scores `1/log2(3) ≈ 0.6309`. The ideal
    DCG is the same sum over the first `min(k, |relevant|)` positions, which is
    what normalises a user with two relevant items against one with a single
    one.
    """
    if not relevant:
        return 0.0
    relevant_set = set(relevant)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(ranked[:k], start=1)
        if item in relevant_set
    )
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant_set)) + 1))
    return dcg / ideal if ideal else 0.0


def coverage(rankings: Iterable[Sequence[int]], n_items: int, k: int = DEFAULT_K) -> float:
    """Fraction of the catalogue that appears in any top-K list.

    Denominator is the whole catalogue, including items nobody has ever
    interacted with, because that is the number a tenant means when they ask
    what fraction of their products the system will ever recommend.
    """
    if n_items <= 0:
        return 0.0
    surfaced: set[int] = set()
    for ranked in rankings:
        surfaced.update(ranked[:k])
    return len(surfaced) / n_items


def evaluate_rankings(
    rankings: Sequence[Sequence[int]],
    relevant: Sequence[Collection[int]],
    *,
    n_items: int,
    k: int = DEFAULT_K,
) -> Metrics:
    """Aggregate per-user metrics into one `Metrics`.

    Macro-averaged — each user counts once regardless of how many interactions
    they have. A micro average would let the ten most active users decide
    whether a model version is eligible.
    """
    if len(rankings) != len(relevant):
        msg = f"{len(rankings)} ranked lists against {len(relevant)} relevant sets"
        raise ValueError(msg)
    if not rankings:
        return Metrics(k=k, n_users=0, recall=0.0, hit_rate=0.0, ndcg=0.0, coverage=0.0)

    n = len(rankings)
    return Metrics(
        k=k,
        n_users=n,
        recall=sum(recall_at_k(r, t, k) for r, t in zip(rankings, relevant, strict=True)) / n,
        hit_rate=sum(hit_rate_at_k(r, t, k) for r, t in zip(rankings, relevant, strict=True)) / n,
        ndcg=sum(ndcg_at_k(r, t, k) for r, t in zip(rankings, relevant, strict=True)) / n,
        coverage=coverage(rankings, n_items, k),
    )


__all__ = [
    "DEFAULT_K",
    "Metrics",
    "coverage",
    "evaluate_rankings",
    "hit_rate_at_k",
    "ndcg_at_k",
    "recall_at_k",
]
