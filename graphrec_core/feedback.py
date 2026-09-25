"""Validate and persist feedback against the exact tenant-owned served result."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from graphrec_core.database.models import RecommendationFeedback, RecommendationRecord
from graphrec_core.errors import ApiError
from graphrec_core.schemas.recommendations import FeedbackResponse


def payload_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def submit_feedback(db: Session, tenant_id: UUID, kind: str, payload) -> FeedbackResponse:
    body = payload.model_dump(mode="json")
    # Server-generated default time is not part of a client's replay identity.
    identity = payload.model_dump(mode="json", exclude_unset=True)
    fingerprint = payload_hash({"kind": kind, **identity})
    previous = db.get(RecommendationFeedback, (tenant_id, payload.event_id))
    if previous is not None:
        if previous.payload_hash != fingerprint:
            raise ApiError(409, "idempotency_conflict", "This feedback identifier was already used for a different submission.")
        return FeedbackResponse(event_id=previous.event_id, feedback_type=previous.feedback_type, accepted=True, duplicate=True, received_at=previous.received_at)
    record = db.get(RecommendationRecord, (tenant_id, payload.request_id))
    if record is None:
        raise ApiError(404, "resource_not_found", "Recommendation result not found.")
    allowed = {(item["external_product_id"], item["position"]) for item in record.response["items"]}
    submitted = [(item.external_product_id, item.position) for item in payload.items] if kind == "impression" else [(payload.external_product_id, payload.position)]
    if not submitted or any((product, position) not in allowed if position is not None else not any(product == item[0] for item in allowed) for product, position in submitted):
        raise ApiError(422, "invalid_feedback_reference", "Feedback products and positions must match the referenced recommendation.")
    impression_id = getattr(payload, "impression_event_id", None)
    if impression_id:
        impression = db.get(RecommendationFeedback, (tenant_id, impression_id))
        if impression is None or impression.feedback_type != "impression" or impression.request_id != payload.request_id:
            raise ApiError(422, "invalid_feedback_reference", "The impression does not belong to this recommendation.")
    now = datetime.now(timezone.utc)
    saved = db.execute(insert(RecommendationFeedback).values(tenant_id=tenant_id, event_id=payload.event_id,
        request_id=payload.request_id, feedback_type=kind, payload_hash=fingerprint, payload=body, received_at=now)
        .on_conflict_do_nothing(index_elements=["tenant_id", "event_id"]).returning(RecommendationFeedback.event_id)).scalar_one_or_none()
    if saved is None:
        previous = db.scalar(select(RecommendationFeedback).where(RecommendationFeedback.tenant_id == tenant_id, RecommendationFeedback.event_id == payload.event_id))
        if previous.payload_hash != fingerprint:
            raise ApiError(409, "idempotency_conflict", "This feedback identifier was already used for a different submission.")
        now = previous.received_at
    db.commit()
    return FeedbackResponse(event_id=payload.event_id, feedback_type=kind, accepted=True, duplicate=saved is None, received_at=now)
