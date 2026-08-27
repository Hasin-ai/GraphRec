"""What happened to an answer, on the data plane.

Three routes rather than one with a `type` field, because that is how the API is
shaped and collapsing them would mean inventing a discriminator the server does
not read. All three take the same body and all three are keyed on `request_id`
plus each item's `event_id`, so a retried batch is deduplicated per item —
`graphrec/domain/serving/feedback.py` opens by saying a retry after a timeout is
the normal consequence of one, not an error.

`unknown_products` in the reply is not a failure. It is the identifiers that are
not in your catalogue, which usually means the catalogue sync has not caught up
with the storefront, and it is worth a metric.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._spec import CallOptions, Spec
from .._validate import build, parse
from ..models import FeedbackEvent, FeedbackRequest, FeedbackResponse

if TYPE_CHECKING:
    from ..transport import AsyncTransport, Transport

_EventArg = FeedbackEvent | dict[str, Any]

IMPRESSIONS = "/v1/feedback/impressions"
CLICKS = "/v1/feedback/clicks"
CONVERSIONS = "/v1/feedback/conversions"


def feedback_spec(
    path: str,
    *,
    request_id: str,
    events: list[_EventArg],
    options: CallOptions | None = None,
) -> Spec:
    request = build(FeedbackRequest, "A feedback request", request_id=request_id, events=events)
    return Spec(
        "POST",
        path,
        request.model_dump(mode="json", exclude_none=True),
        # Safe: `request_id` plus each `event_id` is the deduplication key.
        idempotent=True,
        options=options,
    )


def decode(payload: object) -> FeedbackResponse:
    return parse(FeedbackResponse, payload)


class Feedback:
    """Feedback, blocking."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def impressions(
        self, *, request_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> FeedbackResponse:
        """The items you actually rendered. Without these, a click has no denominator."""
        return decode(
            self._transport.send(
                feedback_spec(IMPRESSIONS, request_id=request_id, events=events, options=options)
            )
        )

    def clicks(
        self, *, request_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> FeedbackResponse:
        """The items that were chosen."""
        return decode(
            self._transport.send(
                feedback_spec(CLICKS, request_id=request_id, events=events, options=options)
            )
        )

    def conversions(
        self, *, request_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> FeedbackResponse:
        """The items that were bought. `value` is a float here — a signal, not money."""
        return decode(
            self._transport.send(
                feedback_spec(CONVERSIONS, request_id=request_id, events=events, options=options)
            )
        )


class AsyncFeedback:
    """Feedback, awaited."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def impressions(
        self, *, request_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> FeedbackResponse:
        """The items you actually rendered. Without these, a click has no denominator."""
        return decode(
            await self._transport.send(
                feedback_spec(IMPRESSIONS, request_id=request_id, events=events, options=options)
            )
        )

    async def clicks(
        self, *, request_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> FeedbackResponse:
        """The items that were chosen."""
        return decode(
            await self._transport.send(
                feedback_spec(CLICKS, request_id=request_id, events=events, options=options)
            )
        )

    async def conversions(
        self, *, request_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> FeedbackResponse:
        """The items that were bought. `value` is a float here — a signal, not money."""
        return decode(
            await self._transport.send(
                feedback_spec(CONVERSIONS, request_id=request_id, events=events, options=options)
            )
        )
