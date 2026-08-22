"""Negative sampling: what the model is asked to rank the positive *above*.

The choice of negative decides what the model learns, more than the architecture
does. Two policies are implemented and one is the default.

**Uniform** draws from the catalogue at random. Cheap, unbiased, and almost
useless after the first epoch: a random item is so obviously worse than the
positive that the score difference saturates and the gradient goes to zero.

**Popularity-biased** draws proportionally to a dampened interaction count. This
is the default because it produces the hard cases — the model is repeatedly
asked "why this bestseller and not that one?", which is the actual question at
serving time, where the alternatives on the page are all plausible. The damping
exponent keeps the head from being the only thing ever sampled.

Both **reject items in the user's history**, with a bounded number of retries
rather than a rejection loop. A user who has interacted with most of a small
catalogue would make an unbounded loop hang, and a training step that sometimes
takes forever is worse than one that occasionally trains on a slightly wrong
negative. When the retries run out the draw is accepted; the tests pin the
retry count so the behaviour is a decision and not a surprise.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Collection

    from numpy.typing import NDArray

#: Draws per slot before an in-history item is accepted. Four is enough that a
#: user holding half the catalogue still gets a clean negative ~94% of the time.
MAX_REJECTION_RETRIES = 4

#: Popularity is raised to this power before being normalised. 0.75 is the
#: word2vec subsampling exponent and is used for the same reason: it keeps the
#: head sampled often enough to be informative without letting it be the only
#: thing sampled.
POPULARITY_EXPONENT = 0.75


class NegativePolicy(StrEnum):
    UNIFORM = "uniform"
    POPULARITY = "popularity"


class NegativeSampler:
    """Draws negatives for a batch, deterministically under a seeded generator.

    Holds the sampling distribution rather than recomputing it: the popularity
    vector is a function of the training split and does not change during a run,
    and rebuilding it per batch was measurably the slowest thing in the loop.
    """

    def __init__(
        self,
        n_items: int,
        popularity: NDArray[np.int64] | None = None,
        *,
        policy: NegativePolicy = NegativePolicy.POPULARITY,
    ) -> None:
        self.n_items = n_items
        self.policy = policy
        self._probabilities: NDArray[np.float64] | None = None

        if policy is NegativePolicy.POPULARITY:
            if popularity is None:
                msg = "the popularity policy needs a popularity vector"
                raise ValueError(msg)
            # `+ 1` so an item nobody has touched is still reachable. Without
            # it, a cold item can never appear as a negative, is never pushed
            # down, and drifts to whatever the initialisation left it at — which
            # is how cold items end up ranked randomly high.
            weights = np.power(popularity.astype(np.float64) + 1.0, POPULARITY_EXPONENT)
            self._probabilities = weights / weights.sum()

    def draw(
        self,
        histories: list[Collection[int]],
        rng: np.random.Generator,
        *,
        count: int,
    ) -> NDArray[np.int64]:
        """`(len(histories), count)` item indices."""
        n = len(histories)
        samples = self._raw(n * count, rng).reshape(n, count)

        for row, history in enumerate(histories):
            if not history:
                continue
            blocked = set(history)
            for column in range(count):
                for _ in range(MAX_REJECTION_RETRIES):
                    if int(samples[row, column]) not in blocked:
                        break
                    samples[row, column] = self._raw(1, rng)[0]
        return samples

    def _raw(self, size: int, rng: np.random.Generator) -> NDArray[np.int64]:
        if self._probabilities is None:
            return rng.integers(0, self.n_items, size=size, dtype=np.int64)
        return rng.choice(self.n_items, size=size, p=self._probabilities).astype(np.int64)


__all__ = [
    "MAX_REJECTION_RETRIES",
    "POPULARITY_EXPONENT",
    "NegativePolicy",
    "NegativeSampler",
]
