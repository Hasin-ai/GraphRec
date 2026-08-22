"""The popularity baseline — the number the model has to beat.

Every recommendation system beats random. Very few beat "show everyone the most
popular thing", and a model that does not is a model whose training cost buys
nothing. BUILD_PROMPT makes this the Phase 8 exit criterion for that reason, and
Phase 10 reuses it: a model version that scores below the baseline it was
measured against is `rejected`, not `eligible`.

The baseline is deliberately given every advantage the model gets and no more:
the same evaluation protocol, the same held-out users, the same filtering of
items the user has already interacted with. What it must never be given is the
test rows themselves — `PopularityRanker.fit` takes the *training* dataset, and
counting the held-out interaction would let the baseline predict the answer from
the answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from graphrec.ml.eval.metrics import DEFAULT_K, Metrics, evaluate_rankings

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from numpy.typing import NDArray

    from graphrec.ml.eval.split import HeldOut
    from graphrec.ml.features.builder import Dataset


class PopularityRanker:
    """Rank by training interaction count, ties broken by item index.

    The tie-break is by index and not arbitrary: a catalogue's long tail is
    mostly ties at one interaction, and leaving their order to `argsort`'s
    internals would make the baseline's coverage number differ between numpy
    builds. `np.argsort(kind="stable")` on the negated counts gives descending
    popularity with ascending index inside a tie.
    """

    def __init__(self) -> None:
        self._order: NDArray[np.int64] | None = None
        self._counts: NDArray[np.int64] | None = None

    def fit(self, train: Dataset) -> PopularityRanker:
        counts = train.item_popularity()
        self._counts = counts
        self._order = np.argsort(-counts, kind="stable").astype(np.int64)
        return self

    @property
    def counts(self) -> NDArray[np.int64]:
        if self._counts is None:
            msg = "PopularityRanker.fit has not been called"
            raise RuntimeError(msg)
        return self._counts

    def rank(self, exclude: Collection[int] = (), k: int = DEFAULT_K) -> list[int]:
        """The top K most popular items the user has not already interacted with.

        Exclusion matters more than it looks: without it the baseline recommends
        the same bestseller to a user who bought it yesterday, and — because the
        held-out target is often that bestseller — it would score better than it
        deserves on exactly the users who make the comparison interesting.
        """
        if self._order is None:
            msg = "PopularityRanker.fit has not been called"
            raise RuntimeError(msg)
        blocked = set(exclude)
        out: list[int] = []
        for item in self._order:
            index = int(item)
            if index in blocked:
                continue
            out.append(index)
            if len(out) == k:
                break
        return out


def evaluate_popularity(
    train: Dataset, holdout: Sequence[HeldOut], *, k: int = DEFAULT_K
) -> Metrics:
    """Score the baseline under the same protocol the model is scored under."""
    ranker = PopularityRanker().fit(train)
    rankings = [ranker.rank(exclude=row.history, k=k) for row in holdout]
    relevant: list[Collection[int]] = [{row.item} for row in holdout]
    return evaluate_rankings(rankings, relevant, n_items=train.n_items, k=k)


__all__ = ["PopularityRanker", "evaluate_popularity"]
