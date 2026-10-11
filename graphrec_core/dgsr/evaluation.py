"""XR-F-10: compare model versions on one common evaluation set.

Each training job evaluates its candidate on its own chronological split, so two
versions' stored metrics are not comparable. Here the candidate's held-out test
examples are written out in *external* identifiers (shopper id, prefix history,
target product) and every compared version — the candidate, the version active at
the time, and a popularity baseline — is scored on exactly those examples through
the same serving path (``encode_history``) the API uses.

A version that does not know an example's target cannot rank it: that example
counts as a miss for that version (reported as ``unknown_targets``) rather than
being dropped, so every version is measured over the same denominator.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from graphrec_core.dgsr.serving import DGSRArtifact, HistoryEvent

PROTOCOL = ("Common set: the candidate's chronological held-out test examples in external ids; "
            "full catalog; observed prefix excluded; each version scored through its serving encoder; "
            "an unknown target counts as a miss.")
MAX_EXAMPLES = 500


@dataclass(frozen=True)
class CommonExample:
    user: str
    history: tuple[tuple[str, int], ...]   # (external product id, unix seconds), chronological
    target: str

    def as_dict(self) -> dict[str, Any]:
        return {"user": self.user, "history": [list(h) for h in self.history], "target": self.target}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CommonExample":
        return cls(str(raw["user"]), tuple((str(i), int(t)) for i, t in raw["history"]), str(raw["target"]))


def common_set_from_split(data, split_examples: Sequence, limit: int = MAX_EXAMPLES) -> list[CommonExample]:
    """Translate a training split (internal indices) into external-id examples."""
    out = []
    for example in list(split_examples)[:limit]:
        events = data.by_user[example.user]
        events = events[:np.searchsorted(events, example.cutoff, side="right")]
        history = tuple((data.item_ids[int(data.items[e])], int(data.times[e])) for e in events)
        if history:
            out.append(CommonExample(data.user_ids[example.user], history, data.item_ids[example.target]))
    return out


def _summary(ranks: list[int | None], recommended: set[str], catalog: int, unknown: int) -> dict[str, Any]:
    n = len(ranks)
    hit = lambda k: float(np.mean([r is not None and r <= k for r in ranks])) if n else 0.0  # noqa: E731
    return {
        "examples": n,
        "Hit@1": hit(1),
        "Hit@10": hit(10),
        "NDCG@10": float(np.mean([1 / math.log2(r + 1) if r is not None and r <= 10 else 0 for r in ranks])) if n else 0.0,
        "MRR@10": float(np.mean([1 / r if r is not None and r <= 10 else 0 for r in ranks])) if n else 0.0,
        "catalog_coverage@10": len(recommended) / catalog if catalog else 0.0,
        "unknown_targets": unknown,
    }


def evaluate_artifact(artifact: DGSRArtifact, examples: Iterable[CommonExample]) -> dict[str, Any]:
    ranks: list[int | None] = []
    recommended: set[str] = set()
    unknown = 0
    for example in examples:
        target = artifact.item_index(example.target)
        history = [HistoryEvent(i, t) for i, t in ((artifact.item_index(x), t) for x, t in example.history) if i is not None]
        if target is None or not history:
            unknown += target is None
            ranks.append(None)
            continue
        encoded = artifact.encode_history(history, artifact.user_index(example.user))
        seen = {h.item for h in history} - {target}
        scores = artifact.score(encoded.query, sorted(seen))
        if not np.isfinite(scores[target]):
            ranks.append(None)
            continue
        order = np.lexsort((np.arange(len(scores)), -scores))
        ranks.append(int(np.flatnonzero(order == target)[0]) + 1)
        recommended.update(artifact.item_ids[int(i)] for i in order[:10] if np.isfinite(scores[i]))
    return _summary(ranks, recommended, len(artifact.item_ids), unknown)


def evaluate_popularity(train_items: Sequence[str], catalog: Sequence[str], examples: Iterable[CommonExample]) -> dict[str, Any]:
    """Most-interacted products in the candidate's training interactions, prefix excluded."""
    counts = Counter(train_items)
    ranking = sorted(catalog, key=lambda item: (-counts.get(item, 0), item))
    ranks: list[int | None] = []
    recommended: set[str] = set()
    for example in examples:
        seen = {i for i, _ in example.history} - {example.target}
        order = [i for i in ranking if i not in seen]
        recommended.update(order[:10])
        ranks.append(order.index(example.target) + 1 if example.target in order else None)
    return _summary(ranks, recommended, len(catalog), sum(e.target not in set(catalog) for e in examples))


def compare(candidate: DGSRArtifact, examples: list[CommonExample], train_items: Sequence[str],
            active: DGSRArtifact | None = None, active_version_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "protocol": PROTOCOL,
        "examples": len(examples),
        "candidate": evaluate_artifact(candidate, examples),
        "popularity_baseline": evaluate_popularity(train_items, candidate.item_ids, examples),
        "active": None,
    }
    if active is not None:
        result["active"] = {"model_version_id": active_version_id, **evaluate_artifact(active, examples)}
        result["ndcg10_delta_vs_active"] = result["candidate"]["NDCG@10"] - result["active"]["NDCG@10"]
    return result
