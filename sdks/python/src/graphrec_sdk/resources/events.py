from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union, cast
from uuid import UUID

from .._batching import chunk_items
from .._serialization import to_jsonable
from .._validation import coerce_input
from ..enums import EventType
from ..errors import APIError, InputValidationError
from ..models.events import (
    EventBatch,
    EventBatchList,
    EventBatchResult,
    EventInput,
    EventReceipt,
)
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncEvents", "EventLike", "Events"]

EventLike = Union[EventInput, Mapping[str, Any]]


def _single_body(
    event_type: Union[EventType, str],
    user_id: Optional[str],
    product_id: Optional[str],
    context: Optional[Mapping[str, Any]],
    occurred_at: Optional[datetime],
    event_id: Optional[str],
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "event_type": event_type,
        "user_id": user_id,
        "external_product_id": product_id,
        "context": dict(context or {}),
    }
    if occurred_at is not None:
        data["occurred_at"] = occurred_at
    if event_id is not None:
        data["event_id"] = event_id
    return cast(Dict[str, Any], to_jsonable(coerce_input(EventInput, data)))


def _plan_batch(events: Iterable[EventLike], *, max_bytes: int, max_items: int) -> List[List[Any]]:
    items = [to_jsonable(coerce_input(EventInput, event)) for event in events]
    if not items:
        raise InputValidationError("create_batch() needs at least one event")
    return chunk_items(
        items, envelope_key="events", max_bytes=max_bytes, max_items=max_items, describe="Event"
    )


class Events(SyncResource):
    """Customer interactions used for training. Scopes: ``events:write`` / ``events:read``."""

    def create(
        self,
        event_type: Union[EventType, str],
        *,
        user_id: Optional[str] = None,
        product_id: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[str] = None,
    ) -> EventReceipt:
        """Record one interaction (``POST /v1/events``).

        ``event_id`` deduplicates: a repeat returns ``duplicate=True``. It is
        generated when omitted, and reused across automatic retries.
        """

        return cast(
            EventReceipt,
            self._client.request(
                "events.create",
                json=_single_body(event_type, user_id, product_id, context, occurred_at, event_id),
                cast_to=EventReceipt,
            ),
        )

    def create_batch(self, events: Iterable[EventLike]) -> EventBatchResult:
        """Record many interactions (``POST /v1/events/batches``), split to fit the body limit.

        On failure the raised :class:`~graphrec_sdk.APIError` carries
        ``partial_result`` describing the batches already accepted.
        """

        batches: List[EventBatch] = []
        for chunk in _plan_batch(
            events, max_bytes=self._client.max_body_bytes, max_items=self._client.max_batch_items
        ):
            try:
                batch = self._client.request(
                    "events.create_batch", json={"events": chunk}, cast_to=EventBatch
                )
            except APIError as exc:
                exc.partial_result = EventBatchResult.from_batches(batches)  # type: ignore[attr-defined]
                raise
            batches.append(cast(EventBatch, batch))
        return EventBatchResult.from_batches(batches)

    def list_batches(self) -> EventBatchList:
        """Submitted batches, newest first (``GET /v1/events/batches``)."""

        items = self._client.request("events.list_batches", cast_to=List[EventBatch])
        return EventBatchList(items=items)

    def get_batch(self, batch_id: Union[str, UUID]) -> EventBatch:
        """``GET /v1/events/batches/{batch_id}``."""

        return cast(
            EventBatch,
            self._client.request(
                "events.get_batch", path_params={"batch_id": batch_id}, cast_to=EventBatch
            ),
        )


class AsyncEvents(AsyncResource):
    async def create(
        self,
        event_type: Union[EventType, str],
        *,
        user_id: Optional[str] = None,
        product_id: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[str] = None,
    ) -> EventReceipt:
        """Async variant of :meth:`Events.create`."""

        return cast(
            EventReceipt,
            await self._client.request(
                "events.create",
                json=_single_body(event_type, user_id, product_id, context, occurred_at, event_id),
                cast_to=EventReceipt,
            ),
        )

    async def create_batch(self, events: Iterable[EventLike]) -> EventBatchResult:
        """Async variant of :meth:`Events.create_batch`."""

        batches: List[EventBatch] = []
        for chunk in _plan_batch(
            events, max_bytes=self._client.max_body_bytes, max_items=self._client.max_batch_items
        ):
            try:
                batch = await self._client.request(
                    "events.create_batch", json={"events": chunk}, cast_to=EventBatch
                )
            except APIError as exc:
                exc.partial_result = EventBatchResult.from_batches(batches)  # type: ignore[attr-defined]
                raise
            batches.append(cast(EventBatch, batch))
        return EventBatchResult.from_batches(batches)

    async def list_batches(self) -> EventBatchList:
        """Async variant of :meth:`Events.list_batches`."""

        items = await self._client.request("events.list_batches", cast_to=List[EventBatch])
        return EventBatchList(items=items)

    async def get_batch(self, batch_id: Union[str, UUID]) -> EventBatch:
        """Async variant of :meth:`Events.get_batch`."""

        return cast(
            EventBatch,
            await self._client.request(
                "events.get_batch", path_params={"batch_id": batch_id}, cast_to=EventBatch
            ),
        )
