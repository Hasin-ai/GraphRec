"""The hot path, on the data plane.

Both calls are retried on a transient failure, which is safe because
`request_id` is the idempotency key (`graphrec/domain/serving/recommend.py` keys
the request row on it) — so a retry after a timeout is confirmed rather than
counted twice, and the recommendation you eventually get is the one your
feedback will refer to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._spec import CallOptions, Spec
from .._validate import build, parse
from ..models import (
    CustomerRecommendationRequest,
    RecentEvent,
    RecommendationResponse,
    SessionRecommendationRequest,
)

if TYPE_CHECKING:
    from ..transport import AsyncTransport, Transport

_RecentEventArg = RecentEvent | dict[str, Any]


def _body(request: CustomerRecommendationRequest | SessionRecommendationRequest) -> dict[str, Any]:
    return request.model_dump(mode="json", exclude_none=True)


def for_customer_spec(
    *,
    request_id: str,
    customer_id: str,
    session_id: str | None = None,
    top_n: int | None = None,
    recent_events: list[_RecentEventArg] | None = None,
    exclude_product_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
    allow_fallback: bool | None = None,
    options: CallOptions | None = None,
) -> Spec:
    request = build(
        CustomerRecommendationRequest,
        "A recommendation request",
        request_id=request_id,
        customer_id=customer_id,
        session_id=session_id,
        top_n=top_n,
        recent_events=recent_events,
        exclude_product_ids=exclude_product_ids,
        context=context,
        allow_fallback=allow_fallback,
    )
    return Spec("POST", "/v1/recommendations", _body(request), idempotent=True, options=options)


def for_session_spec(
    *,
    request_id: str,
    session_id: str,
    top_n: int | None = None,
    recent_events: list[_RecentEventArg] | None = None,
    exclude_product_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
    allow_fallback: bool | None = None,
    options: CallOptions | None = None,
) -> Spec:
    request = build(
        SessionRecommendationRequest,
        "A session recommendation request",
        request_id=request_id,
        session_id=session_id,
        top_n=top_n,
        recent_events=recent_events,
        exclude_product_ids=exclude_product_ids,
        context=context,
        allow_fallback=allow_fallback,
    )
    return Spec(
        "POST", "/v1/recommendations/session", _body(request), idempotent=True, options=options
    )


def decode(payload: object) -> RecommendationResponse:
    return parse(RecommendationResponse, payload)


class Recommendations:
    """Recommendations, blocking."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def for_customer(
        self,
        *,
        request_id: str,
        customer_id: str,
        session_id: str | None = None,
        top_n: int | None = None,
        recent_events: list[_RecentEventArg] | None = None,
        exclude_product_ids: list[str] | None = None,
        context: dict[str, Any] | None = None,
        allow_fallback: bool | None = None,
        options: CallOptions | None = None,
    ) -> RecommendationResponse:
        """Recommendations for a known customer. `session_id` narrows it to one visit."""
        return decode(
            self._transport.send(
                for_customer_spec(
                    request_id=request_id,
                    customer_id=customer_id,
                    session_id=session_id,
                    top_n=top_n,
                    recent_events=recent_events,
                    exclude_product_ids=exclude_product_ids,
                    context=context,
                    allow_fallback=allow_fallback,
                    options=options,
                )
            )
        )

    def for_session(
        self,
        *,
        request_id: str,
        session_id: str,
        top_n: int | None = None,
        recent_events: list[_RecentEventArg] | None = None,
        exclude_product_ids: list[str] | None = None,
        context: dict[str, Any] | None = None,
        allow_fallback: bool | None = None,
        options: CallOptions | None = None,
    ) -> RecommendationResponse:
        """Recommendations for an anonymous visit, with no customer to name."""
        return decode(
            self._transport.send(
                for_session_spec(
                    request_id=request_id,
                    session_id=session_id,
                    top_n=top_n,
                    recent_events=recent_events,
                    exclude_product_ids=exclude_product_ids,
                    context=context,
                    allow_fallback=allow_fallback,
                    options=options,
                )
            )
        )


class AsyncRecommendations:
    """Recommendations, awaited."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def for_customer(
        self,
        *,
        request_id: str,
        customer_id: str,
        session_id: str | None = None,
        top_n: int | None = None,
        recent_events: list[_RecentEventArg] | None = None,
        exclude_product_ids: list[str] | None = None,
        context: dict[str, Any] | None = None,
        allow_fallback: bool | None = None,
        options: CallOptions | None = None,
    ) -> RecommendationResponse:
        """Recommendations for a known customer. `session_id` narrows it to one visit."""
        return decode(
            await self._transport.send(
                for_customer_spec(
                    request_id=request_id,
                    customer_id=customer_id,
                    session_id=session_id,
                    top_n=top_n,
                    recent_events=recent_events,
                    exclude_product_ids=exclude_product_ids,
                    context=context,
                    allow_fallback=allow_fallback,
                    options=options,
                )
            )
        )

    async def for_session(
        self,
        *,
        request_id: str,
        session_id: str,
        top_n: int | None = None,
        recent_events: list[_RecentEventArg] | None = None,
        exclude_product_ids: list[str] | None = None,
        context: dict[str, Any] | None = None,
        allow_fallback: bool | None = None,
        options: CallOptions | None = None,
    ) -> RecommendationResponse:
        """Recommendations for an anonymous visit, with no customer to name."""
        return decode(
            await self._transport.send(
                for_session_spec(
                    request_id=request_id,
                    session_id=session_id,
                    top_n=top_n,
                    recent_events=recent_events,
                    exclude_product_ids=exclude_product_ids,
                    context=context,
                    allow_fallback=allow_fallback,
                    options=options,
                )
            )
        )
