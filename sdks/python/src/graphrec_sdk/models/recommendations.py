from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel

__all__ = ["FeedbackReceipt", "RecommendationItem", "Recommendations"]


class RecommendationItem(GraphRecModel):
    external_product_id: str
    #: One-based rank.
    position: int
    #: ``because_you_viewed``, ``picked_for_you``, ``popular_in_category``,
    #: ``trending`` or ``recently_recommended`` (glass-box pipeline only).
    reason: Optional[str] = None
    #: Retrieval sources that proposed the item, primary first.
    sources: List[str] = Field(default_factory=list)
    #: The recently viewed product behind a ``because_you_viewed`` item.
    anchor_product_id: Optional[str] = None
    #: Blended relevance in [0, 1].
    score: Optional[float] = None


class Recommendations(GraphRecModel):
    """Top-N result of ``POST /v1/recommendations`` (or ``/session``).

    Keep ``request_id`` - impression, click and conversion feedback must
    reference it.
    """

    request_id: str
    items: List[RecommendationItem] = Field(default_factory=list)
    #: Version that produced the ranking; ``None`` when a fallback served the request.
    model_version_id: Optional[UUID] = None
    #: The tenant's active version at serving time, whether or not it served.
    active_model_version_id: Optional[UUID] = None
    #: ``personalized`` or ``popular_fallback``.
    strategy: str
    fallback_used: bool
    #: ``none``, ``tenant_popular``...
    fallback_tier: str
    #: Re-ranking rules from the tenant's recommendation policy that changed this list.
    applied_rules: List[str] = Field(default_factory=list)
    #: Version of the recommendation policy in force; ``None`` before one is configured.
    rules_version: Optional[int] = None
    #: Serving pipeline that produced the list, e.g. ``glassbox-v1``.
    pipeline: Optional[str] = None
    #: MMR diversity applied to this list.
    diversity: Optional[float] = None
    #: Per-stage trace and per-candidate scores when requested with ``explain=True``.
    explain: Optional[Dict[str, Any]] = None

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
