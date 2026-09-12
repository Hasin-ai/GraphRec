"""Recommendation widgets with automatic feedback bookkeeping.

::

    from graphrec_sdk.ecommerce import RecommendationSession

    recs_ui = RecommendationSession(client)

    # product page: recommend and record the impression in one call
    recs = recs_ui.recommend(user_id="customer-42", top_n=8, exclude_product_ids=["sku-123"])

    # later, when the shopper clicks / buys a recommended item
    recs_ui.click(recs, "sku-777")
    recs_ui.convert(recs, "sku-777", value="49.90")

Clicks are linked to the impression automatically and positions are looked up
from the original response. Store ``recs.request_id`` (e.g. in the page or the
cart line) if the click happens in another process, then call
``client.feedback.click(request_id, product_id, position=...)`` directly.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Sequence, Union

from ..models.recommendations import FeedbackReceipt, Recommendations

if TYPE_CHECKING:
    from .._client import AsyncGraphRec, GraphRec

__all__ = ["AsyncRecommendationSession", "RecommendationSession"]

Money = Union[Decimal, float, int, str]


class _ImpressionIndex:
    """Bounded map ``request_id -> impression event_id``."""

    def __init__(self, capacity: int) -> None:
        self.capacity = max(capacity, 1)
        self._data: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, request_id: str, event_id: str) -> None:
        with self._lock:
            self._data[request_id] = event_id
            self._data.move_to_end(request_id)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)

    def get(self, request_id: str) -> Optional[str]:
        with self._lock:
            return self._data.get(request_id)


def _request_args(
    user_id: Optional[str],
    top_n: int,
    context: Optional[Mapping[str, Any]],
    exclude_product_ids: Optional[Sequence[str]],
) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "top_n": top_n,
        "context": context,
        "exclude_product_ids": exclude_product_ids,
    }


class RecommendationSession:
    """Fetch recommendations and send impression/click/conversion feedback consistently."""

    def __init__(
        self, client: GraphRec, *, auto_impression: bool = True, remember: int = 1_000
    ) -> None:
        self._client = client
        self.auto_impression = auto_impression
        self._impressions = _ImpressionIndex(remember)

    def recommend(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        recent_product_ids: Optional[Sequence[str]] = None,
        top_n: int = 10,
        context: Optional[Mapping[str, Any]] = None,
        exclude_product_ids: Optional[Sequence[str]] = None,
    ) -> Recommendations:
        """Personalized results for ``user_id``, or session-based when ``session_id`` is given."""

        args = _request_args(user_id, top_n, context, exclude_product_ids)
        if session_id is not None:
            recs = self._client.recommendations.for_session(
                session_id, recent_product_ids=recent_product_ids, **args
            )
        else:
            recs = self._client.recommendations.get(**args)
        if self.auto_impression and recs.items:
            self.impression(recs)
        return recs

    def impression(self, recs: Recommendations, **options: Any) -> FeedbackReceipt:
        receipt = self._client.feedback.impression(recs, **options)
        self._impressions.put(recs.request_id, receipt.event_id)
        return receipt

    def click(self, recs: Recommendations, product_id: str, **options: Any) -> FeedbackReceipt:
        options.setdefault("impression_event_id", self._impressions.get(recs.request_id))
        return self._client.feedback.click(recs, product_id, **options)

    def convert(
        self,
        recs: Recommendations,
        product_id: str,
        *,
        value: Optional[Money] = None,
        **options: Any,
    ) -> FeedbackReceipt:
        return self._client.feedback.conversion(recs, product_id, value=value, **options)


class AsyncRecommendationSession:
    """Async variant of :class:`RecommendationSession`."""

    def __init__(
        self, client: AsyncGraphRec, *, auto_impression: bool = True, remember: int = 1_000
    ) -> None:
        self._client = client
        self.auto_impression = auto_impression
        self._impressions = _ImpressionIndex(remember)

    async def recommend(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        recent_product_ids: Optional[Sequence[str]] = None,
        top_n: int = 10,
        context: Optional[Mapping[str, Any]] = None,
        exclude_product_ids: Optional[Sequence[str]] = None,
    ) -> Recommendations:
        args = _request_args(user_id, top_n, context, exclude_product_ids)
        if session_id is not None:
            recs = await self._client.recommendations.for_session(
                session_id, recent_product_ids=recent_product_ids, **args
            )
        else:
            recs = await self._client.recommendations.get(**args)
        if self.auto_impression and recs.items:
            await self.impression(recs)
        return recs

    async def impression(self, recs: Recommendations, **options: Any) -> FeedbackReceipt:
        receipt = await self._client.feedback.impression(recs, **options)
        self._impressions.put(recs.request_id, receipt.event_id)
        return receipt

    async def click(
        self, recs: Recommendations, product_id: str, **options: Any
    ) -> FeedbackReceipt:
        options.setdefault("impression_event_id", self._impressions.get(recs.request_id))
        return await self._client.feedback.click(recs, product_id, **options)

    async def convert(
        self,
        recs: Recommendations,
        product_id: str,
        *,
        value: Optional[Money] = None,
        **options: Any,
    ) -> FeedbackReceipt:
        return await self._client.feedback.conversion(recs, product_id, value=value, **options)
