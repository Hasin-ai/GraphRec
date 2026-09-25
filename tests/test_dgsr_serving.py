"""DGSR serving against the pretrained Beauty artifact.

Skipped unless ``model_artifacts/dgsr_beauty_t4_v2`` (or ``DGSR_TEST_ARTIFACT``)
exists. The notebook wrote ``recommendations_user_0.csv`` for user ``0`` after
all events; ``encode_known`` must reproduce it exactly, and the virtual-root
path must land on (nearly) the same list for the same history.
"""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from graphrec_core.dgsr.serving import DGSRArtifact, HistoryEvent, load_artifact  # noqa: E402

ARTIFACT = Path(os.environ.get("DGSR_TEST_ARTIFACT", "model_artifacts/dgsr_beauty_t4_v2"))

pytestmark = pytest.mark.skipif(not (ARTIFACT / "best.pt").is_file(), reason="Beauty artifact not present")


@pytest.fixture(scope="module")
def artifact() -> DGSRArtifact:
    return load_artifact(ARTIFACT)


def notebook_recommendations() -> list[tuple[str, float]]:
    with (ARTIFACT / "recommendations_user_0.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [(row["item_id"], float(row["score"])) for row in rows]


def test_artifact_identity(artifact: DGSRArtifact) -> None:
    info = artifact.describe()
    assert info["users"] == 52204 and info["items"] == 57289
    assert info["engine_version"] == "beauty-t4-v2"
    assert artifact.metrics["validation"]["NDCG@10"] > 0.3


def test_known_user_matches_notebook(artifact: DGSRArtifact) -> None:
    user = artifact.user_index("0")
    assert user is not None
    encoded = artifact.encode_known(user)
    seen = np.unique(artifact.data.items[artifact.data.by_user[user]])
    ranked = artifact.top_k(artifact.score(encoded.query, seen), 10)
    expected = notebook_recommendations()
    assert [item for item, _ in ranked] == [item for item, _ in expected]
    for (_, score), (_, reference) in zip(ranked, expected):
        assert score == pytest.approx(reference, abs=2e-3)


def test_virtual_root_reproduces_known_user(artifact: DGSRArtifact) -> None:
    user = artifact.user_index("0")
    events = artifact.data.by_user[user]
    history = [HistoryEvent(int(artifact.data.items[e]), int(artifact.data.times[e])) for e in events]
    exact = artifact.encode_known(user)
    virtual = artifact.encode_history(history, user=user)
    assert virtual.strategy == "personalized" and virtual.known_user
    seen = np.unique(artifact.data.items[events])
    top_exact = [i for i, _ in artifact.top_k(artifact.score(exact.query, seen), 10)]
    top_virtual = [i for i, _ in artifact.top_k(artifact.score(virtual.query, seen), 10)]
    # Same subgraph, same root edges; only same-timestamp tie order can differ.
    assert len(set(top_exact) & set(top_virtual)) >= 8
    assert top_exact[0] == top_virtual[0]


def test_session_without_user_is_labelled(artifact: DGSRArtifact) -> None:
    items = [artifact.item_index(i) for i in ("0", "1", "2")]
    history = [HistoryEvent(i, 500_000_000 + k) for k, i in enumerate(items)]
    encoded = artifact.encode_history(history, user=None)
    assert encoded.strategy == "session" and not encoded.known_user
    ranked = artifact.top_k(artifact.score(encoded.query, items), 5)
    assert len(ranked) == 5
    assert not {"0", "1", "2"} & {item for item, _ in ranked}


def test_virtual_root_with_history_longer_than_recent_items(artifact: DGSRArtifact) -> None:
    # User 112 has 293 events, far beyond recent_items=50; older events on items
    # outside the sampled subgraph must be dropped, not raise.
    user = artifact.user_index("112")
    events = artifact.data.by_user[user]
    assert len(events) > artifact.cfg.recent_items
    history = [HistoryEvent(int(artifact.data.items[e]), int(artifact.data.times[e])) for e in events]
    history.append(HistoryEvent(artifact.item_index("0"), 600_000_000))
    encoded = artifact.encode_history(history, user=user)
    assert encoded.strategy == "personalized" and np.isfinite(encoded.query).all()
    seen = np.unique([h.item for h in history])
    ranked = artifact.top_k(artifact.score(encoded.query, seen), 10)
    exact = artifact.top_k(artifact.score(artifact.encode_known(user).query, seen), 10)
    assert len(set(i for i, _ in ranked) & set(i for i, _ in exact)) >= 5


def test_different_histories_rank_differently(artifact: DGSRArtifact) -> None:
    a, b = artifact.user_index("0"), artifact.user_index("1")
    ranked = []
    for user in (a, b):
        encoded = artifact.encode_known(user)
        seen = np.unique(artifact.data.items[artifact.data.by_user[user]])
        ranked.append([i for i, _ in artifact.top_k(artifact.score(encoded.query, seen), 10)])
    assert ranked[0] != ranked[1]


def test_encode_latency(artifact: DGSRArtifact) -> None:
    user = artifact.user_index("0")
    artifact.encode_known(user)
    started = time.perf_counter()
    for _ in range(5):
        encoded = artifact.encode_known(user)
        artifact.top_k(artifact.score(encoded.query), 10)
    per_request = (time.perf_counter() - started) / 5
    assert per_request < 1.0, f"encode+score took {per_request:.3f}s"
