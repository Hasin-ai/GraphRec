"""A-13: typed, bounded serving hints that keep the stored request shape."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphrec_core.schemas.recommendations import RecommendationRequest


def test_known_hints_are_typed_and_unset_hints_are_omitted():
    request = RecommendationRequest(context={"session_id": "s-1", "page": "pdp"})
    assert request.context.session_id == "s-1"
    assert request.model_dump(mode="json")["context"] == {"session_id": "s-1", "page": "pdp"}


def test_oversized_session_history_is_rejected():
    with pytest.raises(ValidationError):
        RecommendationRequest(context={"session_id": "s", "recent_product_ids": ["p"] * 201})


def test_wrong_hint_type_is_rejected():
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id="u", context={"recent_product_ids": "not-a-list"})
