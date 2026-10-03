"""XR-F-04 / XR-NF-02: bounded diversity and freshness re-ranking.

Rules re-order an already eligible, exclusion-filtered candidate pool; they
never add products. Relevance stays dominant and explainable:

* the freshness boost is capped (``weight <= 0.3``): score =
  (1 - w) * relevance + w * freshness, with relevance = 1 - rank/n. A brand-new
  item can therefore gain at most w / (1 - w) (~43% at the cap) of the
  relevance range, so it can pass only candidates in that band, never the top
  of the list from the bottom on age alone;
  Candidates tied on the upstream score share one relevance value;
* the diversity cap is greedy over the relevance order, and if the cap would
  leave the list short it is relaxed in relevance order instead of returning
  fewer items than requested.

Every response that used rules carries the policy ``version`` it applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RuleSet:
    version: int
    diversity_enabled: bool
    max_per_category: int
    freshness_enabled: bool
    freshness_weight: float
    freshness_half_life_days: int

    @property
    def active(self) -> bool:
        return self.diversity_enabled or (self.freshness_enabled and self.freshness_weight > 0)

    def applied(self) -> list[str]:
        out = []
        if self.freshness_enabled and self.freshness_weight > 0:
            out.append("freshness")
        if self.diversity_enabled:
            out.append("diversity")
        return out


MAX_FRESHNESS_WEIGHT = 0.3


def rerank(candidates: Sequence[str], meta: Mapping[str, tuple[str | None, datetime]], rules: RuleSet,
           *, top_n: int, now: datetime, scores: Mapping[str, float] | None = None) -> list[str]:
    """Re-rank ``candidates`` (best first).

    ``scores`` optionally carries the upstream relevance signal (e.g. popularity
    counts). Candidates with equal scores share the relevance of the first of
    their tie group, so an arbitrary tie-break (external id) is never mistaken
    for a relevance difference that freshness cannot overcome.
    """
    ids = [c for c in dict.fromkeys(candidates) if c in meta]
    if not ids:
        return []
    n = len(ids)
    rank_of: dict[str, int] = {}
    group_start, previous = 0, object()
    for index, item in enumerate(ids):
        current = scores.get(item) if scores is not None else object()
        if scores is None or current != previous:
            group_start, previous = index, current
        rank_of[item] = group_start
    weight = min(max(rules.freshness_weight, 0.0), MAX_FRESHNESS_WEIGHT) if rules.freshness_enabled else 0.0
    half_life = max(rules.freshness_half_life_days, 1)
    scored = []
    for index, item in enumerate(ids):
        relevance = 1.0 - rank_of[item] / n
        score = relevance
        if weight:
            age_days = max((now - meta[item][1]).total_seconds() / 86_400, 0.0)
            freshness = 0.5 ** (age_days / half_life)
            score = (1 - weight) * relevance + weight * freshness
        scored.append((-score, index, item))
    ordered = [item for _, _, item in sorted(scored)]
    if not rules.diversity_enabled:
        return ordered[:top_n]
    cap = max(rules.max_per_category, 1)
    picked, deferred, counts = [], [], {}
    for item in ordered:
        category = meta[item][0]
        if category is None or counts.get(category, 0) < cap:
            picked.append(item)
            if category is not None:
                counts[category] = counts.get(category, 0) + 1
            if len(picked) == top_n:
                return picked
        else:
            deferred.append(item)
    return (picked + deferred)[:top_n]


def category_spread(items: Sequence[str], meta: Mapping[str, tuple[str | None, datetime]]) -> int:
    return len({meta[i][0] for i in items if i in meta and meta[i][0] is not None})
