"""Recommendations route — four-stage serving funnel with Qdrant Stage 1.

Stage 0: Query assembly. For a DGSR model version (``artifact_uri`` is a
         ``file://`` directory) the shopper's event history from PostgreSQL,
         plus any ``context.recent_product_ids`` from the session, is encoded
         by the trained model into a query vector (Eq. 17-18). Placeholder
         versions keep the unit query vector.
Stage 1: ANN candidate retrieval via Qdrant (Top-K by the collection's
         distance: DOT for DGSR item tables, cosine for placeholders). When the
         collection is unavailable a DGSR version scores its item table
         in-process so one ready capability remains (NR-NF-08).
Stage 2: Eligibility filtering against the PostgreSQL product catalog. A
         product is servable only when it is active and its availability is
         ``available`` (BRULE-09: disabled, unavailable, out-of-stock and
         discontinued products are never returned).
Stage 3: Proxy scoring — retrieval rank order is the score
Stage 4: Deterministic ordering — top_n items, stable tie-break by product ID
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import (
    CustomerEvent,
    ModelVersion,
    Product,
    ServingRequest,
    UsageEvent,
    RecommendationRecord,
    RecommendationResult,
)
from graphrec_core.database.session import get_db
from graphrec_core.customers import ensure_customers
from graphrec_core.recommendation_policy_service import load_rules
from graphrec_core.recommendation_rules import rerank
from graphrec_core.models_reg.service import artifact_directory
from graphrec_core.schemas.recommendations import (
    ClickFeedback,
    ConversionFeedback,
    FeedbackResponse,
    ImpressionFeedback,
    RecommendationItem,
    RecommendationRequest,
    RecommendationResponse,
)
from graphrec_core.settings import get_settings
from graphrec_core.errors import ApiError
from graphrec_core.feedback import payload_hash, submit_feedback
from graphrec_core.usage.limits import require_capacity
from graphrec_core.vector_store.client import get_qdrant_client
from graphrec_core.vector_store.retriever import retrieve_candidates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])


def _zero_query_vector(dim: int) -> list[float]:
    """Return a deterministic placeholder query vector.

    This is used only by explicit development-placeholder versions. Real DGSR
    versions encode the user's history with the trained artifact.
    """
    vec = [0.0] * dim
    vec[0] = 1.0
    return vec


#: Most recent stored events considered for one shopper's history.
HISTORY_LIMIT = 1000
#: Session items accepted from ``context.recent_product_ids``.
SESSION_ITEMS_LIMIT = 50
#: The only availability a product may have and still be served (BRULE-09).
SERVABLE_AVAILABILITY = "available"


def _servable() -> tuple[Any, ...]:
    """Stage 2 eligibility predicate, shared by retrieval filtering and fallback."""
    return (
        Product.is_active == True,  # noqa: E712
        Product.availability_status == SERVABLE_AVAILABILITY,
    )


def _record_serving_request(
    db: Session,
    tenant_id: UUID,
    *,
    model_version_id: UUID | None,
    strategy: str,
    outcome: str,
    fallback_used: bool,
    item_count: int,
    latency_ms: int,
) -> bool:
    """Append the telemetry row behind /v1/metrics/summary and meter the request.

    Observability must never turn a served response into a failed one, so a
    write that fails is rolled back and logged instead of raised.
    """
    now = datetime.now(timezone.utc)
    request_id = uuid4()
    try:
        db.add(
            ServingRequest(
                id=request_id,
                tenant_id=tenant_id,
                model_version_id=model_version_id,
                strategy=strategy,
                outcome=outcome,
                fallback_used=fallback_used,
                item_count=item_count,
                latency_ms=latency_ms,
                occurred_at=now,
            )
        )
        db.add(
            UsageEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                usage_type="recommendation_requests",
                quantity=Decimal(1),
                source_id=str(request_id),
                idempotency_key=f"serving-{request_id}",
                occurred_at=now,
            )
        )
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recording the serving request failed: %s", exc)
        db.rollback()
        return False


def _session_items(context: dict[str, Any]) -> list[str]:
    raw = context.get("recent_product_ids")
    if not isinstance(raw, list):
        return []
    items = [str(value) for value in raw if isinstance(value, (str, int)) and str(value).strip()]
    return items[-SESSION_ITEMS_LIMIT:]


def _stored_history(db: Session, tenant_id: UUID, user_id: str) -> list[tuple[str, datetime]]:
    """The shopper's product events, oldest first (bounded to the latest ones)."""
    rows = db.execute(
        select(CustomerEvent.external_product_id, CustomerEvent.occurred_at)
        .where(
            CustomerEvent.tenant_id == tenant_id,
            CustomerEvent.user_id == user_id,
            CustomerEvent.external_product_id.is_not(None),
        )
        .order_by(CustomerEvent.occurred_at.desc(), CustomerEvent.created_at.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return [(str(product), occurred) for product, occurred in reversed(rows)]


def _dgsr_candidates(
    db: Session,
    tenant_id: UUID,
    version_id: UUID,
    directory,
    payload: RecommendationRequest,
    top_k: int,
) -> tuple[list[str], str]:
    """Stage 0 + Stage 1 for a DGSR version: encode the shopper, retrieve Top-K.

    Returns ``([], "popular_fallback")`` when nothing about the shopper is known
    to the model (no stored or session items in its vocabulary).
    """
    from graphrec_core.dgsr.serving import HistoryEvent, load_artifact

    artifact = load_artifact(directory)
    history = _stored_history(db, tenant_id, payload.user_id) if payload.user_id else []
    now = datetime.now(timezone.utc)
    history.extend((item, now) for item in _session_items(payload.context))
    seen = list(dict.fromkeys(item for item, _ in history))
    if not history:
        return [], "popular_fallback"

    user = artifact.user_index(payload.user_id) if payload.user_id else None
    session_items = _session_items(payload.context)
    if user is not None and not session_items and sorted(seen) == sorted(set(artifact.known_history(user))):
        # Nothing newer than the training graph: the notebook's exact serving path.
        encoded = artifact.encode_known(user)
    else:
        events = [
            HistoryEvent(index, int(occurred.timestamp()))
            for item, occurred in history
            if (index := artifact.item_index(item)) is not None
        ]
        if not events:
            return [], "popular_fallback"
        encoded = artifact.encode_history(events, user=user)

    exclude = list(dict.fromkeys([*(payload.exclude_product_ids or []), *seen]))
    try:
        candidates = retrieve_candidates(
            client=get_qdrant_client(),
            tenant_id=tenant_id,
            version_id=version_id,
            query_vector=encoded.query.tolist(),
            top_k=top_k,
            exclude_ids=exclude or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant retrieval failed; scoring the DGSR item table in-process: %s", exc)
        candidates = []
    if not candidates:
        excluded_rows = [index for item in exclude if (index := artifact.item_index(item)) is not None]
        candidates = [item for item, _ in artifact.top_k(artifact.score(encoded.query, excluded_rows), top_k)]
    return candidates, encoded.strategy


@router.post("/v1/recommendations", response_model=RecommendationResponse)
def get_recommendations(
    payload: RecommendationRequest,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Serve Top-N recommendations and record what it took to serve them."""
    principal.require_scope("recommendations:read")
    fingerprint = payload_hash(payload.model_dump(mode="json"))
    if payload.request_id:
        # Same tenant/request id serializes only its own concurrent retries.
        import hashlib
        lock = int.from_bytes(hashlib.sha256(f"{principal.tenant_id}:{payload.request_id}".encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        existing = db.get(RecommendationRecord, (principal.tenant_id, payload.request_id))
        if existing is not None:
            if existing.payload_hash != fingerprint:
                raise ApiError(409, "idempotency_conflict", "This request identifier was already used with different input.")
            returned_ids = {item["external_product_id"] for item in existing.response["items"]}
            eligible_ids = set(db.scalars(select(Product.external_id).where(
                Product.tenant_id == principal.tenant_id,
                Product.external_id.in_(returned_ids), *_servable(),
            )))
            if returned_ids != eligible_ids:
                raise ApiError(409, "recommendation_expired", "Catalog eligibility changed. Submit a new request identifier.")
            return RecommendationResponse.model_validate(existing.response)
    require_capacity(db, principal.tenant_id, "concurrent_recommendation_requests")
    require_capacity(db, principal.tenant_id, "recommendation_requests")
    require_capacity(db, principal.tenant_id, "requests_per_minute")
    started = time.perf_counter()
    try:
        response = _serve(payload, principal.tenant_id, db)
    except Exception:
        db.rollback()
        _record_serving_request(
            db,
            principal.tenant_id,
            model_version_id=None,
            strategy="none",
            outcome="error",
            fallback_used=False,
            item_count=0,
            latency_ms=_elapsed_ms(started),
        )
        raise
    created_at = datetime.now(timezone.utc)
    if payload.user_id:
        ensure_customers(db, principal.tenant_id, {payload.user_id})
    db.add(RecommendationRecord(tenant_id=principal.tenant_id, request_id=response.request_id,
        external_customer_id=payload.user_id, payload_hash=fingerprint,
        response=response.model_dump(mode="json"), created_at=created_at))
    for item in response.items:
        db.add(RecommendationResult(
            id=uuid4(), tenant_id=principal.tenant_id, request_id=response.request_id,
            external_product_id=item.external_product_id, rank_position=item.position,
            candidate_source=response.fallback_tier if response.fallback_used else "model_retrieval",
            strategy=response.strategy, created_at=created_at,
        ))
    recorded = _record_serving_request(
        db,
        principal.tenant_id,
        model_version_id=response.model_version_id,
        strategy=response.strategy,
        outcome="served",
        fallback_used=response.fallback_used,
        item_count=len(response.items),
        latency_ms=_elapsed_ms(started),
    )
    if not recorded:
        raise ApiError(503, "service_unavailable", "The recommendation could not be recorded. Retry with the same request identifier.", retryable=True)
    return response


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _serve(
    payload: RecommendationRequest, tenant_id: UUID, db: Session
) -> RecommendationResponse:
    settings = get_settings()

    # Resolve active model version
    active_model = db.execute(
        select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id, ModelVersion.status == "active"
        )
    ).scalar_one_or_none()

    # ----------------------------------------------------------------
    # Stage 1 — ANN Candidate Retrieval (Qdrant)
    # ----------------------------------------------------------------
    candidate_ids: list[str] = []
    strategy = "popular_fallback"

    directory = artifact_directory(active_model.artifact_uri) if active_model else None
    if active_model and directory is not None:
        try:
            candidate_ids, strategy = _dgsr_candidates(
                db, tenant_id, active_model.id, directory, payload, settings.qdrant_top_k
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("DGSR serving failed, falling back to popular: %s", exc)
    elif active_model and active_model.model_type != "dgsr":
        query_vec = _zero_query_vector(settings.qdrant_embedding_dim)

        try:
            candidate_ids = retrieve_candidates(
                client=get_qdrant_client(),
                tenant_id=tenant_id,
                version_id=active_model.id,
                query_vector=query_vec,
                top_k=settings.qdrant_top_k,
                exclude_ids=payload.exclude_product_ids or None,
            )
            strategy = "development_placeholder"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant retrieval failed, falling back to popular: %s", exc)

    # ----------------------------------------------------------------
    # Stage 2 — Eligibility Filtering (servable products in PostgreSQL)
    # ----------------------------------------------------------------
    if candidate_ids:
        # Keep only servable products whose external_id is in Qdrant results
        active_set: set[str] = set(
            db.execute(
                select(Product.external_id).where(
                    Product.tenant_id == tenant_id,
                    Product.external_id.in_(candidate_ids),
                    *_servable(),
                )
            ).scalars()
        )
        # Preserve Qdrant ranking order (Stage 3 proxy score)
        filtered_ids = list(dict.fromkeys(eid for eid in candidate_ids if eid in active_set))
    else:
        filtered_ids = []

    # ----------------------------------------------------------------
    # Stage 3 & 4 — Score proxy + deterministic ordering
    # ----------------------------------------------------------------
    # Qdrant already returns results in descending cosine similarity order.
    # Stable tie-break: sort equal-score items by external_id lexicographically.
    # Truncate to top_n.
    rules = load_rules(db, tenant_id)
    if rules and filtered_ids:
        top_ids = rerank(filtered_ids, _rule_meta(db, tenant_id, filtered_ids), rules,
                         top_n=payload.top_n, now=datetime.now(timezone.utc))
    else:
        top_ids = filtered_ids[: payload.top_n]

    # Fallback: if Qdrant returned nothing, pull most recent servable products
    fallback_used = False
    fallback_tier = "none"

    if not top_ids:
        if not payload.fallback_allowed:
            raise ApiError(
                503,
                "recommendation_unavailable",
                "Personalized recommendations are unavailable for this customer or session. Enable fallback or provide usable history.",
            )
        fallback_used = True
        fallback_tier = "tenant_popular"
        strategy = "popular_fallback"
        popularity = select(CustomerEvent.external_product_id.label("product_id"), func.count().label("events")).where(CustomerEvent.tenant_id == tenant_id).group_by(CustomerEvent.external_product_id).subquery()
        fallback_query = (
            select(Product.external_id)
            .outerjoin(popularity, popularity.c.product_id == Product.external_id)
            .where(Product.tenant_id == tenant_id, *_servable())
            .order_by(func.coalesce(popularity.c.events, 0).desc(), Product.external_id.asc())
            # Re-ranking needs a wider eligible pool than the final list (bounded).
            .limit(min(max(payload.top_n * 5, 50), 500) if rules else payload.top_n)
        )
        if payload.exclude_product_ids:
            fallback_query = fallback_query.where(
                Product.external_id.not_in(payload.exclude_product_ids)
            )
        top_ids = list(db.execute(fallback_query).scalars())
        if rules and top_ids:
            top_ids = rerank(top_ids, _rule_meta(db, tenant_id, top_ids), rules,
                             top_n=payload.top_n, now=datetime.now(timezone.utc))

    items = [
        RecommendationItem(external_product_id=eid, position=idx + 1)
        for idx, eid in enumerate(top_ids)
    ]

    return RecommendationResponse(
        request_id=payload.request_id or f"rec-{uuid4().hex}",
        items=items,
        model_version_id=active_model.id if active_model else None,
        strategy=strategy,
        fallback_used=fallback_used,
        fallback_tier=fallback_tier,
        applied_rules=rules.applied() if rules else [],
        rules_version=rules.version if rules else None,
    )


def _rule_meta(db: Session, tenant_id: UUID, ids: list[str]) -> dict[str, tuple[str | None, datetime]]:
    rows = db.execute(select(Product.external_id, Product.category, Product.created_at).where(
        Product.tenant_id == tenant_id, Product.external_id.in_(ids)))
    return {external_id: (category, created_at) for external_id, category, created_at in rows}


@router.post("/v1/recommendations/session", response_model=RecommendationResponse)
def get_session_recommendations(
    payload: RecommendationRequest,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    principal.require_scope("recommendations:read")
    return get_recommendations(payload, principal, db)


@router.post("/v1/feedback/impressions", response_model=FeedbackResponse)
def submit_impression_feedback(
    payload: ImpressionFeedback,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    principal.require_scope("events:write")
    return submit_feedback(db, principal.tenant_id, "impression", payload)


@router.post("/v1/feedback/clicks", response_model=FeedbackResponse)
def submit_click_feedback(
    payload: ClickFeedback,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    principal.require_scope("events:write")
    return submit_feedback(db, principal.tenant_id, "click", payload)


@router.post("/v1/feedback/conversions", response_model=FeedbackResponse)
def submit_conversion_feedback(
    payload: ConversionFeedback,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    principal.require_scope("events:write")
    return submit_feedback(db, principal.tenant_id, "conversion", payload)
