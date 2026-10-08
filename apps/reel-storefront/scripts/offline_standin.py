"""REHEARSAL ONLY - not GraphRec. Serves the Reel UI without Docker.

Replaces the GraphRec API with an in-process object that calls the SAME DGSR
serving code the API uses (graphrec_core.dgsr.serving: encode_known /
encode_history, seen-item exclusion) on the real MovieLens checkpoint. No
tenancy, auth, persistence, eligibility filtering or feedback storage: use it to
rehearse the acts and check what the model returns, never to present GraphRec.
The Status tab names the tenant "local stand-in" so it cannot be mistaken.

    pip install torch numpy           # in addition to the storefront deps
    python -m uvicorn scripts.offline_standin:app --port 5290   (from apps/reel-storefront)
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))  # graphrec_core

from graphrec_core.dgsr.serving import HistoryEvent, load_artifact  # noqa: E402

from app.config import Settings  # noqa: E402
from app.graphrec import build_local  # noqa: E402
from app.main import create_app  # noqa: E402

A = load_artifact(REPO / "model_artifacts" / "dgsr_movielens_32m")
FILMS = json.loads((HERE / "data" / "films.json").read_text(encoding="utf-8"))
POPULAR = [f["id"] for f in sorted(FILMS, key=lambda f: f["popularityRank"])]
EVENTS: dict = {}
for p in json.loads((HERE / "data" / "personas.json").read_text(encoding="utf-8")):
    for n, h in enumerate(p["history"]):
        EVENTS[f"ml-{p['user_id']}-{n}"] = (p["user_id"], h["filmId"], h["time"])


def _ranked(ids, strategy, fallback=False):
    return SimpleNamespace(
        request_id="req_" + uuid.uuid4().hex[:10],
        items=[SimpleNamespace(external_product_id=i, position=k) for k, i in enumerate(ids, 1)],
        model_version_id=None, strategy=strategy, fallback_used=fallback,
        fallback_tier="standin_popular" if fallback else "none", applied_rules=[])


def _score(history, user, exclude, n):
    events = [HistoryEvent(A.item_index(i), t) for i, t in history if A.item_index(i) is not None]
    if not events:
        return None
    u = A.user_index(user) if user else None
    seen = [i for i, _ in history]
    if u is not None and sorted(set(seen)) == sorted(set(A.known_history(u))):
        enc = A.encode_known(u)
    else:
        enc = A.encode_history(events, user=u)
    ex = [A.item_index(i) for i in set(seen) | set(exclude) if A.item_index(i) is not None]
    return [i for i, _ in A.top_k(A.score(enc.query, ex), n)], enc.strategy


class StandIn:
    def __init__(self) -> None:
        async def create(event_type, *, user_id=None, product_id=None, context=None, event_id=None, occurred_at=None):
            dup = event_id in EVENTS
            if not dup:
                EVENTS[event_id] = (user_id, product_id, int(time.time()))
            return SimpleNamespace(event_id=event_id, accepted=not dup, duplicate=dup, received_at=datetime.now(timezone.utc))

        async def get(*, user_id, top_n, context=None, exclude_product_ids=None):
            hist = sorted([(f, t) for (u, f, t) in EVENTS.values() if u == user_id], key=lambda x: x[1])
            r = _score(hist, user_id, exclude_product_ids or [], top_n)
            return _ranked(*r) if r else _ranked(POPULAR[:top_n], "popular_fallback", True)

        async def for_session(session_id, *, recent_product_ids=None, top_n=10, context=None, exclude_product_ids=None, user_id=None):
            now = int(time.time())
            hist = [(f, now + k) for k, f in enumerate(recent_product_ids or [])]
            r = _score(hist, None, exclude_product_ids or [], top_n)
            if r:
                return _ranked(*r)
            return _ranked([i for i in POPULAR if i not in (exclude_product_ids or [])][:top_n], "popular_fallback", True)

        async def feedback(*args, **kwargs):
            return SimpleNamespace(event_id="fbk_" + uuid.uuid4().hex[:8], accepted=True, duplicate=False)

        self.storefront = SimpleNamespace(
            events=SimpleNamespace(create=create),
            recommendations=SimpleNamespace(get=get, for_session=for_session),
            feedback=SimpleNamespace(impression=feedback, click=feedback, conversion=feedback))

    async def health(self):
        return {"status": "standin"}

    async def close(self):
        pass


_cfg = Settings(graphrec_api_key="gr_live_offline_standin", state_dir=HERE / "state" / "standin",
                reel_tenant_name="local stand-in (NOT GraphRec)", reel_model_version_tag="offline checkpoint")
app = create_app(_cfg, build_local(_cfg, StandIn()))
