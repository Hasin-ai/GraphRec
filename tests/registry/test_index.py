"""The candidate index: exact, deterministic, and per (tenant, version).

The exactness matters because it is the whole justification for ADR 0026. An
approximate index would need a recall/latency trade-off to tune; this one is
compared against a brute-force top-K computed in the test, and any divergence is
a bug rather than a tuning parameter.

The isolation matters because it is what stands in for SRS §6.3's mandatory
`tenant_id` payload filter. §6.3 requires the filter because a shared collection
can be queried without one; the property this suite asserts is that there is no
shared collection to forget.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from graphrec.ml.bundle import Bundle, BundleManifest, FeatureContract
from graphrec.ml.index import Candidate, IndexNotLoadedError, InProcessIndex, build_index

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _bundle(*, tenant_id=TENANT, matrix=None, refs=None) -> Bundle:
    import datetime as dt

    embeddings = matrix if matrix is not None else np.eye(4, dtype=np.float32)
    item_refs = refs or [f"SKU-{index}" for index in range(embeddings.shape[0])]
    manifest = BundleManifest(
        tenant_id=tenant_id,
        model_version_id=uuid.uuid4(),
        training_job_id=uuid.uuid4(),
        snapshot_id=uuid.uuid4(),
        embedding_dim=int(embeddings.shape[1]),
        item_refs=item_refs,
        feature_contract=FeatureContract(
            feature_builder_version=1, static_feature_dim=3, category_count=2
        ),
        payload_digest="sha256:" + "0" * 64,
        created_at=dt.datetime(2026, 8, 23, tzinfo=dt.UTC),
    )
    return Bundle(manifest=manifest, item_embeddings=np.ascontiguousarray(embeddings))


def test_the_index_returns_the_true_top_k() -> None:
    """Compared against brute force, which is the only claim exactness makes."""
    rng = np.random.default_rng(11)
    matrix = rng.standard_normal((200, 16), dtype=np.float32)
    bundle = _bundle(matrix=matrix, refs=[f"P{index:03d}" for index in range(200)])
    index = InProcessIndex()
    key = build_index(index, bundle)
    query = rng.standard_normal(16, dtype=np.float32)

    found = index.search(key, query, top_k=10)

    scores = matrix @ query
    expected = [f"P{row:03d}" for row in np.argsort(-scores, kind="stable")[:10]]
    assert [candidate.item_ref for candidate in found] == expected


def test_scores_come_back_with_the_candidates() -> None:
    index = InProcessIndex()
    key = build_index(index, _bundle())

    top = index.search(key, np.array([0, 1, 0, 0], dtype=np.float32), top_k=1)

    assert top == [Candidate(item_ref="SKU-1", score=1.0)]


def test_ties_are_broken_in_catalogue_order_on_every_replica() -> None:
    """A tie broken differently on two replicas is a recommendation that changes
    when a load balancer does."""
    matrix = np.ones((5, 3), dtype=np.float32)
    bundle = _bundle(matrix=matrix, refs=["E", "D", "C", "B", "A"])
    index = InProcessIndex()
    key = build_index(index, bundle)

    found = index.search(key, np.ones(3, dtype=np.float32), top_k=5)

    assert [candidate.item_ref for candidate in found] == ["E", "D", "C", "B", "A"]


def test_an_exclusion_is_applied_before_the_cut_not_after_it() -> None:
    """Trimming afterwards returns fewer than `top_k` exactly when an excluded
    item scored well — which is when a tenant asked for it to be excluded."""
    matrix = np.diag(np.arange(5, 0, -1)).astype(np.float32)
    bundle = _bundle(matrix=matrix, refs=list("ABCDE"))
    index = InProcessIndex()
    key = build_index(index, bundle)

    found = index.search(key, np.ones(5, dtype=np.float32), top_k=3, exclude=["A", "B"])

    assert [candidate.item_ref for candidate in found] == ["C", "D", "E"]


def test_an_exclusion_naming_nothing_is_not_an_error() -> None:
    index = InProcessIndex()
    key = build_index(index, _bundle())

    found = index.search(key, np.ones(4, dtype=np.float32), top_k=2, exclude=["not-a-sku"])

    assert len(found) == 2


def test_asking_for_more_than_the_catalogue_holds_returns_the_catalogue() -> None:
    index = InProcessIndex()
    key = build_index(index, _bundle())

    assert len(index.search(key, np.ones(4, dtype=np.float32), top_k=99)) == 4


def test_excluding_everything_returns_nothing_rather_than_negative_infinity() -> None:
    index = InProcessIndex()
    key = build_index(index, _bundle())

    found = index.search(key, np.ones(4, dtype=np.float32), top_k=4, exclude=list("0123"))
    excluded = index.search(
        key, np.ones(4, dtype=np.float32), top_k=4, exclude=[f"SKU-{i}" for i in range(4)]
    )

    assert len(found) == 4
    assert excluded == []


def test_one_tenants_search_cannot_reach_another_tenants_index() -> None:
    """§6.3's isolation contract, honoured by the key rather than by a filter."""
    index = InProcessIndex()
    theirs = build_index(index, _bundle(tenant_id=OTHER_TENANT))

    with pytest.raises(IndexNotLoadedError):
        index.search((TENANT, theirs[1]), np.ones(4, dtype=np.float32), top_k=1)


def test_the_missing_index_refusal_names_neither_tenant_nor_version() -> None:
    index = InProcessIndex()
    theirs = build_index(index, _bundle(tenant_id=OTHER_TENANT))

    with pytest.raises(IndexNotLoadedError) as caught:
        index.search((TENANT, theirs[1]), np.ones(4, dtype=np.float32), top_k=1)

    assert str(OTHER_TENANT) not in str(caught.value)
    assert str(theirs[1]) not in str(caught.value)


def test_two_versions_of_one_tenant_are_both_resident_during_an_activation() -> None:
    """The previous version keeps serving while the next one loads (ER-F-06)."""
    index = InProcessIndex()
    previous = build_index(index, _bundle())
    following = build_index(index, _bundle())

    assert index.loaded() == frozenset({previous, following})


def test_building_the_same_version_twice_replaces_it() -> None:
    """A reload after a restart is the normal case, not an error."""
    index = InProcessIndex()
    bundle = _bundle()
    key = build_index(index, bundle)
    build_index(index, bundle)

    assert index.loaded() == frozenset({key})


def test_dropping_an_index_that_is_not_there_is_not_an_error() -> None:
    """Archive may run twice, and a cleanup that fails because it already
    succeeded is a cleanup that blocks."""
    index = InProcessIndex()

    index.drop((TENANT, uuid.uuid4()))

    assert index.loaded() == frozenset()


def test_a_dropped_index_stops_answering() -> None:
    index = InProcessIndex()
    key = build_index(index, _bundle())

    index.drop(key)

    with pytest.raises(IndexNotLoadedError):
        index.search(key, np.ones(4, dtype=np.float32), top_k=1)


def test_a_query_of_the_wrong_width_is_refused() -> None:
    index = InProcessIndex()
    key = build_index(index, _bundle())

    with pytest.raises(ValueError, match="dimensions"):
        index.search(key, np.ones(7, dtype=np.float32), top_k=1)


def test_searching_does_not_write_through_to_the_shared_matrix() -> None:
    """Exclusion drives rows to `-inf`; doing that in place would poison the
    index for every later request."""
    index = InProcessIndex()
    bundle = _bundle()
    key = build_index(index, bundle)

    index.search(key, np.ones(4, dtype=np.float32), top_k=4, exclude=["SKU-0"])
    after = index.search(key, np.ones(4, dtype=np.float32), top_k=4)

    assert {candidate.item_ref for candidate in after} == {f"SKU-{i}" for i in range(4)}


# ------------------------------------------------------------- the selector


def test_the_default_selector_builds_the_in_process_adapter() -> None:
    from graphrec.common.config import CandidateIndexKind
    from graphrec.ml.index import InProcessIndex, build_candidate_index

    assert isinstance(build_candidate_index(CandidateIndexKind.INPROCESS), InProcessIndex)


def test_selecting_qdrant_refuses_rather_than_quietly_serving_from_a_matrix() -> None:
    """ADR 0026 consequence 3. `QDRANT_*` is a configuration surface for an
    adapter that is not built, and a silent fallback would give an operator who
    asked for a real vector store something else without saying so."""
    import pytest

    from graphrec.common.config import CandidateIndexKind
    from graphrec.ml.index import build_candidate_index

    with pytest.raises(NotImplementedError) as raised:
        build_candidate_index(CandidateIndexKind.QDRANT)

    assert "ADR 0026" in str(raised.value), "the refusal points at the decision"
