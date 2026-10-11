"""Glass-box serving pipeline (stages 1-6; admission stays in the route).

Robustness rules:

* every retrieval source is optional - an error or timeout drops that source,
  is recorded in the trace and never fails the request;
* Qdrant runs under a timeout and falls back to scoring the in-memory DGSR
  item table, so personalization survives a Qdrant outage;
* eligibility is always enforced by one SQL query against the servable
  catalogue, for every source including the last-good cache;
* the output is deterministic for the same input and model.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.database.models import CustomerEvent, ModelVersion, Product
from graphrec_core.models_reg.service import artifact_directory
from graphrec_core.recommendation_rules import RuleSet, rerank
from graphrec_core.serving import cache
from graphrec_core.serving.ranking import (  # noqa: F401  (tuning constants re-exported)
    DEFAULT_DIVERSITY,
    NEIGHBOR_ANCHORS,
    QUOTA_CATEGORY,
    QUOTA_NEIGHBORS,
    QUOTA_PERSONALIZED,
    QUOTA_TRENDING,
    WEIGHTS,
    Candidate,
    combine_scores,
    mmr_order,
    primary_reason,
    relevance_order,
)
from graphrec_core.vector_store.retriever import retrieve_candidates

logger = logging.getLogger(__name__)

PIPELINE_NAME = "glassbox-v1"

#: Qdrant must answer within this budget or the in-memory item table is used.
QDRANT_TIMEOUT_SECONDS = 0.25
#: After a Qdrant timeout or error, skip it (serve from memory) for this long,
#: so an outage does not add the timeout budget to every request.
QDRANT_BREAKER_SECONDS = 30.0
_qdrant_open_until = 0.0

HISTORY_LIMIT = 1000
HISTORY_EVENT_TYPES = ("view", "click", "add_to_cart", "purchase", "rating", "add_to_wishlist")
SESSION_ITEMS_LIMIT = 50
SERVABLE_AVAILABILITY = "available"

_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="graphrec-source")


def servable() -> tuple[Any, ...]:
    return (Product.is_active == True, Product.availability_status == SERVABLE_AVAILABILITY)  # noqa: E712


@dataclass
class Outcome:
    items: list[Candidate]
    strategy: str
    fallback_used: bool
    fallback_tier: str
    model_served: bool
    diversity: float
    explain: dict[str, Any] = field(default_factory=dict)


class Trace:
    def __init__(self) -> None:
        self.stages: list[dict[str, Any]] = []
        self.sources: dict[str, dict[str, Any]] = {}
        self._mark = time.perf_counter()
        self._start = self._mark

    def stage(self, name: str, count: int, **detail: Any) -> None:
        now = time.perf_counter()
        self.stages.append({"name": name, "ms": round((now - self._mark) * 1000, 2), "count": count, **detail})
        self._mark = now

    def source(self, name: str, status: str, count: int, started: float, **detail: Any) -> None:
        self.sources[name] = {"status": status, "count": count,
                              "ms": round((time.perf_counter() - started) * 1000, 2), **detail}

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 2)


# ---------------------------------------------------------------- stage 1: query

def session_items(context: Any) -> list[str]:
    raw = context.get("recent_product_ids") if context is not None else None
    if not isinstance(raw, list):
        return []
    items = [str(v) for v in raw if isinstance(v, (str, int)) and str(v).strip()]
    return items[-SESSION_ITEMS_LIMIT:]


def stored_history(db: Session, tenant_id: UUID, user_id: str) -> list[tuple[str, datetime]]:
    rows = db.execute(
        select(CustomerEvent.external_product_id, CustomerEvent.occurred_at)
        .where(
            CustomerEvent.tenant_id == tenant_id,
            CustomerEvent.user_id == user_id,
            CustomerEvent.external_product_id.is_not(None),
            CustomerEvent.event_type.in_(HISTORY_EVENT_TYPES),
        )
        .order_by(CustomerEvent.occurred_at.desc(), CustomerEvent.created_at.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return [(str(p), t) for p, t in reversed(rows)]


@dataclass
class Query:
    artifact: Any
    encoded: Any | None
    history: list[str]          # oldest first, stored + session
    seen: list[str]


def build_query(db: Session, tenant_id: UUID, payload: Any, directory: Any) -> Query:
    from graphrec_core.dgsr.serving import HistoryEvent, load_artifact

    artifact = load_artifact(directory)
    history = stored_history(db, tenant_id, payload.user_id) if payload.user_id else []
    now = datetime.now(timezone.utc)
    recent = session_items(payload.context)
    history.extend((item, now) for item in recent)
    items = [item for item, _ in history]
    seen = list(dict.fromkeys(items))
    if not history:
        return Query(artifact, None, items, seen)
    user = artifact.user_index(payload.user_id) if payload.user_id else None
    if user is not None and not recent and sorted(seen) == sorted(set(artifact.known_history(user))):
        return Query(artifact, artifact.encode_known(user), items, seen)
    events = [HistoryEvent(index, int(t.timestamp())) for item, t in history
              if (index := artifact.item_index(item)) is not None]
    if not events:
        return Query(artifact, None, items, seen)
    return Query(artifact, artifact.encode_history(events, user=user), items, seen)


def unit_item_table(artifact: Any) -> np.ndarray:
    """Row-normalised item embeddings, computed once per loaded artifact."""
    table = getattr(artifact, "_serving_unit_items", None)
    if table is None:
        raw = artifact.item_embeddings()
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        table = raw / np.where(norms > 0, norms, 1.0)
        artifact._serving_unit_items = table
    return table


# ---------------------------------------------------------------- stage 2: sources

def popularity_window(db: Session, tenant_id: UUID, days: int) -> list[Any]:
    latest = db.scalar(select(func.max(CustomerEvent.occurred_at)).where(CustomerEvent.tenant_id == tenant_id))
    recent = [CustomerEvent.tenant_id == tenant_id]
    if latest is not None:
        recent.append(CustomerEvent.occurred_at >= latest - timedelta(days=days))
    return recent


#: Tenant popularity (recent event counts) is shared by requests for this long.
POPULARITY_TTL_SECONDS = 15.0
#: Most popular products kept per tenant for the trending / category sources.
POPULARITY_TOP = 500
_POPULARITY_CACHE_MAX = 1000
_popularity_lock = threading.Lock()
_popularity_cache: dict[tuple[UUID, int], tuple[float, "Popularity"]] = {}


@dataclass
class Popularity:
    #: Recent events per product (popularity window).
    counts: dict[str, int]
    #: The most popular catalogue products: (external id, events, category), best first.
    ranked: list[tuple[str, int, str | None]]


def tenant_popularity(db: Session, tenant_id: UUID, days: int) -> Popularity:
    """Recent popularity for one tenant, computed at most once per TTL per process.

    It only feeds candidate generation and a 5 % scoring weight; eligibility is
    still checked per request against the live catalogue, so a disabled product
    is never served from a cached ranking.
    """
    now = time.monotonic()
    key = (tenant_id, days)
    hit = _popularity_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    window = popularity_window(db, tenant_id, days)
    rows = db.execute(select(CustomerEvent.external_product_id, func.count()).where(
        *window, CustomerEvent.external_product_id.is_not(None)).group_by(CustomerEvent.external_product_id)).all()
    counts = {str(pid): int(n) for pid, n in rows}
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:POPULARITY_TOP]
    categories = dict(db.execute(select(Product.external_id, Product.category).where(
        Product.tenant_id == tenant_id, Product.external_id.in_([pid for pid, _ in top]))).all()) if top else {}
    value = Popularity(counts, [(pid, n, categories.get(pid)) for pid, n in top if pid in categories])
    with _popularity_lock:
        if len(_popularity_cache) >= _POPULARITY_CACHE_MAX:
            _popularity_cache.pop(next(iter(_popularity_cache)))
        _popularity_cache[key] = (now + POPULARITY_TTL_SECONDS, value)
    return value


def popular_products(db: Session, tenant_id: UUID, window: list[Any], *, limit: int,
                     exclude: Sequence[str] = (), categories: Sequence[str] | None = None) -> list[tuple[str, int]]:
    """Servable products by recent event count (ties by external ID)."""
    popularity = (
        select(CustomerEvent.external_product_id.label("product_id"), func.count().label("events"))
        .where(*window).group_by(CustomerEvent.external_product_id).subquery()
    )
    query = (
        select(Product.external_id, func.coalesce(popularity.c.events, 0))
        .outerjoin(popularity, popularity.c.product_id == Product.external_id)
        .where(Product.tenant_id == tenant_id, *servable())
        .order_by(func.coalesce(popularity.c.events, 0).desc(), Product.external_id.asc())
        .limit(limit)
    )
    if categories is not None:
        query = query.where(Product.category.in_(list(categories)))
    if exclude:
        query = query.where(Product.external_id.not_in(list(exclude)))
    return [(str(pid), int(count)) for pid, count in db.execute(query).all()]


def _qdrant_search(factory: Callable[[], Any], tenant_id: UUID, version_id: UUID, vector: list[float],
                   top_k: int, exclude: list[str]) -> list[str]:
    return retrieve_candidates(client=factory(), tenant_id=tenant_id, version_id=version_id,
                               query_vector=vector, top_k=top_k, exclude_ids=exclude or None)


@dataclass
class QdrantCall:
    future: Any | None          # None while the breaker is open
    deadline: float


def start_qdrant(q: Query, factory: Callable[[], Any], tenant_id: UUID, version_id: UUID,
                 exclude: list[str], top_k: int) -> QdrantCall:
    """Submit the ANN search so it runs while the in-process sources work."""
    if time.monotonic() < _qdrant_open_until:
        return QdrantCall(None, 0.0)
    future = _EXECUTOR.submit(_qdrant_search, factory, tenant_id, version_id,
                              q.encoded.query.tolist(), top_k, exclude)
    return QdrantCall(future, time.monotonic() + QDRANT_TIMEOUT_SECONDS)


def finish_personalized(q: Query, all_scores: np.ndarray, call: QdrantCall, exclude: list[str],
                        top_k: int) -> tuple[list[str], str]:
    """Qdrant's answer, or the same Top-K scored in-process from the item table."""
    global _qdrant_open_until
    if call.future is None:
        ids, status = [], "qdrant_skipped"
    else:
        try:
            ids = call.future.result(timeout=max(call.deadline - time.monotonic(), 0.0))
            status = "qdrant" if ids else "qdrant_empty"
        except FuturesTimeout:
            ids, status = [], "qdrant_timeout"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant retrieval failed; scoring the item table in-process: %s", exc)
            ids, status = [], "qdrant_unavailable"
        if status in ("qdrant_timeout", "qdrant_unavailable"):
            _qdrant_open_until = time.monotonic() + QDRANT_BREAKER_SECONDS
            logger.warning("Qdrant %s; serving from the in-memory item table for %ss", status, QDRANT_BREAKER_SECONDS)
    if ids:
        return ids, status
    scores = all_scores.copy()
    rows = [i for item in exclude if (i := q.artifact.item_index(item)) is not None]
    if rows:
        scores[np.asarray(rows, dtype=np.int64)] = -np.inf
    return [item for item, _ in q.artifact.top_k(scores, top_k)], f"{status}->in_memory"


def source_personalized(q: Query, all_scores: np.ndarray, factory: Callable[[], Any], tenant_id: UUID,
                        version_id: UUID, exclude: list[str], top_k: int) -> tuple[list[str], str]:
    """Qdrant Top-K for the shopper's query (start + finish in one call)."""
    return finish_personalized(q, all_scores, start_qdrant(q, factory, tenant_id, version_id, exclude, top_k),
                               exclude, top_k)


def fast_top_k(scores: np.ndarray, k: int) -> list[int]:
    """Indices of the k best finite scores; ties by ascending index (as ``top_k``)."""
    finite = np.isfinite(scores)
    k = min(k, int(finite.sum()))
    if k <= 0:
        return []
    candidates = np.argpartition(-np.where(finite, scores, -np.inf), k - 1)[:k] if k < len(scores) else np.arange(len(scores))
    threshold = scores[candidates].min()
    pool = np.flatnonzero(finite & (scores >= threshold))   # keeps every tie at the boundary
    order = np.lexsort((pool, -scores[pool]))[:k]
    return [int(i) for i in pool[order]]


def neighbor_anchors(q: Query) -> list[str]:
    anchors: list[str] = []
    for item in reversed(q.history):
        if item not in anchors and q.artifact.item_index(item) is not None:
            anchors.append(item)
            if len(anchors) == NEIGHBOR_ANCHORS:
                break
    return anchors


def source_neighbors(q: Query, anchors: list[str], exclude: set[str]) -> list[tuple[str, str]]:
    """Items closest (cosine) to each recent anchor, interleaved round-robin."""
    if not anchors:
        return []
    table = unit_item_table(q.artifact)
    blocked = np.asarray([i for item in exclude if (i := q.artifact.item_index(item)) is not None], dtype=np.int64)
    per_anchor = max(QUOTA_NEIGHBORS // len(anchors), 1)
    lists: list[list[tuple[str, str]]] = []
    for anchor in anchors:
        sims = table @ table[q.artifact.item_index(anchor)]
        if blocked.size:
            sims[blocked] = -np.inf
        lists.append([(q.artifact.item_ids[i], anchor) for i in fast_top_k(sims, per_anchor)])
    out, seen = [], set()
    for rank in range(per_anchor):
        for lst in lists:
            if rank < len(lst) and lst[rank][0] not in seen:
                seen.add(lst[rank][0])
                out.append(lst[rank])
    return out


# ---------------------------------------------------------------- pipeline

def run(db: Session, tenant_id: UUID, payload: Any, active_model: ModelVersion | None, settings: Any,
        rules: RuleSet | None, qdrant_factory: Callable[[], Any]) -> Outcome:
    trace = Trace()
    top_n = payload.top_n
    requested_exclude = list(dict.fromkeys(payload.exclude_product_ids or []))
    window_days = settings.fallback_popularity_window_days
    popularity: Popularity | None = None
    diversity = DEFAULT_DIVERSITY if getattr(payload, "diversity", None) is None else float(payload.diversity)

    # ---- stage 1: query -------------------------------------------------------
    q: Query | None = None
    strategy = "popular_fallback"
    directory = artifact_directory(active_model.artifact_uri) if active_model else None
    placeholder = (active_model is not None and directory is None and active_model.model_type != "dgsr"
                   and not settings.is_production)
    if active_model is not None and directory is not None:
        try:
            q = build_query(db, tenant_id, payload, directory)
            if q.encoded is not None:
                strategy = q.encoded.strategy
        except Exception as exc:  # noqa: BLE001
            logger.exception("DGSR query building failed; serving without the model: %s", exc)
            q = None
    trace.stage("query", len(q.history) if q else 0, strategy=strategy,
                model="dgsr" if q and q.encoded is not None else ("placeholder" if placeholder else "none"))

    candidates: dict[str, Candidate] = {}

    def add(source: str, ids: Sequence[str], anchors: Sequence[str | None] | None = None) -> None:
        for rank, item in enumerate(ids, start=1):
            c = candidates.get(item) or candidates.setdefault(item, Candidate(external_id=item))
            c.add_source(source, rank, anchors[rank - 1] if anchors else None)

    personal = q is not None and q.encoded is not None
    exclude = list(dict.fromkeys([*requested_exclude, *(q.seen if personal else [])]))
    exclude_set = set(exclude)
    all_scores: np.ndarray | None = None

    # ---- stage 2: retrieval -----------------------------------------------------
    if personal:
        personal_started = time.perf_counter()
        top_k = min(QUOTA_PERSONALIZED, settings.qdrant_top_k)
        qdrant_call = start_qdrant(q, qdrant_factory, tenant_id, active_model.id, exclude, top_k)
        all_scores = q.artifact.score(q.encoded.query)

        started = time.perf_counter()
        anchors: list[str] = []
        try:
            anchors = neighbor_anchors(q)
            pairs = source_neighbors(q, anchors, exclude_set)
            add("session_neighbors", [p for p, _ in pairs], [a for _, a in pairs])
            trace.source("session_neighbors", "ok" if pairs else "no_anchors", len(pairs), started, anchors=anchors)
        except Exception as exc:  # noqa: BLE001
            logger.exception("session_neighbors failed: %s", exc)
            trace.source("session_neighbors", "error", 0, started)

        if payload.fallback_allowed:
            started = time.perf_counter()
            try:
                with db.begin_nested():
                    cats = list(dict.fromkeys(db.scalars(select(Product.category).where(
                        Product.tenant_id == tenant_id,
                        Product.external_id.in_(anchors or q.seen[-NEIGHBOR_ANCHORS:]),
                        Product.category.is_not(None))).all()))[:NEIGHBOR_ANCHORS]
                    popularity = tenant_popularity(db, tenant_id, window_days)
                    wanted = set(cats)
                    rows = [r for r in popularity.ranked if r[2] in wanted and r[0] not in exclude_set][:QUOTA_CATEGORY]
                add("popular_in_category", [r[0] for r in rows])
                trace.source("popular_in_category", "ok" if rows else "no_categories", len(rows), started,
                             categories=cats)
            except Exception as exc:  # noqa: BLE001
                logger.exception("popular_in_category failed: %s", exc)
                trace.source("popular_in_category", "error", 0, started)

            started = time.perf_counter()
            try:
                with db.begin_nested():
                    popularity = popularity or tenant_popularity(db, tenant_id, window_days)
                    rows = [r for r in popularity.ranked if r[0] not in exclude_set][:QUOTA_TRENDING]
                add("trending", [r[0] for r in rows])
                trace.source("trending", "ok", len(rows), started)
            except Exception as exc:  # noqa: BLE001
                logger.exception("trending failed: %s", exc)
                trace.source("trending", "error", 0, started)
        try:
            ids, status = finish_personalized(q, all_scores, qdrant_call, exclude, top_k)
            add("dgsr_personalized", ids)
            trace.source("dgsr_personalized", status, len(ids), personal_started)
        except Exception as exc:  # noqa: BLE001
            logger.exception("dgsr_personalized failed: %s", exc)
            trace.source("dgsr_personalized", "error", 0, personal_started)
    elif placeholder:
        started = time.perf_counter()
        vec = [0.0] * settings.qdrant_embedding_dim
        vec[0] = 1.0
        try:
            ids = _qdrant_search(qdrant_factory, tenant_id, active_model.id, vec, settings.qdrant_top_k,
                                 requested_exclude)
            add("dgsr_personalized", ids)
            strategy = "development_placeholder"
            trace.source("dgsr_personalized", "placeholder", len(ids), started)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Placeholder retrieval failed: %s", exc)
            trace.source("dgsr_personalized", "error", 0, started)
    trace.stage("retrieval", len(candidates))

    # ---- stage 3: eligibility ---------------------------------------------------
    meta: dict[str, tuple[str | None, datetime]] = {}
    if candidates:
        meta = eligible_meta(db, tenant_id, list(candidates))
    eligible = [c for item, c in candidates.items() if item in meta and item not in exclude_set]
    trace.stage("eligibility", len(eligible), dropped=len(candidates) - len(eligible))

    # ---- stage 4: scoring -------------------------------------------------------
    if eligible:
        try:
            if popularity is None:
                with db.begin_nested():
                    popularity = tenant_popularity(db, tenant_id, window_days)
            counts = popularity.counts
        except Exception as exc:  # noqa: BLE001
            # Popularity only nudges the score (5 %); rank by the model alone.
            logger.exception("Popularity unavailable for scoring: %s", exc)
            counts = {}
        for c in eligible:
            c.category = meta[c.external_id][0]
            c.popularity = float(counts.get(c.external_id, 0))
            if personal:
                c.item_index = q.artifact.item_index(c.external_id)
                if c.item_index is not None:
                    c.model_score = float(all_scores[c.item_index])
        combine_scores(eligible)
    ordered = relevance_order(eligible)
    trace.stage("scoring", len(ordered))

    # ---- stage 5: re-ranking ------------------------------------------------------
    pool = max(top_n * 5, 50) if rules else top_n
    vectors: dict[str, np.ndarray] = {}
    if personal and ordered:
        table = unit_item_table(q.artifact)
        vectors = {c.external_id: table[c.item_index] for c in ordered if c.item_index is not None}
    picked = mmr_order(ordered, vectors, diversity=diversity if vectors else 0.0, limit=min(pool, len(ordered)))
    if rules and picked:
        by_id = {c.external_id: c for c in picked}
        picked = [by_id[i] for i in rerank([c.external_id for c in picked], meta, rules, top_n=top_n,
                                           now=datetime.now(timezone.utc))]
    picked = picked[:top_n]
    trace.stage("rerank", len(picked), diversity=diversity if vectors else 0.0,
                rules=rules.applied() if rules else [])

    # ---- stage 6: guarantee -------------------------------------------------------
    cache_key = cache.key(tenant_id, payload.user_id, payload.context.get("session_id"))
    topped_up = 0
    if picked and len(picked) < top_n and payload.fallback_allowed:
        have = {c.external_id for c in picked}
        remembered = [i for i in cache.load(cache_key) if i not in have and i not in exclude_set]
        if remembered:
            still = eligible_meta(db, tenant_id, remembered)
            for item in remembered:
                if item in still and len(picked) < top_n:
                    c = Candidate(external_id=item, sources=["last_good"], category=still[item][0])
                    picked.append(c)
                    topped_up += 1

    model_served = any(c.model_score is not None or "dgsr_personalized" in c.sources for c in picked)
    fallback_used, fallback_tier = False, "none"
    if not picked:
        picked = popular_fallback(db, tenant_id, payload, popularity_window(db, tenant_id, window_days),
                                  rules, requested_exclude)
        if picked:
            fallback_used, fallback_tier, strategy = True, "tenant_popular", "popular_fallback"
    elif not model_served:
        fallback_used, fallback_tier, strategy = True, "tenant_popular", "popular_fallback"
    if picked:
        cache.store(cache_key, [c.external_id for c in picked])
    trace.stage("guarantee", len(picked), topped_up=topped_up, fallback_tier=fallback_tier)

    explain = {
        "pipeline": PIPELINE_NAME,
        "total_ms": trace.total_ms,
        "stages": trace.stages,
        "sources": trace.sources,
        "weights": WEIGHTS,
        "diversity": diversity if vectors else 0.0,
        "candidates": [explain_item(c) for c in ordered[:max(top_n * 3, 30)]],
    }
    return Outcome(items=picked, strategy=strategy, fallback_used=fallback_used, fallback_tier=fallback_tier,
                   model_served=model_served and not fallback_used, diversity=diversity if vectors else 0.0,
                   explain=explain)


def eligible_meta(db: Session, tenant_id: UUID, ids: list[str]) -> dict[str, tuple[str | None, datetime]]:
    rows = db.execute(select(Product.external_id, Product.category, Product.created_at).where(
        Product.tenant_id == tenant_id, Product.external_id.in_(ids), *servable()))
    return {str(eid): (cat, created) for eid, cat, created in rows}


def popular_fallback(db: Session, tenant_id: UUID, payload: Any, window: list[Any], rules: RuleSet | None,
                     exclude: list[str]) -> list[Candidate]:
    """The tenant-popular tier: recent popularity, servable products, ties by ID."""
    if not payload.fallback_allowed:
        return []
    limit = min(max(payload.top_n * 5, 50), 500) if rules else payload.top_n
    rows = popular_products(db, tenant_id, window, limit=limit, exclude=exclude)
    ids = [r[0] for r in rows]
    if rules and ids:
        meta = eligible_meta(db, tenant_id, ids)
        ids = rerank(ids, meta, rules, top_n=payload.top_n, now=datetime.now(timezone.utc),
                     scores={r[0]: float(r[1]) for r in rows})
    counts = dict(rows)
    out = []
    for rank, item in enumerate(ids[:payload.top_n], start=1):
        c = Candidate(external_id=item, popularity=float(counts.get(item, 0)))
        c.add_source("trending", rank)
        out.append(c)
    return out


def explain_item(c: Candidate) -> dict[str, Any]:
    r = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
    return {
        "external_product_id": c.external_id,
        "sources": list(c.sources),
        "source_ranks": dict(c.source_ranks),
        "anchor_product_id": c.anchor_id,
        "category": c.category,
        "reason": primary_reason(c),
        "model_score": r(c.model_score),
        "model_norm": r(c.model_norm),
        "popularity": r(c.popularity),
        "popularity_norm": r(c.popularity_norm),
        "agreement": r(c.agreement),
        "final": r(c.final),
        "rank_before_rerank": c.rank_before_rerank,
    }
