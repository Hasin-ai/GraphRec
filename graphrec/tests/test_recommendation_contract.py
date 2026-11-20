from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphrec_core.schemas.recommendations import RecommendationRequest


@pytest.mark.parametrize(
    ("payload", "message"),
    [({}, "customer ID or usable session context"),
     ({"context": {"surface": "cart"}}, "customer ID or usable session context"),
     ({"user_id": "  "}, "Customer ID cannot be blank"),
     ({"context": {"session_id": "  "}}, "customer ID or usable session context")],
)
def test_recommendation_requires_customer_or_usable_session(payload: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RecommendationRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [{"user_id": "shopper"}, {"context": {"session_id": "session-1"}}, {"context": {"recent_product_ids": ["sku-1"]}}],
)
def test_recommendation_accepts_identified_or_anonymous_context(payload: dict) -> None:
    request = RecommendationRequest.model_validate(payload)
    assert request.fallback_allowed is True
    assert RecommendationRequest.model_validate({**payload, "fallback_allowed": False}).fallback_allowed is False
