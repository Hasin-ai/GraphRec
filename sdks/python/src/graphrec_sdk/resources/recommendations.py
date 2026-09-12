from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence, Union, cast

from .._ids import new_id
from .._serialization import to_jsonable, utcnow
from ..errors import InputValidationError
from ..models.recommendations import FeedbackReceipt, RecommendationItem, Recommendations
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncFeedback", "AsyncRecommendationsResource", "Feedback", "RecommendationsResource"]

MAX_TOP_N = 100
MAX_EXCLUSIONS = 200

RecommendationRef = Union[Recommendations, str]
ItemLike = Union[RecommendationItem, Mapping[str, Any], str]


def _recommendation_body(
    *,
    user_id: Optional[str],
    top_n: int,
    context: Optional[Mapping[str, Any]],
    exclude_product_ids: Optional[Sequence[str]],
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= MAX_TOP_N:
        raise InputValidationError(f"top_n must be an integer between 1 and {MAX_TOP_N}")
    merged: Dict[str, Any] = dict(context or {})
    if session:
        merged.update(session)
    body: Dict[str, Any] = {"top_n": top_n, "context": merged}
    if user_id is not None:
        body["user_id"] = user_id
    if exclude_product_ids:
        unique = list(dict.fromkeys(str(pid) for pid in exclude_product_ids))
        if len(unique) > MAX_EXCLUSIONS:
            raise InputValidationError(f"At most {MAX_EXCLUSIONS} product IDs can be excluded")
        body["exclude_product_ids"] = unique
    return body


def _session_context(
    session_id: str, recent_product_ids: Optional[Sequence[str]]
) -> Dict[str, Any]:
    if not session_id:
        raise InputValidationError("session_id must be a non-empty string")
    session: Dict[str, Any] = {"session_id": session_id}
    if recent_product_ids:
        session["recent_product_ids"] = [str(pid) for pid in recent_product_ids]
    return session


def _request_id(ref: RecommendationRef) -> str:
    request_id = ref.request_id if isinstance(ref, Recommendations) else ref
    if not request_id:
        raise InputValidationError("A recommendation request_id is required for feedback")
    return request_id


def _items(ref: RecommendationRef, items: Optional[Sequence[ItemLike]]) -> list[Dict[str, Any]]:
    if items is None:
        if not isinstance(ref, Recommendations):
            raise InputValidationError(
                "Pass the Recommendations object, or items=[...] together with a request_id"
            )
        return [item.model_dump(include={"external_product_id", "position"}) for item in ref.items]
    normalized: list[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, str):
            normalized.append({"external_product_id": item, "position": index})
        elif isinstance(item, RecommendationItem):
            normalized.append(item.model_dump(include={"external_product_id", "position"}))
        else:
            try:
                normalized.append(
                    {
                        "external_product_id": str(item["external_product_id"]),
                        "position": int(item["position"]),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise InputValidationError(
                    "Feedback items need 'external_product_id' and 'position'"
                ) from exc
    return normalized


def _position(
    ref: RecommendationRef, product_id: str, position: Optional[int], required: bool
) -> Optional[int]:
    if position is not None:
        if position < 1:
            raise InputValidationError("position is one-based and must be >= 1")
        return position
    if isinstance(ref, Recommendations):
        found = ref.position_of(product_id)
        if found is None:
            raise InputValidationError(
                f"Product {product_id!r} is not part of recommendation {ref.request_id!r}"
            )
        return found
    if required:
        raise InputValidationError("position is required when passing a request_id string")
    return None


def _feedback_body(
    ref: RecommendationRef,
    event_id: Optional[str],
    occurred_at: Optional[datetime],
    context: Optional[Mapping[str, Any]],
    **fields: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "event_id": event_id or new_id("fbk"),
        "request_id": _request_id(ref),
        "context": dict(context or {}),
        **{key: value for key, value in fields.items() if value is not None},
    }
    body["occurred_at"] = occurred_at if occurred_at is not None else utcnow()
    return cast(Dict[str, Any], to_jsonable(body))


class RecommendationsResource(SyncResource):
    """Top-N recommendations. Scope: ``recommendations:read``."""

    def get(
        self,
        *,
        user_id: Optional[str] = None,
        top_n: int = 10,
        context: Optional[Mapping[str, Any]] = None,
        exclude_product_ids: Optional[Sequence[str]] = None,
    ) -> Recommendations:
        """Recommendations for an identified customer (``POST /v1/recommendations``).

        ``exclude_product_ids`` removes items such as the product on the current
        page or the cart contents. Check ``fallback_used`` to know whether the
        result is personalized.
        """

        return cast(
            Recommendations,
            self._client.request(
                "recommendations.get",
                json=_recommendation_body(
                    user_id=user_id,
                    top_n=top_n,
                    context=context,
                    exclude_product_ids=exclude_product_ids,
                ),
                cast_to=Recommendations,
            ),
        )

    def for_session(
        self,
        session_id: str,
        *,
        recent_product_ids: Optional[Sequence[str]] = None,
        user_id: Optional[str] = None,
        top_n: int = 10,
        context: Optional[Mapping[str, Any]] = None,
        exclude_product_ids: Optional[Sequence[str]] = None,
    ) -> Recommendations:
        """Session-aware recommendations for anonymous shoppers.

        ``POST /v1/recommendations/session``.

        ``session_id`` and ``recent_product_ids`` are sent in ``context``.
        """

        return cast(
            Recommendations,
            self._client.request(
                "recommendations.for_session",
                json=_recommendation_body(
                    user_id=user_id,
                    top_n=top_n,
                    context=context,
                    exclude_product_ids=exclude_product_ids,
                    session=_session_context(session_id, recent_product_ids),
                ),
                cast_to=Recommendations,
            ),
        )


class AsyncRecommendationsResource(AsyncResource):
    async def get(
        self,
        *,
        user_id: Optional[str] = None,
        top_n: int = 10,
        context: Optional[Mapping[str, Any]] = None,
        exclude_product_ids: Optional[Sequence[str]] = None,
    ) -> Recommendations:
        """Async variant of :meth:`RecommendationsResource.get`."""

        return cast(
            Recommendations,
            await self._client.request(
                "recommendations.get",
                json=_recommendation_body(
                    user_id=user_id,
                    top_n=top_n,
                    context=context,
                    exclude_product_ids=exclude_product_ids,
                ),
                cast_to=Recommendations,
            ),
        )

    async def for_session(
        self,
        session_id: str,
        *,
        recent_product_ids: Optional[Sequence[str]] = None,
        user_id: Optional[str] = None,
        top_n: int = 10,
        context: Optional[Mapping[str, Any]] = None,
        exclude_product_ids: Optional[Sequence[str]] = None,
    ) -> Recommendations:
        """Async variant of :meth:`RecommendationsResource.for_session`."""

        return cast(
            Recommendations,
            await self._client.request(
                "recommendations.for_session",
                json=_recommendation_body(
                    user_id=user_id,
                    top_n=top_n,
                    context=context,
                    exclude_product_ids=exclude_product_ids,
                    session=_session_context(session_id, recent_product_ids),
                ),
                cast_to=Recommendations,
            ),
        )


class Feedback(SyncResource):
    """Impression, click and conversion feedback. Every call is deduplicated by ``event_id``."""

    def impression(
        self,
        recommendation: RecommendationRef,
        *,
        items: Optional[Sequence[ItemLike]] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> FeedbackReceipt:
        """Report that recommendations were shown (``POST /v1/feedback/impressions``).

        Pass the :class:`~graphrec_sdk.models.Recommendations` object, or a
        ``request_id`` plus ``items`` (product IDs in display order are fine).
        """

        return cast(
            FeedbackReceipt,
            self._client.request(
                "feedback.impression",
                json=_feedback_body(
                    recommendation,
                    event_id,
                    occurred_at,
                    context,
                    items=_items(recommendation, items),
                ),
                cast_to=FeedbackReceipt,
            ),
        )

    def click(
        self,
        recommendation: RecommendationRef,
        product_id: str,
        *,
        position: Optional[int] = None,
        impression_event_id: Optional[str] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> FeedbackReceipt:
        """Report a click on a recommended product (``POST /v1/feedback/clicks``)."""

        return cast(
            FeedbackReceipt,
            self._client.request(
                "feedback.click",
                json=_feedback_body(
                    recommendation,
                    event_id,
                    occurred_at,
                    context,
                    external_product_id=product_id,
                    position=_position(recommendation, product_id, position, required=True),
                    impression_event_id=impression_event_id,
                ),
                cast_to=FeedbackReceipt,
            ),
        )

    def conversion(
        self,
        recommendation: RecommendationRef,
        product_id: str,
        *,
        value: Optional[Union[Decimal, float, int, str]] = None,
        position: Optional[int] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> FeedbackReceipt:
        """Report a purchase attributed to a recommendation (``POST /v1/feedback/conversions``)."""

        return cast(
            FeedbackReceipt,
            self._client.request(
                "feedback.conversion",
                json=_feedback_body(
                    recommendation,
                    event_id,
                    occurred_at,
                    context,
                    external_product_id=product_id,
                    position=_position(recommendation, product_id, position, required=False),
                    value=_money(value),
                ),
                cast_to=FeedbackReceipt,
            ),
        )


class AsyncFeedback(AsyncResource):
    async def impression(
        self,
        recommendation: RecommendationRef,
        *,
        items: Optional[Sequence[ItemLike]] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> FeedbackReceipt:
        """Async variant of :meth:`Feedback.impression`."""

        return cast(
            FeedbackReceipt,
            await self._client.request(
                "feedback.impression",
                json=_feedback_body(
                    recommendation,
                    event_id,
                    occurred_at,
                    context,
                    items=_items(recommendation, items),
                ),
                cast_to=FeedbackReceipt,
            ),
        )

    async def click(
        self,
        recommendation: RecommendationRef,
        product_id: str,
        *,
        position: Optional[int] = None,
        impression_event_id: Optional[str] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> FeedbackReceipt:
        """Async variant of :meth:`Feedback.click`."""

        return cast(
            FeedbackReceipt,
            await self._client.request(
                "feedback.click",
                json=_feedback_body(
                    recommendation,
                    event_id,
                    occurred_at,
                    context,
                    external_product_id=product_id,
                    position=_position(recommendation, product_id, position, required=True),
                    impression_event_id=impression_event_id,
                ),
                cast_to=FeedbackReceipt,
            ),
        )

    async def conversion(
        self,
        recommendation: RecommendationRef,
        product_id: str,
        *,
        value: Optional[Union[Decimal, float, int, str]] = None,
        position: Optional[int] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> FeedbackReceipt:
        """Async variant of :meth:`Feedback.conversion`."""

        return cast(
            FeedbackReceipt,
            await self._client.request(
                "feedback.conversion",
                json=_feedback_body(
                    recommendation,
                    event_id,
                    occurred_at,
                    context,
                    external_product_id=product_id,
                    position=_position(recommendation, product_id, position, required=False),
                    value=_money(value),
                ),
                cast_to=FeedbackReceipt,
            ),
        )


def _money(value: Optional[Union[Decimal, float, int, str]]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except ArithmeticError as exc:
        raise InputValidationError(f"Invalid conversion value {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise InputValidationError("Conversion value must be a non-negative number")
    return amount
