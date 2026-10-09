"""Pure ranking helpers for the serving pipeline (no I/O, unit-testable).

Every function is deterministic: equal inputs give equal outputs, and ties are
broken by external product ID so a demo run can be repeated exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

#: Retrieval sources in priority order (used for the per-item ``reason``).
SOURCES = ("session_neighbors", "dgsr_personalized", "popular_in_category", "trending", "last_good")

#: final = w_model * model + w_popularity * popularity + w_agreement * agreement
#: (chosen by scripts/eval_serving.py on the MovieLens artifact: 2,000 held-out users)
WEIGHTS = {"model": 0.85, "popularity": 0.05, "agreement": 0.10}

#: Candidate quotas per retrieval source.
QUOTA_PERSONALIZED = 100
QUOTA_NEIGHBORS = 60
QUOTA_CATEGORY = 40
QUOTA_TRENDING = 40
#: Most recent distinct viewed items used as neighbor anchors.
NEIGHBOR_ANCHORS = 3
#: Default MMR diversity (0 = pure relevance, 1 = pure novelty).
DEFAULT_DIVERSITY = 0.25

#: Candidates found by this many independent sources get the full agreement bonus.
AGREEMENT_FULL = 3


@dataclass
class Candidate:
    external_id: str
    sources: list[str] = field(default_factory=list)
    #: 1-based rank inside each source that returned the item.
    source_ranks: dict[str, int] = field(default_factory=dict)
    #: The recently viewed item that pulled this one in (session_neighbors).
    anchor_id: str | None = None
    category: str | None = None
    item_index: int | None = None
    model_score: float | None = None
    popularity: float = 0.0
    model_norm: float = 0.0
    popularity_norm: float = 0.0
    agreement: float = 0.0
    final: float = 0.0
    rank_before_rerank: int | None = None

    def add_source(self, source: str, rank: int, anchor: str | None = None) -> None:
        if source not in self.sources:
            self.sources.append(source)
            self.source_ranks[source] = rank
        if anchor is not None and self.anchor_id is None:
            self.anchor_id = anchor


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Map each value to its percentile in [0, 1] (ties share the same value).

    The highest value maps to 1.0. A single value maps to 1.0. Using percentiles
    lets DOT-product scores and popularity counts be blended without one
    magnitude dominating the other.
    """
    if not values:
        return {}
    distinct = sorted(set(values.values()))
    if len(distinct) == 1:
        return {key: 1.0 for key in values}
    position = {value: index / (len(distinct) - 1) for index, value in enumerate(distinct)}
    return {key: position[value] for key, value in values.items()}


def combine_scores(candidates: Sequence[Candidate], weights: Mapping[str, float] = WEIGHTS) -> None:
    """Fill ``model_norm``, ``popularity_norm``, ``agreement`` and ``final`` in place.

    Items the model knows are ranked by their exact DGSR score. Items it does
    not know (new catalogue entries) get a conservative model score: half of
    their popularity percentile, which keeps them below the median personal
    candidate while still letting a very popular new item appear.
    """
    model = percentile_ranks({c.external_id: c.model_score for c in candidates if c.model_score is not None})
    popularity = percentile_ranks({c.external_id: c.popularity for c in candidates})
    has_popularity = any(c.popularity for c in candidates)
    for c in candidates:
        c.popularity_norm = popularity.get(c.external_id, 0.0) if has_popularity else 0.0
        c.model_norm = model[c.external_id] if c.external_id in model else 0.5 * c.popularity_norm
        independent = [s for s in c.sources if s != "last_good"]
        c.agreement = min(max(len(independent) - 1, 0) / (AGREEMENT_FULL - 1), 1.0)
        c.final = (
            weights["model"] * c.model_norm
            + weights["popularity"] * c.popularity_norm
            + weights["agreement"] * c.agreement
        )


def relevance_order(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Best first by ``final``; ties broken by external ID."""
    ordered = sorted(candidates, key=lambda c: (-c.final, c.external_id))
    for index, c in enumerate(ordered, start=1):
        c.rank_before_rerank = index
    return ordered


def mmr_order(
    ordered: Sequence[Candidate],
    vectors: Mapping[str, np.ndarray],
    *,
    diversity: float,
    limit: int,
) -> list[Candidate]:
    """Maximal Marginal Relevance over a relevance-ordered list.

    ``score = (1 - diversity) * relevance - diversity * max_sim(item, picked)``
    with cosine similarity of item embeddings. Items without a vector have zero
    similarity to everything. ``diversity = 0`` returns the relevance order.
    """
    pool = list(ordered)
    if diversity <= 0 or len(pool) <= 1:
        return pool[:limit]
    diversity = min(diversity, 1.0)
    first = next((np.asarray(v) for v in vectors.values() if v is not None), None)
    if first is None:
        return pool[:limit]
    n, dim = len(pool), first.shape[-1]
    unit = np.zeros((n, dim), dtype=np.float32)
    for index, c in enumerate(pool):
        v = vectors.get(c.external_id)
        if v is not None:
            norm = float(np.linalg.norm(v))
            if norm > 0:
                unit[index] = np.asarray(v, dtype=np.float32) / norm
    relevance = np.array([c.final for c in pool], dtype=np.float64)
    max_sim = np.zeros(n, dtype=np.float64)
    available = np.ones(n, dtype=bool)
    picked: list[Candidate] = []
    for _ in range(min(limit, n)):
        score = (1 - diversity) * relevance - diversity * max_sim
        score[~available] = -np.inf
        best = int(np.argmax(score))          # first maximum = earliest in relevance order
        picked.append(pool[best])
        available[best] = False
        max_sim = np.maximum(max_sim, unit @ unit[best])
    return picked


def primary_reason(c: Candidate) -> str:
    """Human-meaningful reason code for the storefront badge."""
    if "session_neighbors" in c.sources and c.anchor_id:
        return "because_you_viewed"
    if "dgsr_personalized" in c.sources:
        return "picked_for_you"
    if "popular_in_category" in c.sources:
        return "popular_in_category"
    if "trending" in c.sources:
        return "trending"
    return "recently_recommended"


def primary_source(c: Candidate) -> str:
    for source in SOURCES:
        if source in c.sources:
            return source
    return "unknown"
