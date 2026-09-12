"""The single credentialed GraphRec client and the helpers built on it.

Created once in the FastAPI lifespan and stored on ``app.state.services``. Tests
construct :class:`Services` with fakes instead.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import httpx
from graphrec_sdk import AsyncGraphRec
from graphrec_sdk.ecommerce import AsyncEventTracker

from .catalog import CatalogCache
from .config import Settings

log = logging.getLogger("facet")


class ImpressionIndex:
    """Bounded ``request_id -> impression event_id`` memory shared by all requests."""

    def __init__(self, capacity: int = 2_000) -> None:
        self._data: "OrderedDict[str, str]" = OrderedDict()
        self._capacity = capacity

    def put(self, request_id: str, event_id: str) -> None:
        self._data.pop(request_id, None)
        self._data[request_id] = event_id
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def get(self, request_id: str) -> Optional[str]:
        return self._data.get(request_id)


@dataclass
class Services:
    client: Any
    tracker: Any
    catalog: CatalogCache
    settings: Settings
    impressions: ImpressionIndex = field(default_factory=ImpressionIndex)

    async def close(self) -> None:
        try:
            await self.tracker.close()
        finally:
            await self.client.close()


async def _log_tracker_failure(error: BaseException, events: Sequence[object]) -> None:
    # Telemetry must never break the storefront; dropped events are logged and counted.
    log.warning("event flush failed, %d events dropped: %s", len(events), error)


def build_services(settings: Settings) -> Services:
    client = AsyncGraphRec(
        base_url=settings.graphrec_base_url,
        api_key=settings.graphrec_api_key,
        timeout=httpx.Timeout(settings.graphrec_timeout_seconds, connect=1.0),
        max_retries=settings.graphrec_max_retries,
        default_headers={"X-Demo-App": "facet-storefront"},
    )
    tracker = AsyncEventTracker(
        client,
        batch_size=50,
        flush_interval=2.0,
        max_queue_size=5_000,
        on_error=_log_tracker_failure,
        default_context={"source": "demo-storefront", "app": "facet"},
    )
    return Services(
        client=client,
        tracker=tracker,
        catalog=CatalogCache(client.products, ttl=settings.catalog_cache_seconds),
        settings=settings,
    )


def product_ids(items: Sequence[object]) -> List[str]:
    return [str(getattr(i, "external_product_id")) for i in items]
