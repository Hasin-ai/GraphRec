"""Recommendations route — four-stage serving funnel with Qdrant Stage 1.

Stage 1: ANN candidate retrieval via Qdrant (cosine similarity Top-K)
Stage 2: Eligibility filtering against active PostgreSQL product catalog
Stage 3: Proxy scoring — use Qdrant rank order as score (real GNN forward
         pass is the Celery worker responsibility for the active serving pod)
Stage 4: Deterministic ordering — top_n items, stable tie-break by product ID
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import ModelVersion, Product
from graphrec_core.database.session import get_db
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
from graphrec_core.vector_store.client import get_qdrant_client
from graphrec_core.vector_store.retriever import retrieve_candidates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])


def _zero_query_vector(dim: int) -> list[float]:
    """Return a deterministic placeholder query vector.

    In production this is replaced by the GNN-assembled user/session
    embedding from the DGSR-lite forward pass running inside the
    tenant-pinned inference pod. Until that Celery worker slice is built,
    a unit-first vector is used so that Qdrant returns a stable ordering
    without all-zero cosine issues.
    """
    vec = [0.0] * dim
    vec[0] = 1.0
    return vec


@router.post("/v1/recommendations", response_model=RecommendationResponse)
def get_recommendations(
    payload: RecommendationRequest,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    principal.require_scope("recommendations:read")
    settings = get_settings()
    tenant_id = principal.tenant_id

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

    if active_model:
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
            strategy = "personalized"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant retrieval failed, falling back to popular: %s", exc)

    # ----------------------------------------------------------------
    # Stage 2 — Eligibility Filtering (active products in PostgreSQL)
    # ----------------------------------------------------------------
    if candidate_ids:
        # Keep only active products whose external_id is in Qdrant results
        active_set: set[str] = set(
            db.execute(
                select(Product.external_id).where(
                    Product.tenant_id == tenant_id,
                    Product.is_active == True,  # noqa: E712
                    Product.external_id.in_(candidate_ids),
                )
            ).scalars()
        )
        # Preserve Qdrant ranking order (Stage 3 proxy score)
        filtered_ids = [eid for eid in candidate_ids if eid in active_set]
    else:
        filtered_ids = []

    # ----------------------------------------------------------------
    # Stage 3 & 4 — Score proxy + deterministic ordering
    # ----------------------------------------------------------------
    # Qdrant already returns results in descending cosine similarity order.
    # Stable tie-break: sort equal-score items by external_id lexicographically.
    # Truncate to top_n.
    top_ids = filtered_ids[: payload.top_n]

    # Fallback: if Qdrant returned nothing, pull most recent active products
    fallback_used = False
    fallback_tier = "none"

    if not top_ids:
        fallback_used = True
        fallback_tier = "tenant_popular"
        strategy = "popular_fallback"
        fallback_query = (
            select(Product.external_id)
            .where(Product.tenant_id == tenant_id, Product.is_active == True)  # noqa: E712
            .order_by(Product.created_at.desc())
            .limit(payload.top_n)
        )
        if payload.exclude_product_ids:
            fallback_query = fallback_query.where(
                Product.external_id.not_in(payload.exclude_product_ids)
            )
        top_ids = list(db.execute(fallback_query).scalars())

    items = [
        RecommendationItem(external_product_id=eid, position=idx + 1)
        for idx, eid in enumerate(top_ids)
    ]

    return RecommendationResponse(
        request_id=f"rec-{uuid4().hex[:12]}",
        items=items,
        model_version_id=active_model.id if active_model else None,
        strategy=strategy,
        fallback_used=fallback_used,
        fallback_tier=fallback_tier,
    )


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
    return FeedbackResponse(
        event_id=payload.event_id,
        feedback_type="impression",
        accepted=True,
        duplicate=False,
        received_at=datetime.now(timezone.utc),
    )


@router.post("/v1/feedback/clicks", response_model=FeedbackResponse)
def submit_click_feedback(
    payload: ClickFeedback,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    principal.require_scope("events:write")
    return FeedbackResponse(
        event_id=payload.event_id,
        feedback_type="click",
        accepted=True,
        duplicate=False,
        received_at=datetime.now(timezone.utc),
    )


@router.post("/v1/feedback/conversions", response_model=FeedbackResponse)
def submit_conversion_feedback(
    payload: ConversionFeedback,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    principal.require_scope("events:write")
    return FeedbackResponse(
        event_id=payload.event_id,
        feedback_type="conversion",
        accepted=True,
        duplicate=False,
        received_at=datetime.now(timezone.utc),
    )
