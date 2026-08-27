"""Interaction events, on the control plane.

Two shapes and two idempotency mechanisms, which is deliberate and worth
knowing: a single event is keyed on `event_id` and a repeat comes back
``200 duplicate_confirmed`` with the time the first one arrived; a batch is keyed
on `batch_id` and a repeat returns the original submission rather than draining
the collection twice. In both cases a repeat is a **success** — there is no 409
anywhere on this surface, because an integration retrying after a timeout has
done nothing wrong (`apps/control_api/routers/ingestion.py`).

Both keys are your arguments and neither is generated here. A generated
`batch_id` would be different on every attempt, so the retry the SDK performs on
your behalf would be a second submission of the same events under a new key —
the deduplication the backend offers, silently disabled by the convenience the
SDK added.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._spec import CallOptions, Spec
from .._validate import build, parse
from ..models import EventBatch, EventInput, EventReceipt, EventType, Submission
from ..transport import AsyncTransport, Transport
from .submissions import decode_submission

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from ..transport import AsyncTransport, Transport

_EventArg = EventInput | dict[str, Any]


def submit_spec(
    *,
    event_id: str,
    customer_id: str,
    external_product_id: str,
    event_type: EventType,
    occurred_at: datetime | str,
    value: Decimal | str | None = None,
    context: dict[str, Any] | None = None,
    options: CallOptions | None = None,
) -> Spec:
    event = build(
        EventInput,
        "An event",
        event_id=event_id,
        customer_id=customer_id,
        external_product_id=external_product_id,
        event_type=event_type,
        occurred_at=occurred_at,
        value=value,
        context=context,
    )
    return Spec(
        "POST",
        "/v1/events",
        event.model_dump(mode="json", exclude_none=True),
        idempotent=True,
        options=options,
    )


def submit_batch_spec(
    *, batch_id: str, events: list[_EventArg], options: CallOptions | None = None
) -> Spec:
    batch = build(EventBatch, "An event batch", batch_id=batch_id, events=events)
    return Spec(
        "POST",
        "/v1/events/batches",
        batch.model_dump(mode="json", exclude_none=True),
        idempotent=True,
        options=options,
    )


def decode_receipt(payload: object) -> EventReceipt:
    return parse(EventReceipt, payload)


class Events:
    """Events, blocking."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def submit(
        self,
        *,
        event_id: str,
        customer_id: str,
        external_product_id: str,
        event_type: EventType,
        occurred_at: datetime | str,
        value: Decimal | str | None = None,
        context: dict[str, Any] | None = None,
        options: CallOptions | None = None,
    ) -> EventReceipt:
        """One interaction. Answers `200` whether it is new or a confirmed repeat."""
        return decode_receipt(
            self._transport.send(
                submit_spec(
                    event_id=event_id,
                    customer_id=customer_id,
                    external_product_id=external_product_id,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    value=value,
                    context=context,
                    options=options,
                )
            )
        )

    def submit_batch(
        self, *, batch_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> Submission:
        """Up to 5,000 interactions, accepted for processing.

        Returns the submission at `202`, before any of it has been applied. Use
        `submissions.wait` for the counts and the per-item rejections.
        """
        return decode_submission(
            self._transport.send(
                submit_batch_spec(batch_id=batch_id, events=events, options=options)
            )
        )


class AsyncEvents:
    """Events, awaited."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def submit(
        self,
        *,
        event_id: str,
        customer_id: str,
        external_product_id: str,
        event_type: EventType,
        occurred_at: datetime | str,
        value: Decimal | str | None = None,
        context: dict[str, Any] | None = None,
        options: CallOptions | None = None,
    ) -> EventReceipt:
        """One interaction. Answers `200` whether it is new or a confirmed repeat."""
        return decode_receipt(
            await self._transport.send(
                submit_spec(
                    event_id=event_id,
                    customer_id=customer_id,
                    external_product_id=external_product_id,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    value=value,
                    context=context,
                    options=options,
                )
            )
        )

    async def submit_batch(
        self, *, batch_id: str, events: list[_EventArg], options: CallOptions | None = None
    ) -> Submission:
        """Up to 5,000 interactions, accepted for processing.

        Returns the submission at `202`, before any of it has been applied. Use
        `submissions.wait` for the counts and the per-item rejections.
        """
        return decode_submission(
            await self._transport.send(
                submit_batch_spec(batch_id=batch_id, events=events, options=options)
            )
        )
