"""Unit tests for the glass-box serving pipeline (no Postgres/Qdrant/Redis/torch).

The DB helpers are replaced with an in-memory catalogue and the DGSR artifact
with a tiny fake whose item embeddings form two clusters ("scifi" i0-i9 and
"drama" i10-i19), so neighbor and diversity behaviour is easy to assert.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import numpy as np
import pytest

from graphrec_core.recommendation_rules import RuleSet
from graphrec_core.schemas.recommendations import RecommendationRequest
from graphrec_core.serving import pipeline as pl
from graphrec_core.serving.ranking import (
    Candidate,
    combine_scores,
    mmr_order,
    percentile_ranks,
    primary_reason,
    relevance_order,
)

ITEMS = [f"i{n}" for n in range(20)]
CATEGORY = {item: ("scifi" if n < 10 else "drama") for n, item in enumerate(ITEMS)}
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


class FakeArtifact:
    def __init__(self) -> None:
        rng = np.random.default_rng(7)
        base = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
        rows = [base[0 if n < 10 else 1] + 0.05 * rng.standard_normal(3).astype(np.float32) for n in range(20)]
        # Strength decreases with index inside each cluster so ranks are well defined.
        self.table = np.stack([r * (1.0 - 0.02 * (n % 10)) for n, r in enumerate(rows)]).astype(np.float32)
        self.index = {item: n for n, item in enumerate(ITEMS)}
        self.item_ids = list(ITEMS)

    def item_index(self, item):
        return self.index.get(item)

    def item_embeddings(self):
        return self.table

    def score(self, query, exclude_items=()):
        scores = self.table @ np.asarray(query, dtype=np.float32)
        if len(exclude_items):
            scores[np.asarray(list(exclude_items))] = -np.inf
        return scores

    def top_k(self, scores, k):
        count = min(k, int(np.isfinite(scores).sum()))
        order = np.lexsort((np.arange(len(scores)), -scores))[:count]
        return [(ITEMS[int(i)], float(scores[i])) for i in order]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(pl, "_qdrant_open_until", 0.0)
    state = SimpleNamespace(
        artifact=FakeArtifact(),
        history=["i0"],
        disabled=set(),
        counts={"i15": 9, "i12": 5, "i3": 4},
        remembered=[],
        stored=[],
        fail_popular=False,
    )

    def build_query(db, tenant_id, payload, directory):
        seen = list(dict.fromkeys(state.history))
        encoded = None
        if state.history:
            q = state.artifact.table[[state.artifact.index[i] for i in state.history]].mean(axis=0)
            encoded = SimpleNamespace(query=q, strategy="personalized")
        return pl.Query(state.artifact, encoded, list(state.history), seen)

    def popular_products(db, tenant_id, window, *, limit, exclude=(), categories=None):
        if state.fail_popular:
            raise RuntimeError("database hiccup")
        pool = [i for i in ITEMS if i not in state.disabled and i not in set(exclude)
                and (categories is None or CATEGORY[i] in categories)]
        pool.sort(key=lambda i: (-state.counts.get(i, 0), i))
        return [(i, state.counts.get(i, 0)) for i in pool[:limit]]

    monkeypatch.setattr(pl, "artifact_directory", lambda uri: "dir")
    monkeypatch.setattr(pl, "build_query", build_query)
    monkeypatch.setattr(pl, "popularity_window", lambda db, tenant, days: [])
    monkeypatch.setattr(pl, "popular_products", popular_products)
    monkeypatch.setattr(pl, "eligible_meta", lambda db, tenant, ids: {
        i: (CATEGORY[i], NOW) for i in ids if i in CATEGORY and i not in state.disabled})
    def tenant_popularity(db, tenant_id, days):
        if state.fail_popular:
            raise RuntimeError("database hiccup")
        ranked = sorted(((i, n, CATEGORY[i]) for i, n in state.counts.items()), key=lambda r: (-r[1], r[0]))
        return pl.Popularity(dict(state.counts), ranked)

    monkeypatch.setattr(pl, "tenant_popularity", tenant_popularity)
    monkeypatch.setattr(pl.cache, "load", lambda key: list(state.remembered))
    monkeypatch.setattr(pl.cache, "store", lambda key, items: state.stored.append(items))
    return state


def db_with_categories():
    db = MagicMock()
    db.scalars.return_value.all.side_effect = lambda: ["scifi"]
    return db


SETTINGS = SimpleNamespace(fallback_popularity_window_days=30, qdrant_top_k=100, is_production=False,
                           qdrant_embedding_dim=3)
MODEL = SimpleNamespace(id=uuid4(), artifact_uri="file:///x", model_type="dgsr")


def qdrant_down():
    raise ConnectionError("qdrant unreachable")


def serve(env, rules=None, qdrant=qdrant_down, **request):
    payload = RecommendationRequest(**{"user_id": "u1", "top_n": 5, **request})
    return pl.run(db_with_categories(), uuid4(), payload, MODEL, SETTINGS, rules, qdrant)


# ------------------------------------------------------------------ ranking helpers

def test_percentile_ranks_share_ties_and_span_unit_interval():
    ranks = percentile_ranks({"a": 1.0, "b": 3.0, "c": 3.0, "d": 2.0})
    assert ranks == {"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.5}
    assert percentile_ranks({"only": 5.0}) == {"only": 1.0}


def test_agreement_rewards_items_found_by_several_sources():
    one = Candidate("x", sources=["dgsr_personalized"], model_score=1.0)
    two = Candidate("y", sources=["dgsr_personalized", "session_neighbors", "trending"], model_score=1.0)
    combine_scores([one, two])
    assert one.agreement == 0.0 and two.agreement == 1.0 and two.final > one.final


def test_unknown_items_stay_below_known_median():
    known = [Candidate(f"k{n}", sources=["dgsr_personalized"], model_score=float(n)) for n in range(5)]
    cold = Candidate("cold", sources=["trending"], popularity=100.0)
    combine_scores([*known, cold])
    assert cold.model_norm <= 0.5


def test_mmr_without_diversity_keeps_relevance_order_and_with_it_spreads():
    cands = [Candidate(f"c{n}", final=1.0 - n * 0.01) for n in range(4)]
    vectors = {"c0": np.array([1, 0]), "c1": np.array([1, 0.01]), "c2": np.array([1, 0.02]), "c3": np.array([0, 1])}
    assert [c.external_id for c in mmr_order(cands, vectors, diversity=0, limit=4)] == ["c0", "c1", "c2", "c3"]
    assert [c.external_id for c in mmr_order(cands, vectors, diversity=0.5, limit=2)] == ["c0", "c3"]


def test_relevance_order_ties_break_by_id():
    cands = [Candidate("b", final=0.5), Candidate("a", final=0.5)]
    assert [c.external_id for c in relevance_order(cands)] == ["a", "b"]


# ------------------------------------------------------------------ pipeline

def test_personalized_list_is_explained_and_never_returns_seen_items(env):
    out = serve(env)
    ids = [c.external_id for c in out.items]
    assert len(ids) == 5 and "i0" not in ids
    assert out.strategy == "personalized" and not out.fallback_used and out.model_served
    neighbor = [c for c in out.items if primary_reason(c) == "because_you_viewed"]
    assert neighbor and all(c.anchor_id == "i0" for c in neighbor)
    assert {s["name"] for s in out.explain["stages"]} == {"query", "retrieval", "eligibility", "scoring", "rerank", "guarantee"}


def test_qdrant_outage_falls_back_to_in_memory_scoring(env):
    out = serve(env, explain=True)
    assert out.explain["sources"]["dgsr_personalized"]["status"].endswith("in_memory")
    assert out.strategy == "personalized"


def test_slow_qdrant_is_abandoned_within_budget(env):
    def slow():
        time.sleep(1.5)
        raise ConnectionError("too late")
    started = time.perf_counter()
    out = serve(env, qdrant=slow)
    assert time.perf_counter() - started < 1.0
    assert out.explain["sources"]["dgsr_personalized"]["status"] == "qdrant_timeout->in_memory"
    assert len(out.items) == 5


def test_a_failing_source_is_skipped_not_fatal(env):
    env.fail_popular = True
    out = serve(env)
    assert len(out.items) == 5
    assert out.explain["sources"]["trending"]["status"] == "error"


def test_disabled_and_excluded_products_are_never_served(env):
    env.disabled = {"i1", "i2"}
    out = serve(env, exclude_product_ids=["i3"])
    assert not {"i1", "i2", "i3"} & {c.external_id for c in out.items}


def test_output_is_deterministic(env):
    first = [c.external_id for c in serve(env).items]
    assert all([c.external_id for c in serve(env).items] == first for _ in range(3))


def test_diversity_mixes_categories(env):
    env.history = ["i0", "i1"]
    focused = [CATEGORY[c.external_id] for c in serve(env, diversity=0.0).items]
    diverse = [CATEGORY[c.external_id] for c in serve(env, diversity=0.9).items]
    assert len(set(diverse)) >= len(set(focused)) and len(set(diverse)) == 2


def test_policy_rules_still_apply_on_top(env):
    rules = RuleSet(version=3, diversity_enabled=True, max_per_category=1, freshness_enabled=False,
                    freshness_weight=0.0, freshness_half_life_days=30)
    out = serve(env, rules=rules, diversity=0.0)
    head = [CATEGORY[c.external_id] for c in out.items[:2]]
    assert head[0] != head[1]


def test_short_list_is_topped_up_from_last_good_after_eligibility(env):
    env.disabled = set(ITEMS[4:])           # only i1..i3 remain servable besides seen i0
    env.remembered = ["i9", "i2", "i3", "i1"]
    out = serve(env)
    ids = [c.external_id for c in out.items]
    assert ids[:3] and set(ids) <= {"i1", "i2", "i3"} and len(ids) == 3


def test_no_history_and_no_fallback_returns_nothing(env):
    env.history = []
    out = serve(env, fallback_allowed=False)
    assert out.items == []


def test_no_history_serves_trending_as_fallback(env):
    env.history = []
    out = serve(env)
    assert out.fallback_used and out.strategy == "popular_fallback" and out.fallback_tier == "tenant_popular"
    assert out.items[0].external_id == "i15" and primary_reason(out.items[0]) == "trending"


def test_without_fallback_only_model_sources_are_used(env):
    out = serve(env, fallback_allowed=False, explain=True)
    assert "trending" not in out.explain["sources"] and "popular_in_category" not in out.explain["sources"]
    assert out.items


def test_qdrant_breaker_skips_qdrant_after_a_failure(env):
    calls = []

    def down():
        calls.append(1)
        raise ConnectionError("qdrant unreachable")
    first = serve(env, qdrant=down, explain=True)
    second = serve(env, qdrant=down, explain=True)
    assert first.explain["sources"]["dgsr_personalized"]["status"] == "qdrant_unavailable->in_memory"
    assert second.explain["sources"]["dgsr_personalized"]["status"] == "qdrant_skipped->in_memory"
    assert len(calls) == 1 and [c.external_id for c in first.items] == [c.external_id for c in second.items]
