"""The two DGSR encode paths must agree on an unchanged history.

``_dgsr_candidates`` switches from ``encode_known`` (saved graph) to
``encode_history`` (virtual root) as soon as a shopper has one event the
training graph does not contain. If the paths disagreed on the same history,
part of any "before vs after" difference would come from the switch rather than
the new event. Requires torch and the MovieLens artifact; skipped otherwise.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from graphrec_core.dgsr.serving import HistoryEvent, load_artifact  # noqa: E402

ARTIFACT = Path(__file__).resolve().parents[1] / "model_artifacts" / "dgsr_movielens_32m"


@pytest.mark.skipif(not (ARTIFACT / "best.pt").is_file(), reason="MovieLens artifact not present")
@pytest.mark.parametrize("user_id", ["184387", "48173", "150751"])
def test_known_and_virtual_root_paths_agree(user_id: str) -> None:
    artifact = load_artifact(ARTIFACT)
    user = artifact.user_index(user_id)
    assert user is not None
    rows = artifact.data.by_user[user]
    events = [HistoryEvent(int(artifact.data.items[r]), int(artifact.data.times[r])) for r in rows]
    known = artifact.encode_known(user)
    virtual = artifact.encode_history(events, user=user)
    np.testing.assert_allclose(known.query, virtual.query, rtol=0, atol=1e-5)
    seen = sorted({e.item for e in events})
    top_known = artifact.top_k(artifact.score(known.query, seen), 10)
    top_virtual = artifact.top_k(artifact.score(virtual.query, seen), 10)
    assert [i for i, _ in top_known] == [i for i, _ in top_virtual]
