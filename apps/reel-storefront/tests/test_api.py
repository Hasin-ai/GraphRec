"""Contract tests for the Reel storefront with a fake GraphRec client (no network)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.graphrec import build_local
from app.main import create_app

DATA = Path(__file__).resolve().parents[1] / "data"
FILMS = json.loads((DATA / "films.json").read_text(encoding="utf-8"))
PERSONAS = json.loads((DATA / "personas.json").read_text(encoding="utf-8"))


class FakeGraphRec:
    """Records calls; ranks the most popular unseen films, shifting with history length."""

    def __init__(self) -> None:
        self.events: dict = {}
        self.calls: list = []
        self.version = uuid4()
        me = self
        self.storefront = SimpleNamespace(
            events=SimpleNamespace(create=self._create),
            recommendations=SimpleNamespace(get=self._get, for_session=self._for_session),
            feedback=SimpleNamespace(impression=self._fb("impression"), click=self._fb("click"), conversion=self._fb("conversion")),
        )

    async def health(self):
        return {"status": "ok"}

    async def close(self):
        pass

    async def _create(self, event_type, *, user_id=None, product_id=None, context=None, event_id=None, occurred_at=None):
        duplicate = event_id in self.events
        self.events.setdefault(event_id, (user_id, product_id, event_type))
        return SimpleNamespace(event_id=event_id, accepted=not duplicate, duplicate=duplicate, received_at=datetime.now(timezone.utc))

    def _rank(self, seen, n, offset):
        ids = [f["id"] for f in sorted(FILMS, key=lambda f: f["popularityRank"]) if f["id"] not in seen]
        ids = ids[offset:offset + n]
        return SimpleNamespace(
            request_id="req_" + uuid4().hex[:8], items=[SimpleNamespace(external_product_id=i, position=k) for k, i in enumerate(ids, 1)],
            model_version_id=None if not seen else self.version, strategy="personalized" if seen else "popular_fallback",
            fallback_used=not seen, fallback_tier="tenant_popular" if not seen else "none", applied_rules=[])

    async def _get(self, *, user_id, top_n, context=None, exclude_product_ids=None, **options):
        self.options = options
        self.calls.append(("get", user_id))
        live = [p for (u, p, _) in self.events.values() if u == user_id]
        return self._rank({*live}, top_n, len(live))

    async def _for_session(self, session_id, *, recent_product_ids=None, top_n=10, context=None, exclude_product_ids=None, user_id=None, **options):
        self.options = options
        self.calls.append(("session", tuple(recent_product_ids or ())))
        recent = list(recent_product_ids or [])
        return self._rank(set(recent) | set(exclude_product_ids or []), top_n, len(recent))

    def _fb(self, kind):
        async def send(ref, *args, **kwargs):
            return SimpleNamespace(event_id=f"fbk_{kind}_{uuid4().hex[:6]}", accepted=True, duplicate=False)
        return send


@pytest.fixture
def client(tmp_path):
    cfg = Settings(graphrec_api_key="gr_live_test", state_dir=tmp_path / "state", frontend_dist=tmp_path / "none")
    fake = FakeGraphRec()
    svc = build_local(cfg, fake)
    app = create_app(cfg, svc)
    transport = httpx.ASGITransport(app=app)

    class Ctx:
        async def __aenter__(self):
            self.lifespan = app.router.lifespan_context(app)
            await self.lifespan.__aenter__()
            self.http = httpx.AsyncClient(transport=transport, base_url="http://test")
            self.fake = fake
            return self

        async def __aexit__(self, *exc):
            await self.http.aclose()
            await self.lifespan.__aexit__(*exc)

    return Ctx()


async def test_browse_and_film(client):
    async with client as c:
        page = (await c.http.get("/api/reel/films", params={"genre": "Animation", "limit": 5})).json()["data"]
        assert page["total"] > 300 and all("Animation" in f["genres"] for f in page["items"])
        one = page["items"][0]
        assert (await c.http.get(f"/api/reel/films/{one['id']}")).json()["data"]["title"] == one["title"]
        assert (await c.http.get("/api/reel/films/nope")).status_code == 404


async def test_films_carry_community_tags_and_tags_are_browsable(client):
    async with client as c:
        shining = (await c.http.get("/api/reel/films/1258")).json()["data"]
        assert "stanley kubrick" in shining["tags"] and "horror" not in shining["tags"]  # genre repeats dropped
        top = (await c.http.get("/api/reel/tags", params={"limit": 5})).json()["data"]
        assert len(top) == 5 and top[0]["films"] >= top[-1]["films"]
        many = (await c.http.get("/api/reel/tags", params={"limit": 500})).json()["data"]
        assert not any(t["name"].startswith("nudity") for t in many)
        tagged = (await c.http.get("/api/reel/films", params={"tag": "pixar", "limit": 60})).json()["data"]
        assert tagged["total"] > 5 and all("pixar" in f["tags"] for f in tagged["items"])


async def test_search_matches_titles_first_then_tags(client):
    async with client as c:
        page = (await c.http.get("/api/reel/films", params={"q": "kubrick", "limit": 60})).json()["data"]
        ids = [f["id"] for f in page["items"]]
        assert "1258" in ids  # The Shining has no "kubrick" in its title, only in its tags
        titled = (await c.http.get("/api/reel/films", params={"q": "toy story"})).json()["data"]["items"]
        assert titled[0]["title"].lower().startswith("toy story")


async def test_history_is_complete_newest_first_and_deduplicated(client):
    async with client as c:
        await c.http.post("/api/reel/session/persona", json={"persona": "maya"})
        maya = next(p for p in PERSONAS if p["key"] == "maya")
        film = next(f["id"] for f in FILMS if f["id"] not in {h["filmId"] for h in maya["history"]})
        await c.http.post("/api/reel/watch", json={"filmId": film})
        await c.http.post("/api/reel/watch", json={"filmId": film})
        films = (await c.http.get("/api/reel/insight/history")).json()["data"]
        ids = [f["id"] for f in films]
        assert ids[0] == film and len(ids) == len(set(ids))
        assert len(ids) == len({h["filmId"] for h in maya["history"]} | {film})


async def test_sort_orders(client):
    async with client as c:
        newest = (await c.http.get("/api/reel/films", params={"sort": "newest", "limit": 5})).json()["data"]["items"]
        years = [f["year"] or 0 for f in newest]
        assert years == sorted(years, reverse=True)
        titles = (await c.http.get("/api/reel/films", params={"sort": "title", "limit": 5})).json()["data"]["items"]
        assert [f["title"].lower() for f in titles] == sorted(f["title"].lower() for f in titles)
        assert (await c.http.get("/api/reel/films", params={"sort": "random"})).status_code == 422


async def test_anonymous_session_flow_and_fallback(client):
    async with client as c:
        first = (await c.http.post("/api/reel/recommendations", json={"shelf": "home"})).json()["data"]
        assert first["title"] == "Popular right now" and first["trace"]["fallbackUsed"]
        film = first["items"][0]["id"]
        receipt = (await c.http.post("/api/reel/watch", json={"filmId": film})).json()["data"]
        assert receipt["accepted"] and not receipt["duplicate"]
        after = (await c.http.post("/api/reel/recommendations", json={"shelf": "home"})).json()["data"]
        assert after["trace"]["request"]["recentProductIds"] == [film]
        assert after["diff"]["hasPrevious"] and film not in [i["id"] for i in after["items"]]
        seq = (await c.http.get("/api/reel/insight/sequence")).json()["data"]
        assert seq["sessionOnly"] and [i["film"]["id"] for i in seq["items"]] == [film]


async def test_replay_is_duplicate(client):
    async with client as c:
        await c.http.post("/api/reel/watch", json={"filmId": FILMS[0]["id"]})
        again = (await c.http.post("/api/reel/watch/replay")).json()["data"]
        assert again["duplicate"] and not again["accepted"]
        seq = (await c.http.get("/api/reel/insight/sequence")).json()["data"]
        assert seq["liveCount"] == 1  # the duplicate adds nothing


async def test_persona_window_and_carry(client):
    async with client as c:
        await c.http.post("/api/reel/watch", json={"filmId": FILMS[5]["id"]})
        out = (await c.http.post("/api/reel/session/persona", json={"persona": "maya", "carrySession": True})).json()
        assert out["data"]["persona"]["userId"] == "184387" and len(out["meta"]["carried"]) == 1
        seq = (await c.http.get("/api/reel/insight/sequence")).json()["data"]
        window = [i for i in seq["items"] if i["inWindow"]]
        assert len(window) == 20 and window[-1]["origin"] == "live" and seq["total"] == len(PERSONAS[0]["history"]) + 1
        assert sum(i["evicted"] for i in seq["items"]) == 1
        recs = (await c.http.post("/api/reel/recommendations", json={"shelf": "home"})).json()["data"]
        assert recs["trace"]["request"]["userId"] == "184387" and recs["title"] == "Recommended for you"
        # carrying twice is idempotent
        await c.http.post("/api/reel/session/persona", json={"persona": "anon"})
        again = (await c.http.post("/api/reel/session/persona", json={"persona": "maya", "carrySession": True})).json()
        assert all(r["duplicate"] for r in again["meta"]["carried"])


async def test_more_like_is_session_without_user(client):
    async with client as c:
        await c.http.post("/api/reel/session/persona", json={"persona": "theo"})
        film = FILMS[10]["id"]
        out = (await c.http.post("/api/reel/recommendations", json={"shelf": "more_like", "filmId": film})).json()["data"]
        assert out["trace"]["request"]["userId"] is None and out["trace"]["request"]["recentProductIds"] == [film]
        assert film not in [i["id"] for i in out["items"]]


async def test_rejects_unknown_fields_and_personas(client):
    async with client as c:
        assert (await c.http.post("/api/reel/watch", json={"filmId": "1", "userId": "x"})).status_code == 422
        assert (await c.http.post("/api/reel/session/persona", json={"persona": "mallory"})).status_code == 422


def test_per_visitor_state_is_bounded():
    from app.store import BoundedDict, LastLists
    seen = BoundedDict(limit=3)
    for n in range(5):
        seen[f"req-{n}"] = n
    assert list(seen) == ["req-2", "req-3", "req-4"]
    lists = LastLists(limit=2)
    lists.swap("a", "home", ["1"]); lists.swap("b", "home", ["2"]); lists.swap("c", "home", ["3"])
    assert lists.swap("a", "home", ["4"]) is None   # the oldest shopper's list was forgotten
    assert lists.swap("c", "home", ["5"]) == ["3"]


def test_bootstrap_quotes_env_values_with_spaces(tmp_path):
    import importlib.util
    from pathlib import Path
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_reel.py"
    spec = importlib.util.spec_from_file_location("bootstrap_reel", str(script_path))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    path = tmp_path / ".env"
    module.write_env(path, {"REEL_TENANT_NAME": "Reel 3f2a1c", "GRAPHREC_API_KEY": "gr_live_abc"})
    assert path.read_text() == 'REEL_TENANT_NAME="Reel 3f2a1c"\nGRAPHREC_API_KEY=gr_live_abc\n'


async def test_status_shows_the_checkpoint_card_only_for_the_imported_checkpoint(client):
    async with client as c:
        body = (await c.http.get("/api/reel/insight/status")).json()["data"]
        assert body["modelSource"] == "checkpoint" and body["modelCard"]["dataset"] == "MovieLens 32M"
        c.http._transport.app.state.settings.reel_model_source = "trained"
        body = (await c.http.get("/api/reel/insight/status")).json()["data"]
        assert body["modelSource"] == "trained" and body["modelCard"] is None


async def test_pipeline_options_are_forwarded_and_reasons_explained(client):
    async with client as c:
        anchor = FILMS[3]
        original = c.fake._for_session

        async def explained(*args, **kwargs):
            recs = await original(*args, **kwargs)
            first = recs.items[0]
            first.reason, first.anchor_product_id, first.sources, first.score = (
                "because_you_viewed", anchor["id"], ["session_neighbors", "dgsr_personalized"], 0.91)
            recs.items[1].reason = "trending"
            recs.pipeline, recs.diversity = "glassbox-v1", 0.6
            recs.explain = {"stages": [{"name": "retrieval", "count": 120, "ms": 4.2}], "sources": {}}
            return recs

        c.fake._for_session = explained
        c.fake.storefront.recommendations.for_session = explained
        out = (await c.http.post("/api/reel/recommendations",
                                 json={"shelf": "home", "diversity": 0.6})).json()["data"]
        assert c.fake.options == {"explain": True, "diversity": 0.6}
        assert out["items"][0]["reasonText"].startswith("Because you watched")
        assert out["items"][1]["reasonText"] == "Trending now"
        assert out["trace"]["pipeline"] == "glassbox-v1" and out["trace"]["explain"]["stages"][0]["count"] == 120
        await c.http.post("/api/reel/recommendations", json={"shelf": "home"})
        assert c.fake.options == {"explain": True}
        assert (await c.http.post("/api/reel/recommendations", json={"shelf": "home", "pipeline": "legacy"})).status_code == 422


async def test_guest_reset_starts_a_clean_visitor(client):
    async with client as c:
        before = (await c.http.get("/api/reel/session")).json()["data"]
        film = FILMS[2]["id"]
        await c.http.post("/api/reel/watch", json={"filmId": film})
        await c.http.post("/api/reel/recommendations", json={"shelf": "home"})
        assert [i["film"]["id"] for i in (await c.http.get("/api/reel/insight/sequence")).json()["data"]["items"]] == [film]
        reset = await c.http.post("/api/reel/session/reset")
        assert reset.status_code == 200
        after = reset.json()["data"]
        assert after["persona"]["key"] == "anon" and after["sessionId"] != before["sessionId"]
        assert reset.json()["meta"]["previous_session_id"] == before["sessionId"]
        # The new session carries no history: empty sequence, popular fallback, no recent ids, no stale diff.
        assert (await c.http.get("/api/reel/insight/sequence")).json()["data"]["items"] == []
        assert (await c.http.get("/api/reel/insight/history")).json()["data"] == []
        recs = (await c.http.post("/api/reel/recommendations", json={"shelf": "home"})).json()["data"]
        assert recs["trace"]["request"]["recentProductIds"] == [] and recs["trace"]["fallbackUsed"]
        assert recs["diff"]["hasPrevious"] is False
        assert (await c.http.get("/api/reel/session")).json()["data"]["sessionId"] == after["sessionId"]


async def test_named_shopper_cannot_be_reset(client):
    async with client as c:
        await c.http.post("/api/reel/session/persona", json={"persona": "theo"})
        refused = await c.http.post("/api/reel/session/reset")
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "reset_not_supported"
        assert (await c.http.get("/api/reel/session")).json()["data"]["persona"]["key"] == "theo"
