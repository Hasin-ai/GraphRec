"""The four-stage funnel, and why every stage is a pure function.

Retrieve, filter, order, truncate. Each stage takes a list and returns a list;
none of them touches the database or the clock. That is not stylistic — ER-NF-06
requires the same request to produce the same answer, and a stage that read
`now()` would make "deterministic" mean "deterministic within a second".

**Ordering is a versioned policy, shipped in the bundle.** XR-NF-02: the weights
that turn a model score into a rank are part of the artifact, not part of the
serving process, so a tenant reading `ordering_policy_version` on a response can
tell a re-ranking change from a model change. `OrderingPolicy.DEFAULT` is what a
bundle written before the field existed loads as, which is deliberately the
identity-ish policy: no diversity cap, no freshness weight, ties by item ref.

**Ties are broken by product identifier, always.** Two items with the same final
score must not swap places between two identical requests, and float scores tie
more often than intuition suggests — a cold-start lane scoring by popularity
count produces exact ties constantly. `_sort_key` therefore ends in the item
ref, and the sort is `sorted`, which is stable, over a key that is already
total. Determinism here is a property of the key, not of the sort.

**Filtering happens before ordering and truncation happens after.** Excluding
after truncation would return fewer than `top_n` items for a caller who excluded
one; diversity capping after truncation would return fewer still. The order of
the stages *is* the contract.

**The funnel never sees a tenant id.** It is handed candidates that a caller
already resolved within one tenant, and it returns a subset of them. There is no
path through this module by which another tenant's product could enter, because
nothing here can fetch anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from graphrec.serving.states import CandidateSource

#: The policy shape this code understands. A bundle declaring a higher version
#: is refused rather than read with the fields this version happens to know —
#: see `OrderingPolicy.from_dict`.
POLICY_VERSION = 1

#: The default cap on items from one category, as a fraction of `top_n`. `1.0`
#: means "no cap": a catalogue with three categories and a top_n of 10 would be
#: mutilated by an aggressive default, and a tenant who wants diversity can ask
#: for it in the policy their bundle ships.
DEFAULT_CATEGORY_SHARE = 1.0


@dataclass(frozen=True, slots=True)
class ScoredItem:
    """One candidate on its way through the funnel.

    `score` is what produced it — a model dot product, a popularity count, a
    session co-occurrence. `final_score` is what ordered it, and the two are
    different numbers whenever the policy weights anything, which is why both
    are stored on `recommendation_results`.
    """

    item_ref: str
    score: float
    source: CandidateSource
    #: Used by the diversity cap. `None` when the product has no category, which
    #: is a real state in a catalogue and must not be a group of its own — see
    #: `_apply_diversity`.
    category: str | None = None
    #: Higher is newer, and the policy's `freshness_weight` multiplies it. A
    #: rank rather than a timestamp, so the funnel stays clock-free.
    freshness: float = 0.0
    final_score: float = 0.0


@dataclass(frozen=True, slots=True)
class OrderingPolicy:
    """The versioned re-ranking rule (XR-NF-02).

    Three knobs and a version. Deliberately small: every knob here is a number a
    tenant may one day see on `/models/:versionId`, and a policy with twenty
    fields is a policy nobody can attribute a change to.
    """

    version: int = POLICY_VERSION
    #: Multiplies `freshness`. Zero by default — a bundle that wants recency to
    #: matter says so, and one that says nothing gets pure model order.
    freshness_weight: float = 0.0
    #: The largest share of the returned list one category may occupy.
    category_share: float = DEFAULT_CATEGORY_SHARE
    #: Per-source multipliers, for a blend that trusts the graph more than
    #: popularity. Absent source means 1.0.
    source_weights: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def default(cls) -> OrderingPolicy:
        return cls()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> OrderingPolicy:
        """Read a policy out of a bundle's `notes`, or fall back to the default.

        A *higher* version is a refusal, not a best-effort read. The point of
        versioning the policy is that a change to it is attributable; a process
        that read version 2's fields as though they were version 1's would
        produce a different ranking under the same version number, which is the
        one outcome the version exists to prevent.
        """
        if not raw:
            return cls.default()
        version = int(raw.get("version", POLICY_VERSION))
        if version > POLICY_VERSION:
            msg = (
                f"ordering policy version {version} is newer than this build "
                f"understands ({POLICY_VERSION}). Deploy a newer inference image."
            )
            raise ValueError(msg)
        weights = raw.get("source_weights") or {}
        return cls(
            version=version,
            freshness_weight=float(raw.get("freshness_weight", 0.0)),
            category_share=float(raw.get("category_share", DEFAULT_CATEGORY_SHARE)),
            source_weights={str(k): float(v) for k, v in weights.items()},
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "freshness_weight": self.freshness_weight,
            "category_share": self.category_share,
            "source_weights": dict(self.source_weights),
        }


# ------------------------------------------------------------------- stage 1


def merge(*lanes: Iterable[ScoredItem]) -> list[ScoredItem]:
    """Stage 1. Combine lanes, keeping the best-scoring copy of each item.

    Lanes overlap by design — a product can be both a graph neighbour and a
    top seller. The first lane wins on ties rather than the last, so the caller
    passes them in order of trust and the merge does not need to know which
    source is better.
    """
    best: dict[str, ScoredItem] = {}
    for lane in lanes:
        for item in lane:
            existing = best.get(item.item_ref)
            if existing is None or item.score > existing.score:
                best[item.item_ref] = item
    # Sorted by ref, not by score. Ordering is stage 3's job, and a stage that
    # ordered here would make stage 3's stability depend on stage 1's.
    return [best[ref] for ref in sorted(best)]


# ------------------------------------------------------------------- stage 2


def filter_candidates(
    items: Sequence[ScoredItem],
    *,
    eligible: Collection[str] | None = None,
    exclude: Collection[str] = (),
) -> list[ScoredItem]:
    """Stage 2. Drop what may not be shown.

    `eligible` is the catalogue's own verdict — `products.is_eligible`, resolved
    by the caller against *this* tenant. `None` means "the caller did not
    restrict", which is different from an empty collection: an empty one means
    nothing is eligible and the correct answer is no items at all.

    `exclude` is the caller's list. Applied second and independently, because a
    caller excluding an ineligible product should not get a different answer
    from one who did not.
    """
    excluded = frozenset(exclude)
    return [
        item
        for item in items
        if item.item_ref not in excluded and (eligible is None or item.item_ref in eligible)
    ]


# ------------------------------------------------------------------- stage 3


def order(items: Sequence[ScoredItem], policy: OrderingPolicy) -> list[ScoredItem]:
    """Stage 3. Apply the policy and sort into a total order.

    Returns items with `final_score` filled in, which is the number stored on
    `recommendation_results.final_score` and the one that explains the rank.
    """
    weighted = [replace(item, final_score=_final_score(item, policy)) for item in items]
    return sorted(weighted, key=_sort_key)


def _final_score(item: ScoredItem, policy: OrderingPolicy) -> float:
    weight = policy.source_weights.get(item.source.value, 1.0)
    return item.score * weight + item.freshness * policy.freshness_weight


def _sort_key(item: ScoredItem) -> tuple[float, str]:
    """Descending by score, ascending by item ref.

    The negation is what makes one `sorted` call do both directions. The item
    ref is the tie-break ER-NF-06 names, and because refs are unique within a
    merged list the key is total — so the result does not depend on the sort
    being stable, only on the key being right.
    """
    return (-item.final_score, item.item_ref)


# ------------------------------------------------------------------- stage 4


def truncate(
    items: Sequence[ScoredItem], *, top_n: int, policy: OrderingPolicy
) -> list[ScoredItem]:
    """Stage 4. Apply the diversity cap and cut to length.

    The cap is applied while cutting rather than before it: capping first would
    discard items that the cut would have discarded anyway, and could leave the
    response short when a lower-ranked item from a fresh category was available.
    """
    if top_n <= 0:
        return []
    capped = _apply_diversity(items, top_n=top_n, policy=policy)
    return capped[:top_n]


def _apply_diversity(
    items: Sequence[ScoredItem], *, top_n: int, policy: OrderingPolicy
) -> list[ScoredItem]:
    """One pass, in order, skipping items whose category is already full.

    Skipped items are appended afterwards rather than dropped. A cap that
    returned six items when ten were asked for would trade a tenant's page size
    for a diversity property they did not ask for, and the cap is a preference
    while the length is a contract.

    Products without a category are never capped. Grouping them under one key
    would make "uncategorised" the most-capped category in a catalogue that is
    mid-import, which is the worst moment to start withholding results.
    """
    share = policy.category_share
    if share >= 1.0:
        return list(items)
    limit = max(1, int(top_n * share))
    counts: dict[str, int] = {}
    kept: list[ScoredItem] = []
    deferred: list[ScoredItem] = []
    for item in items:
        if item.category is None:
            kept.append(item)
            continue
        seen = counts.get(item.category, 0)
        if seen >= limit:
            deferred.append(item)
            continue
        counts[item.category] = seen + 1
        kept.append(item)
    return kept + deferred


# ------------------------------------------------------------------ the whole


def run(
    lanes: Sequence[Sequence[ScoredItem]],
    *,
    top_n: int,
    policy: OrderingPolicy,
    eligible: Collection[str] | None = None,
    exclude: Collection[str] = (),
) -> list[ScoredItem]:
    """All four stages, in the one order that is the contract.

    A single entry point so no caller can assemble the stages differently. The
    stages stay public because the tests assert on them individually — a
    determinism failure inside `order` is a different bug from one inside
    `truncate`, and a test that could only see the end would not say which.
    """
    merged = merge(*lanes)
    kept = filter_candidates(merged, eligible=eligible, exclude=exclude)
    ordered = order(kept, policy)
    return truncate(ordered, top_n=top_n, policy=policy)


__all__ = [
    "DEFAULT_CATEGORY_SHARE",
    "POLICY_VERSION",
    "OrderingPolicy",
    "ScoredItem",
    "filter_candidates",
    "merge",
    "order",
    "run",
    "truncate",
]
