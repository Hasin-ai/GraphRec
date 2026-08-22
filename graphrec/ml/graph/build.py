"""The interaction graph: a bipartite user-item structure in flat arrays.

CON-01 makes this a graph model, so the graph is a real object with an owner
rather than an adjacency dict built inline in the training loop. It is stored in
CSR form — `indptr`/`indices`, the shape scipy would call compressed sparse row —
for two reasons that both matter at the scale a tenant reaches quickly:

* a node's neighbours are one contiguous slice, so sampling is a slice and not a
  dictionary lookup per node, and
* the whole graph is four `int64` arrays plus two `float32` ones, so it can be
  handed to a worker process or written into a checkpoint without pickling a
  graph library's internal state.

Edges carry **time** and **weight**, and both are kept in the same order as
`indices` so a neighbour, its timestamp and its weight are read from the same
offset. The time is what makes recency-biased sampling possible, and the weight
is what makes a purchase count for more than a view when messages are averaged.

**The graph is built from a training `Dataset` and nothing else.** There is no
parameter for "also include the held-out rows", because a graph containing the
test interaction is the single most effective way to leak: the target becomes a
one-hop neighbour of the user it is supposed to be predicted for, and the model
reads the answer off the edge list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from graphrec.ml.features.builder import Dataset


@dataclass(frozen=True, slots=True)
class InteractionGraph:
    """A bipartite graph, stored twice: once per direction.

    Both directions are materialised rather than transposing on demand. A 2-hop
    sample from a user goes user→item→user, so it needs both, and building the
    transpose inside the sampler would rebuild it once per batch.
    """

    n_users: int
    n_items: int

    #: user → items. `user_indptr` has `n_users + 1` entries.
    user_indptr: NDArray[np.int64]
    user_indices: NDArray[np.int64]
    user_times: NDArray[np.float64]
    user_weights: NDArray[np.float32]

    #: item → users. `item_indptr` has `n_items + 1` entries.
    item_indptr: NDArray[np.int64]
    item_indices: NDArray[np.int64]
    item_times: NDArray[np.float64]
    item_weights: NDArray[np.float32]

    @property
    def n_edges(self) -> int:
        """Undirected edges, counted once. Both arrays hold the same set."""
        return int(self.user_indices.size)

    def items_of(self, user: int) -> NDArray[np.int64]:
        start, end = self.user_indptr[user], self.user_indptr[user + 1]
        return self.user_indices[start:end]

    def users_of(self, item: int) -> NDArray[np.int64]:
        start, end = self.item_indptr[item], self.item_indptr[item + 1]
        return self.item_indices[start:end]

    def degree_of_item(self, item: int) -> int:
        return int(self.item_indptr[item + 1] - self.item_indptr[item])

    def isolated_items(self) -> NDArray[np.int64]:
        """Items with no edge at all — the cold-start set.

        Exposed because it is a number a tenant should be told rather than a
        detail of the sampler: a catalogue that is 90% isolated will produce a
        model that recommends 10% of it, and Phase 9's training report says so.
        """
        degrees = np.diff(self.item_indptr)
        return np.flatnonzero(degrees == 0).astype(np.int64)


def build_graph(dataset: Dataset) -> InteractionGraph:
    """Build both directions from a dataset's sequences.

    Duplicate edges are kept, not collapsed. A user who viewed an item eight
    times has eight edges, and that repetition is signal — collapsing it would
    make a browsed-to-death product indistinguishable from one seen once, and
    the degree-based normalisation in the GNN pathway is where it earns its
    keep.
    """
    total = dataset.n_interactions

    src = np.empty(total, dtype=np.int64)
    dst = np.empty(total, dtype=np.int64)
    times = np.empty(total, dtype=np.float64)
    weights = np.empty(total, dtype=np.float32)

    cursor = 0
    for user in range(dataset.n_users):
        seq = dataset.sequences[user]
        for offset, item in enumerate(seq):
            src[cursor] = user
            dst[cursor] = item
            times[cursor] = dataset.timestamps[user][offset].timestamp()
            weights[cursor] = dataset.weights[user][offset]
            cursor += 1

    user_indptr, user_indices, user_times, user_weights = _compress(
        src, dst, times, weights, n_nodes=dataset.n_users
    )
    item_indptr, item_indices, item_times, item_weights = _compress(
        dst, src, times, weights, n_nodes=dataset.n_items
    )

    return InteractionGraph(
        n_users=dataset.n_users,
        n_items=dataset.n_items,
        user_indptr=user_indptr,
        user_indices=user_indices,
        user_times=user_times,
        user_weights=user_weights,
        item_indptr=item_indptr,
        item_indices=item_indices,
        item_times=item_times,
        item_weights=item_weights,
    )


def _compress(
    src: NDArray[np.int64],
    dst: NDArray[np.int64],
    times: NDArray[np.float64],
    weights: NDArray[np.float32],
    *,
    n_nodes: int,
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.float64], NDArray[np.float32]]:
    """Group `dst` by `src` into CSR arrays, oldest edge first within a node.

    The sort is `kind="stable"` and lexicographic on `(src, time)`, so a node's
    neighbours come out in ascending time and ties keep their construction
    order. Recency-biased sampling then reads the tail of a slice, and the
    ordering is reproducible — which is what a seeded run needs to mean
    anything.
    """
    order = np.lexsort((times, src))
    sorted_src = src[order]

    counts = np.bincount(sorted_src, minlength=n_nodes)
    indptr = np.zeros(n_nodes + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])

    return (
        indptr,
        dst[order].astype(np.int64),
        times[order].astype(np.float64),
        weights[order].astype(np.float32),
    )


__all__ = ["InteractionGraph", "build_graph"]
