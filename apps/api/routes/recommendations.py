"""Recommendations route.

Admission (Redis slots / RPM / quota), idempotent replay and telemetry live
here; ranking is the glass-box pipeline in ``graphrec_core.serving``:
query building, multi-source retrieval, eligibility, scoring, MMR re-ranking
and the guarantee layer (see ``graphrec_core/serving/pipeline.py``).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import (
    Customer,
    ModelDeployment,
    ModelVersion,
    Product,
    ServingRequest,
    UsageEvent,
    RecommendationRecord,
    RecommendationResult,
)
from graphrec_core.database.session import get_db
from graphrec_core.recommendation_policy_service import load_rules
from graphrec_core.serving import pipeline as glassbox
from graphrec_core.serving.ranking import primary_reason, primary_source
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
from graphrec_core.capacity import effective_limits, serving_slots
from graphrec_core.usage.admission import get_admission
from graphrec_core.usage.limits import ledger_usage, month_bounds
from graphrec_core.vector_store.client import get_qdrant_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])


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


@router.post("/v1/recommendations", response_model=RecommendationResponse)
def get_recommendations(
    payload: RecommendationRequest,
    response: Response,
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
                Product.external_id.in_(returned_ids), *glassbox.servable(),
            )))
            if returned_ids != eligible_ids:
                raise ApiError(409, "recommendation_expired", "Catalog eligibility changed. Submit a new request identifier.")
            return RecommendationResponse.model_validate(existing.response)
    tenant_id = principal.tenant_id
    limits = effective_limits(db, tenant_id)
    if any(limits.get(k) is None for k in ("concurrent_recommendation_requests", "requests_per_minute",
                                            "recommendation_requests")):
        raise ApiError(503, "quota_unavailable", "Usage limits are temporarily unavailable.", retryable=True)
    # XR-F-08: an active deployment serves with the slots its scaled capacity
    # provides; without one the plan limit applies unchanged. D16: admission
    # state is shared in Redis, so every API replica sees the same slots.
    ready = db.scalar(select(ModelDeployment.ready_capacity).where(
        ModelDeployment.tenant_id == tenant_id, ModelDeployment.active_model_version_id.is_not(None)))
    slots = (serving_slots(limits, ready) if ready else None) or limits["concurrent_recommendation_requests"]
    admission = get_admission()
    period_start, period_end = month_bounds(datetime.now(timezone.utc))
    lease = admission.acquire_slot(tenant_id, slots)
    quota_taken = served = False
    try:
        rate = admission.check_rate(tenant_id, limits["requests_per_minute"])
        admission.consume_quota(tenant_id, "recommendation_requests", limits["recommendation_requests"],
                                period_start, period_end,
                                seed=lambda: ledger_usage(db, tenant_id, "recommendation_requests",
                                                          period_start, period_end))
        quota_taken = True
        result = _serve_and_record(payload, principal, db, fingerprint)
        response.headers.update(rate.headers())
        served = True
        return result
    finally:
        if quota_taken and not served:
            admission.refund_quota(tenant_id, "recommendation_requests", period_start)
        admission.release(lease)


def _serve_and_record(payload: RecommendationRequest, principal: AuthenticatedPrincipal, db: Session,
                      fingerprint: str) -> RecommendationResponse:
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
    # A-21b / BRULE-03: customers are created from accepted interactions only. A
    # recommendation for an id the tenant never sent an event for (cold start, or an
    # arbitrary string) links to no customer instead of creating one per request.
    known_customer = payload.user_id if payload.user_id and db.scalar(select(Customer.external_id).where(
        Customer.tenant_id == principal.tenant_id, Customer.external_id == payload.user_id)) else None
    db.add(RecommendationRecord(tenant_id=principal.tenant_id, request_id=response.request_id,
        external_customer_id=known_customer, payload_hash=fingerprint,
        response=response.model_dump(mode="json"), created_at=created_at))
    for item in response.items:
        db.add(RecommendationResult(
            id=uuid4(), tenant_id=principal.tenant_id, request_id=response.request_id,
            external_product_id=item.external_product_id, rank_position=item.position,
            candidate_source=(item.sources[0] if item.sources else
                              response.fallback_tier if response.fallback_used else "model_retrieval")[:48],
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


def _serve(payload: RecommendationRequest, tenant_id: UUID, db: Session) -> RecommendationResponse:
    settings = get_settings()
    active_model = db.execute(
        select(ModelVersion).where(ModelVersion.tenant_id == tenant_id, ModelVersion.status == "active")
    ).scalar_one_or_none()
    rules = load_rules(db, tenant_id)
    # Looked up at call time so tests (and chaos drills) can replace the client.
    outcome = glassbox.run(db, tenant_id, payload, active_model, settings, rules,
                           qdrant_factory=lambda: get_qdrant_client())
    if not outcome.items and not payload.fallback_allowed:
        raise ApiError(
            503,
            "recommendation_unavailable",
            "Personalized recommendations are unavailable for this customer or session. Enable fallback or provide usable history.",
        )
    items = [
        RecommendationItem(
            external_product_id=c.external_id,
            position=index + 1,
            reason=primary_reason(c),
            sources=[primary_source(c), *[s for s in c.sources if s != primary_source(c)]],
            anchor_product_id=c.anchor_id if primary_reason(c) == "because_you_viewed" else None,
            score=round(c.final, 4) if c.final else None,
        )
        for index, c in enumerate(outcome.items)
    ]
    served_by_model = outcome.model_served and active_model is not None
    return RecommendationResponse(
        request_id=payload.request_id or f"rec-{uuid4().hex}",
        items=items,
        model_version_id=active_model.id if served_by_model else None,
        active_model_version_id=active_model.id if active_model else None,
        strategy=outcome.strategy,
        fallback_used=outcome.fallback_used,
        fallback_tier=outcome.fallback_tier,
        applied_rules=rules.applied() if rules else [],
        rules_version=rules.version if rules else None,
        pipeline=glassbox.PIPELINE_NAME,
        diversity=outcome.diversity,
        explain=outcome.explain if payload.explain else None,
    )


@router.post("/v1/recommendations/session", response_model=RecommendationResponse)
def get_session_recommendations(
    payload: RecommendationRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    principal.require_scope("recommendations:read")
    return get_recommendations(payload, response, principal, db)


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
