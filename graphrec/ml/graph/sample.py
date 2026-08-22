"""Bounded 2-hop neighbourhood sampling.

The whole reason a sampler exists is degree skew. A tenant's catalogue has a
bestseller that a hundred thousand people touched, and full-neighbourhood
aggregation over it is a single node deciding both the memory ceiling and the
step time for the entire batch. Bounding the fan-out per hop turns an unbounded
graph into a fixed-shape tensor, which is what makes the step cost predictable
and the GNN pathway implementable as three dense operations instead of a
scatter over ragged lists.

**The shape is the contract.** A sample of `n` seeds with fan-outs `(f1, f2)` is
always `(n, f1)` and `(n, f1, f2)`, padded with `-1` and accompanied by a boolean
mask. Nothing downstream branches on how many neighbours a node happened to
have; it multiplies by the mask. A cold item with no neighbours at all is an
all-false row, and its aggregate is zero rather than a division by zero.

**Sampling is with replacement when a node is under-full? No.** Padding is used
instead, because sampling with replacement would weight a two-neighbour item's
single edge as heavily as a hundred-neighbour item's ten, and the model would
learn that sparse items are confidently whatever their one neighbour is.

**Recency bias, not uniformity, is the default.** `graph.build` leaves each
node's edges in ascending time, so the most recent `f` edges are the tail of the
slice. Taking the tail is both the cheapest option and the right one: what a
user did last month predicts what they do tomorrow better than what they did two
years ago. Uniform sampling stays available for evaluation runs that want to
measure the bias's contribution.

**Determinism.** Every random draw goes through a `numpy.random.Generator` the
caller supplies. There is no module-level RNG and no call to `np.random.*`, so a
seeded run reproduces its samples exactly — the Phase 8 exit criterion depends
on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from graphrec.ml.graph.build import InteractionGraph

#: Neighbours kept per hop. Deliberately small: the second hop is the product of
#: both, so `(10, 10)` already means a hundred nodes per seed, and doubling the
#: first fan-out quadruples nothing while doubling the step time.
DEFAULT_FANOUTS: tuple[int, int] = (10, 10)

#: The value a padded slot holds. `-1` and not `0`, because `0` is a real node
#: index and a padding bug that silently aggregates item 0 into every cold
#: item's embedding is exactly the kind of fault that shows up as "the model
#: recommends the same thing to everyone" three phases later.
PAD = -1


class SamplingStrategy(StrEnum):
    """How a node's edges are cut down to the fan-out."""

    #: Keep the most recent `f` edges. The default.
    RECENT = "recent"
    #: Draw `f` without replacement from all edges, using the caller's RNG.
    UNIFORM = "uniform"


@dataclass(frozen=True, slots=True)
class Neighbourhood:
    """A fixed-shape 2-hop sample around a set of seed items.

    Item seeds rather than user seeds because the thing being scored is an item.
    Hop 1 reaches the users who interacted with the seed and hop 2 reaches what
    *those* users also interacted with, which is co-occurrence — the signal that
    lets a newly-listed product inherit a neighbourhood from the two people who
    have seen it.
    """

    seeds: NDArray[np.int64]
    #: `(n_seeds, f1)` user indices, `PAD` where absent.
    hop1: NDArray[np.int64]
    hop1_mask: NDArray[np.bool_]
    #: `(n_seeds, f1, f2)` item indices, `PAD` where absent.
    hop2: NDArray[np.int64]
    hop2_mask: NDArray[np.bool_]

    @property
    def n_seeds(self) -> int:
        return int(self.seeds.size)

    def sizes(self) -> tuple[int, int]:
        """Actual neighbour counts, for the training report's sparsity line."""
        return int(self.hop1_mask.sum()), int(self.hop2_mask.sum())


def sample_two_hop(
    graph: InteractionGraph,
    seeds: NDArray[np.int64],
    rng: np.random.Generator,
    *,
    fanouts: tuple[int, int] = DEFAULT_FANOUTS,
    strategy: SamplingStrategy = SamplingStrategy.RECENT,
) -> Neighbourhood:
    """Sample item → user → item, bounded at each hop.

    Hop 2 deliberately does **not** exclude the seed. An item is trivially
    reachable from itself in two hops — every user who touched it leads back —
    and dropping it would make the aggregate of a one-user item empty. Its own
    contribution is a self-loop with the same standing as any other neighbour,
    which is the usual GNN convention and keeps the masked mean well-defined.
    """
    f1, f2 = fanouts
    seeds = np.asarray(seeds, dtype=np.int64)
    n = int(seeds.size)

    hop1 = np.full((n, f1), PAD, dtype=np.int64)
    hop2 = np.full((n, f1, f2), PAD, dtype=np.int64)

    for row, item in enumerate(seeds):
        users = _pick(graph.users_of(int(item)), f1, rng, strategy)
        hop1[row, : users.size] = users
        for slot, user in enumerate(users):
            items = _pick(graph.items_of(int(user)), f2, rng, strategy)
            hop2[row, slot, : items.size] = items

    return Neighbourhood(
        seeds=seeds,
        hop1=hop1,
        hop1_mask=hop1 != PAD,
        hop2=hop2,
        hop2_mask=hop2 != PAD,
    )


def _pick(
    neighbours: NDArray[np.int64],
    fanout: int,
    rng: np.random.Generator,
    strategy: SamplingStrategy,
) -> NDArray[np.int64]:
    """At most `fanout` neighbours, chosen by strategy. Never padded — the
    caller places what it gets and leaves the rest as `PAD`."""
    if neighbours.size <= fanout:
        return neighbours
    if strategy is SamplingStrategy.RECENT:
        # Edges are stored oldest-first, so the tail is the most recent.
        return neighbours[-fanout:]
    chosen = rng.choice(neighbours.size, size=fanout, replace=False)
    # Sorted so the sample's order is a function of the draw and not of
    # `choice`'s internal ordering, which is not part of numpy's contract.
    return neighbours[np.sort(chosen)]


__all__ = [
    "DEFAULT_FANOUTS",
    "PAD",
    "Neighbourhood",
    "SamplingStrategy",
    "sample_two_hop",
]
