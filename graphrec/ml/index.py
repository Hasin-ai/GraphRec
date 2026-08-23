"""The candidate index: a port, and the exact top-K adapter behind it (ADR 0026).

Retrieval is one matrix multiply. Dot-product scoring means a model version *is*
its item matrix (ADR 0023), so the "index" is that matrix held in memory and the
"search" is `matrix @ query` followed by a partial sort. At ASM-02's scale — a
50,000 by 128 float32 matrix is 25 MB — that is exact, single-digit milliseconds,
and has no service to operate.

**The port exists so that stays true only for as long as it is true.** SRS §6.3
specifies a Qdrant contract; ADR 0026 reads it as an *isolation* contract rather
than a product requirement and implements the isolation here. When a catalogue
outgrows one process, the ANN adapter's obligation is to approach what this
adapter already does, and this one becomes the oracle its tests compare against.

**Isolation is the key, not a filter.** §6.3's mandatory `tenant_id` payload
filter exists because a shared collection can be queried without one. Here an
index is keyed by `(tenant_id, model_version_id)` and there is no shared
collection to forget to filter: a search issued with the wrong tenant does not
return the wrong rows, it finds no index at all. The bundle's manifest is
checked before the matrix is admitted (`graphrec.ml.bundle`), so the key and the
bytes agree about whose they are.

**Ordering is deterministic and total.** Two items with the same score are
returned in catalogue order — the order `Dataset.item_refs` was built in — never
in whatever order `argpartition` happened to leave them. Phase 11 requires a
deterministic funnel, and a tie broken differently on two replicas is a
recommendation that changes when a load balancer does.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

from graphrec.common.config import CandidateIndexKind

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection

    from numpy.typing import NDArray

    from graphrec.ml.bundle import Bundle

#: An index is addressed by both, always. A tenant id alone would be ambiguous
#: during an activation, when the previous version is still loaded and serving.
IndexKey = tuple["uuid.UUID", "uuid.UUID"]


class IndexNotLoadedError(LookupError):
    """No index is loaded for that `(tenant, version)`.

    A `LookupError` rather than a `GraphRecError`: the serving path turns it into
    a fallback lane (Phase 11), and a tenant is told a recommendation is
    degraded, not which index was missing.
    """


@dataclass(frozen=True, slots=True)
class Candidate:
    """One retrieved item and the score that retrieved it.

    `item_ref` is the tenant's own external product identifier, because that is
    the only identifier that survives a catalogue rebuild and the only one the
    API may return (`Dataset.item_refs`).
    """

    item_ref: str
    score: float


@runtime_checkable
class CandidateIndex(Protocol):
    """Build it from a bundle, search it, drop it when the version is archived."""

    def build(self, bundle: Bundle) -> None:
        """Make `bundle`'s matrix searchable. Idempotent: building the same
        version twice replaces it, because a reload after a restart is the
        normal case rather than an error."""
        ...

    def search(
        self,
        key: IndexKey,
        query: NDArray[np.float32],
        *,
        top_k: int,
        exclude: Collection[str] = (),
    ) -> list[Candidate]: ...

    def vectors(self, key: IndexKey, item_refs: Collection[str]) -> NDArray[np.float32]:
        """The embedding rows for `item_refs`, in the order given.

        Unknown refs are skipped rather than zero-filled, so the result can be
        shorter than the input and can be empty. A zero row would be a vector
        that contributes nothing to a mean while still counting in the divisor,
        which is a silent way to make a query weaker the more unknown items the
        caller sent.

        The port exposes rows and not a query vector on purpose: *how* a history
        becomes a query is a modelling decision, and it belongs in
        `graphrec.domain.serving.recommend` where it can be read beside the
        strategy it produces — not inside an adapter that would then have to be
        reimplemented identically for Qdrant.
        """
        ...

    def drop(self, key: IndexKey) -> None:
        """Forget an index. Absent is not an error — archive may run twice, and
        a cleanup that fails because it already succeeded is a cleanup that
        blocks."""
        ...

    def loaded(self) -> frozenset[IndexKey]:
        """What is resident. The reconciler reports this; a test asserts on it."""
        ...


@dataclass(frozen=True, slots=True)
class _Resident:
    """`(n_items, dim)` float32, and the labels aligned with its rows."""

    matrix: NDArray[np.float32]
    item_refs: list[str]
    positions: dict[str, int]


class InProcessIndex:
    """Exact top-K over an in-memory matrix.

    Guarded by a lock because an inference process serves requests on several
    threads while the reconciler may be loading the next version underneath
    them. The lock is held for the dictionary lookup, not for the multiply: a
    resident index is immutable once built, so a search that has taken its
    reference can be overtaken by an activation without either of them being
    wrong — the in-flight request finishes against the version it started on.
    """

    def __init__(self) -> None:
        self._indexes: dict[IndexKey, _Resident] = {}
        self._lock = threading.Lock()

    def build(self, bundle: Bundle) -> None:
        manifest = bundle.manifest
        matrix = np.ascontiguousarray(bundle.item_embeddings, dtype=np.float32)
        resident = _Resident(
            matrix=matrix,
            item_refs=list(manifest.item_refs),
            # Built once here rather than per search. The exclusion list in a
            # recommendation request is up to 200 items (NR-NF-04's budget does
            # not survive 200 linear scans of a 50,000-entry list).
            positions={ref: row for row, ref in enumerate(manifest.item_refs)},
        )
        with self._lock:
            self._indexes[(manifest.tenant_id, manifest.model_version_id)] = resident

    def search(
        self,
        key: IndexKey,
        query: NDArray[np.float32],
        *,
        top_k: int,
        exclude: Collection[str] = (),
    ) -> list[Candidate]:
        """The true top-K by dot product, minus anything excluded.

        Exclusion is applied *before* the sort by driving the excluded rows to
        `-inf`, not after by trimming the result. Trimming afterwards returns
        fewer than `top_k` items whenever an excluded item scored well, which is
        precisely when a tenant asked for it to be excluded.
        """
        resident = self._resident(key)
        if top_k <= 0:
            return []

        vector = np.ascontiguousarray(query, dtype=np.float32).reshape(-1)
        if vector.shape[0] != resident.matrix.shape[1]:
            msg = (
                f"query has {vector.shape[0]} dimensions, " f"index has {resident.matrix.shape[1]}"
            )
            raise ValueError(msg)

        scores = resident.matrix @ vector
        if exclude:
            rows = [
                position
                for position in (resident.positions.get(ref) for ref in exclude)
                if position is not None
            ]
            if rows:
                # A copy, because the scores array is derived per search but the
                # matrix behind it is shared and must not be written through.
                scores = scores.copy()
                scores[rows] = -np.inf

        wanted = min(top_k, scores.shape[0])
        # `argpartition` is O(n) and leaves the top block unordered; the sort
        # afterwards is over `wanted` elements rather than the whole catalogue.
        # `-scores` with `argsort(kind="stable")` then breaks ties by row index,
        # which is catalogue order — the determinism this module promises.
        block = np.argpartition(-scores, wanted - 1)[:wanted]
        ordered = block[np.argsort(-scores[block], kind="stable")]
        return [
            Candidate(item_ref=resident.item_refs[row], score=float(scores[row]))
            for row in ordered
            if np.isfinite(scores[row])
        ]

    def vectors(self, key: IndexKey, item_refs: Collection[str]) -> NDArray[np.float32]:
        resident = self._resident(key)
        rows = [
            position
            for position in (resident.positions.get(ref) for ref in item_refs)
            if position is not None
        ]
        if not rows:
            # `(0, dim)` rather than `(0,)`: the caller means to stack or
            # average these, and an array with the wrong rank turns "no known
            # items" into a shape error one frame away from where it happened.
            return np.empty((0, resident.matrix.shape[1]), dtype=np.float32)
        return resident.matrix[rows]

    def drop(self, key: IndexKey) -> None:
        with self._lock:
            self._indexes.pop(key, None)

    def loaded(self) -> frozenset[IndexKey]:
        with self._lock:
            return frozenset(self._indexes)

    def _resident(self, key: IndexKey) -> _Resident:
        with self._lock:
            resident = self._indexes.get(key)
        if resident is None:
            # The message names neither tenant nor version. This is the refusal
            # a cross-tenant search lands on, and it must not confirm that some
            # other tenant's version exists.
            msg = "no candidate index is loaded for that model version"
            raise IndexNotLoadedError(msg)
        return resident


def build_candidate_index(kind: CandidateIndexKind) -> CandidateIndex:
    """The adapter D4 selected, or a refusal.

    `qdrant` is a documented setting for an adapter that does not exist (ADR
    0026). The one thing this must not do is fall back to the in-process index
    and carry on: an operator who set `CANDIDATE_INDEX=qdrant` did so because
    they wanted per-collection isolation demonstrated against a real vector
    store, and a process that silently gave them something else would be a
    process whose configuration file is a work of fiction.

    So it fails at construction, which is startup, rather than at the first
    search — the difference between a deployment that does not come up and one
    that comes up wrong.
    """
    if kind is CandidateIndexKind.INPROCESS:
        return InProcessIndex()
    msg = (
        f"candidate_index={kind.value} selects an adapter that is not built. "
        "See ADR 0026: the port exists, the Qdrant implementation is deferred. "
        f"Set candidate_index={CandidateIndexKind.INPROCESS.value}."
    )
    raise NotImplementedError(msg)


def build_index(index: CandidateIndex, bundle: Bundle) -> IndexKey:
    """Build and return the key it was filed under.

    A one-line helper because every caller wants the key back and computing it
    from the manifest at each call site is how a key comes to be spelled two
    ways.
    """
    index.build(bundle)
    return (bundle.manifest.tenant_id, bundle.manifest.model_version_id)


__all__ = [
    "Candidate",
    "CandidateIndex",
    "IndexKey",
    "IndexNotLoadedError",
    "InProcessIndex",
    "build_candidate_index",
    "build_index",
]
