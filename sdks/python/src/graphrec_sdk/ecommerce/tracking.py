"""Buffered event tracking for storefront backends.

::

    from graphrec_sdk import GraphRec
    from graphrec_sdk.ecommerce import EventTracker

    client = GraphRec(api_key="gr_live_...")
    with EventTracker(client, batch_size=50, flush_interval=5) as tracker:
        tracker.view("customer-42", "sku-123", session_id="sess-9")
        tracker.add_to_cart("customer-42", "sku-123", quantity=2, price="19.90")
        tracker.purchase("customer-42", "sku-123", order_id="ORD-1001", quantity=2)
    # remaining events are flushed on exit

Events are sent with ``POST /v1/events/batches`` (split to fit the 16 KiB body
limit). Because each event carries a stable ``event_id``, re-sending a batch
after a failure never double-counts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Deque, List, Mapping, Optional, Union

from ..enums import EventType
from ..models.events import EventBatchResult, EventInput
from ._builders import EventBuilder, Number

if TYPE_CHECKING:
    from .._client import AsyncGraphRec, GraphRec

__all__ = ["AsyncEventTracker", "EventTracker"]

log = logging.getLogger("graphrec_sdk.tracking")

ErrorHandler = Callable[[Exception, List[EventInput]], None]
AsyncErrorHandler = Callable[[Exception, List[EventInput]], Union[None, Awaitable[None]]]


class _Queue:
    def __init__(self, max_queue_size: int) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be >= 1")
        self.max_queue_size = max_queue_size
        self.items: Deque[EventInput] = deque()
        self.dropped = 0

    def push(self, event: EventInput) -> None:
        if len(self.items) >= self.max_queue_size:
            self.items.popleft()
            self.dropped += 1
            log.warning("GraphRec event queue full (%d); dropped oldest event", self.max_queue_size)
        self.items.append(event)

    def take(self) -> List[EventInput]:
        batch = list(self.items)
        self.items.clear()
        return batch

    def requeue(self, events: List[EventInput]) -> None:
        for event in reversed(events):
            if len(self.items) >= self.max_queue_size:
                self.dropped += 1
                continue
            self.items.appendleft(event)


class EventTracker:
    """Thread-safe buffered tracker for the synchronous :class:`~graphrec_sdk.GraphRec` client.

    :param batch_size: flush automatically once this many events are queued.
    :param flush_interval: seconds between background flushes (``None`` = no thread).
    :param max_queue_size: oldest events are dropped beyond this bound.
    :param on_error: called with ``(exception, events)`` when a flush fails; the
        events are then discarded. Without a handler, failed events are
        re-queued and the exception propagates from :meth:`flush`.
    :param default_context: merged into every event's ``context`` (e.g. ``{"channel": "web"}``).
    """

    def __init__(
        self,
        client: GraphRec,
        *,
        batch_size: int = 100,
        flush_interval: Optional[float] = None,
        max_queue_size: int = 10_000,
        on_error: Optional[ErrorHandler] = None,
        default_context: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._client = client
        self._builder = EventBuilder(default_context=default_context)
        self._queue = _Queue(max_queue_size)
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()
        self.batch_size = batch_size
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if flush_interval is not None:
            if flush_interval <= 0:
                raise ValueError("flush_interval must be > 0")
            self._thread = threading.Thread(
                target=self._run, args=(flush_interval,), name="graphrec-event-tracker", daemon=True
            )
            self._thread.start()

    # -- enqueue ----------------------------------------------------------------

    def track(
        self,
        event_type: Union[EventType, str],
        *,
        user_id: Optional[str] = None,
        product_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[str] = None,
    ) -> EventInput:
        """Queue any interaction type."""

        return self._enqueue(
            self._builder.build(
                event_type,
                user_id=user_id,
                product_id=product_id,
                session_id=session_id,
                context=context,
                occurred_at=occurred_at,
                event_id=event_id,
            )
        )

    def view(self, user_id: Optional[str], product_id: str, **options: Any) -> EventInput:
        """Product page view. Options: session_id, context, occurred_at, event_id."""

        return self._enqueue(self._builder.view(user_id, product_id, **options))

    def click(self, user_id: Optional[str], product_id: str, **options: Any) -> EventInput:
        return self._enqueue(self._builder.click(user_id, product_id, **options))

    def add_to_cart(
        self,
        user_id: Optional[str],
        product_id: str,
        *,
        quantity: int = 1,
        price: Optional[Number] = None,
        **options: Any,
    ) -> EventInput:
        return self._enqueue(
            self._builder.add_to_cart(
                user_id, product_id, quantity=quantity, price=price, **options
            )
        )

    def remove_from_cart(
        self, user_id: Optional[str], product_id: str, *, quantity: int = 1, **options: Any
    ) -> EventInput:
        return self._enqueue(
            self._builder.remove_from_cart(user_id, product_id, quantity=quantity, **options)
        )

    def purchase(
        self,
        user_id: Optional[str],
        product_id: str,
        *,
        order_id: Optional[str] = None,
        line: Optional[Union[int, str]] = None,
        quantity: int = 1,
        price: Optional[Number] = None,
        currency: Optional[str] = None,
        **options: Any,
    ) -> EventInput:
        """One purchased order line; ``order_id`` makes it idempotent across webhook replays."""

        return self._enqueue(
            self._builder.purchase(
                user_id,
                product_id,
                order_id=order_id,
                line=line,
                quantity=quantity,
                price=price,
                currency=currency,
                **options,
            )
        )

    def rating(
        self,
        user_id: Optional[str],
        product_id: str,
        rating: Union[int, float],
        *,
        max_rating: Union[int, float] = 5,
        **options: Any,
    ) -> EventInput:
        return self._enqueue(
            self._builder.rating(user_id, product_id, rating, max_rating=max_rating, **options)
        )

    def search(self, user_id: Optional[str], query: str, **options: Any) -> EventInput:
        return self._enqueue(self._builder.search(user_id, query, **options))

    def add_to_wishlist(
        self, user_id: Optional[str], product_id: str, **options: Any
    ) -> EventInput:
        return self._enqueue(self._builder.add_to_wishlist(user_id, product_id, **options))

    # -- delivery -------------------------------------------------------------------

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._queue.items)

    @property
    def dropped(self) -> int:
        """Events discarded because the queue was full."""

        return self._queue.dropped

    def flush(self) -> Optional[EventBatchResult]:
        """Send every queued event now. Returns ``None`` when nothing was queued."""

        with self._flush_lock:
            with self._lock:
                events = self._queue.take()
            if not events:
                return None
            try:
                return self._client.events.create_batch(events)
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(exc, events)
                    return None
                with self._lock:
                    self._queue.requeue(events)
                raise

    def close(self) -> None:
        """Stop the background thread (if any) and flush remaining events."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None
        self.flush()

    def __enter__(self) -> EventTracker:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _enqueue(self, event: EventInput) -> EventInput:
        with self._lock:
            self._queue.push(event)
            should_flush = len(self._queue.items) >= self.batch_size
        if should_flush:
            self.flush()
        return event

    def _run(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self.flush()
            except Exception:
                log.exception("GraphRec background flush failed; events were re-queued")


class AsyncEventTracker:
    """Buffered tracker for :class:`~graphrec_sdk.AsyncGraphRec`.

    Queueing methods are coroutines because they may flush. Call
    :meth:`start` to flush every ``flush_interval`` seconds in a background
    task, and :meth:`close` (or ``async with``) to drain the queue.
    """

    def __init__(
        self,
        client: AsyncGraphRec,
        *,
        batch_size: int = 100,
        flush_interval: Optional[float] = None,
        max_queue_size: int = 10_000,
        on_error: Optional[AsyncErrorHandler] = None,
        default_context: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if flush_interval is not None and flush_interval <= 0:
            raise ValueError("flush_interval must be > 0")
        self._client = client
        self._builder = EventBuilder(default_context=default_context)
        self._queue = _Queue(max_queue_size)
        self._flush_lock: Optional[asyncio.Lock] = None
        self._task: Optional[asyncio.Task[None]] = None
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.on_error = on_error

    async def track(
        self,
        event_type: Union[EventType, str],
        *,
        user_id: Optional[str] = None,
        product_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[str] = None,
    ) -> EventInput:
        return await self._enqueue(
            self._builder.build(
                event_type,
                user_id=user_id,
                product_id=product_id,
                session_id=session_id,
                context=context,
                occurred_at=occurred_at,
                event_id=event_id,
            )
        )

    async def view(self, user_id: Optional[str], product_id: str, **options: Any) -> EventInput:
        return await self._enqueue(self._builder.view(user_id, product_id, **options))

    async def click(self, user_id: Optional[str], product_id: str, **options: Any) -> EventInput:
        return await self._enqueue(self._builder.click(user_id, product_id, **options))

    async def add_to_cart(
        self,
        user_id: Optional[str],
        product_id: str,
        *,
        quantity: int = 1,
        price: Optional[Number] = None,
        **options: Any,
    ) -> EventInput:
        return await self._enqueue(
            self._builder.add_to_cart(
                user_id, product_id, quantity=quantity, price=price, **options
            )
        )

    async def remove_from_cart(
        self, user_id: Optional[str], product_id: str, *, quantity: int = 1, **options: Any
    ) -> EventInput:
        return await self._enqueue(
            self._builder.remove_from_cart(user_id, product_id, quantity=quantity, **options)
        )

    async def purchase(
        self,
        user_id: Optional[str],
        product_id: str,
        *,
        order_id: Optional[str] = None,
        line: Optional[Union[int, str]] = None,
        quantity: int = 1,
        price: Optional[Number] = None,
        currency: Optional[str] = None,
        **options: Any,
    ) -> EventInput:
        return await self._enqueue(
            self._builder.purchase(
                user_id,
                product_id,
                order_id=order_id,
                line=line,
                quantity=quantity,
                price=price,
                currency=currency,
                **options,
            )
        )

    async def rating(
        self,
        user_id: Optional[str],
        product_id: str,
        rating: Union[int, float],
        *,
        max_rating: Union[int, float] = 5,
        **options: Any,
    ) -> EventInput:
        return await self._enqueue(
            self._builder.rating(user_id, product_id, rating, max_rating=max_rating, **options)
        )

    async def search(self, user_id: Optional[str], query: str, **options: Any) -> EventInput:
        return await self._enqueue(self._builder.search(user_id, query, **options))

    async def add_to_wishlist(
        self, user_id: Optional[str], product_id: str, **options: Any
    ) -> EventInput:
        return await self._enqueue(self._builder.add_to_wishlist(user_id, product_id, **options))

    @property
    def pending(self) -> int:
        return len(self._queue.items)

    @property
    def dropped(self) -> int:
        return self._queue.dropped

    async def flush(self) -> Optional[EventBatchResult]:
        if self._flush_lock is None:
            self._flush_lock = asyncio.Lock()
        async with self._flush_lock:
            events = self._queue.take()
            if not events:
                return None
            try:
                return await self._client.events.create_batch(events)
            except Exception as exc:
                if self.on_error is not None:
                    outcome = self.on_error(exc, events)
                    if asyncio.iscoroutine(outcome):
                        await outcome
                    return None
                self._queue.requeue(events)
                raise

    def start(self) -> None:
        """Begin periodic background flushing (requires ``flush_interval``)."""

        if self.flush_interval is None:
            raise ValueError("start() requires flush_interval")
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(self.flush_interval))

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.flush()

    async def __aenter__(self) -> AsyncEventTracker:
        if self.flush_interval is not None:
            self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _enqueue(self, event: EventInput) -> EventInput:
        self._queue.push(event)
        if len(self._queue.items) >= self.batch_size:
            await self.flush()
        return event

    async def _run(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.flush()
            except Exception:
                log.exception("GraphRec background flush failed; events were re-queued")
