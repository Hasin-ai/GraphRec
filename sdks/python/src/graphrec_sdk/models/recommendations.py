from __future__ import annotations

from datetime import datetime
from typing import Iterator, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel

__all__ = ["FeedbackReceipt", "RecommendationItem", "Recommendations"]


class RecommendationItem(GraphRecModel):
    external_product_id: str
    #: One-based rank.
    position: int


class Recommendations(GraphRecModel):
    """Top-N result of ``POST /v1/recommendations`` (or ``/session``).

    Keep ``request_id`` - impression, click and conversion feedback must
    reference it.
    """

    request_id: str
    items: List[RecommendationItem] = Field(default_factory=list)
    model_version_id: Optional[UUID] = None
    #: ``personalized`` or ``popular_fallback``.
    strategy: str
    fallback_used: bool
    #: ``none``, ``tenant_popular``...
    fallback_tier: str

    @property
    def product_ids(self) -> List[str]:
        return [item.external_product_id for item in self.items]

    @property
    def is_personalized(self) -> bool:
        return not self.fallback_used

    def position_of(self, product_id: str) -> Optional[int]:
        return next(
            (item.position for item in self.items if item.external_product_id == product_id), None
        )

    def __iter__(self) -> Iterator[RecommendationItem]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


class FeedbackReceipt(GraphRecModel):
    event_id: str
    #: ``impression``, ``click`` or ``conversion``.
    feedback_type: str
    accepted: bool
    duplicate: bool
    received_at: datetime
