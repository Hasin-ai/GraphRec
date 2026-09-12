"""Test fixtures: the FastAPI app wired to a fake GraphRec client (no network)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest
from graphrec_sdk import NotFoundError, ServiceUnavailableError
from graphrec_sdk.ecommerce import EventBuilder
from graphrec_sdk.models import (
    EventBatch,
    EventBatchResult,
    FeedbackReceipt,
    Product,
    ProductList,
    RecommendationItem,
    Recommendations,
)

from app.catalog import CatalogCache
from app.config import Settings
from app.graphrec import Services
from app.main import create_app
from fixtures.products import PRODUCTS

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
MODEL_VERSION = "3f0e2b8e-9c1d-4c1e-8e2a-000000000001"


def status_error(cls, status: int, code: str, correlation_id: Optional[str] = None, message: str = "upstream failure"):
    """Build an SDK status error the way the transport would (it needs a real httpx.Response)."""

    response = httpx.Response(status, request=httpx.Request("GET", "http://graphrec.test/v1/x"), json={"error": {"code": code}})
    return cls(message, response=response, code=code, correlation_id=correlation_id)


def product_model(spec: Dict[str, Any], **overrides: Any) -> Product:
    data = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, spec["external_id"])),
        "created_at": NOW,
        "updated_at": NOW,
        **spec,
    }
    data.update(overrides)
    return Product.model_validate(data)


@dataclass
class FakeProducts:
    items: List[Product]
    list_calls: int = 0

    async def list(self) -> ProductList:
        self.list_calls += 1
        return ProductList(items=self.items, total=len(self.items))

    async def get(self, external_id: str) -> Product:
        for p in self.items:
            if p.external_id == external_id:
                return p
        raise status_error(NotFoundError, 404, "resource_not_found", "cid-404")


@dataclass
class FakeRecommendations:
    """Ranks by a per-user rule so tests can make personas identical or different."""

    calls: List[Dict[str, Any]] = field(default_factory=list)
    #: external ids per user id (None = session); default: the same list for everyone.
    rankings: Dict[Optional[str], List[str]] = field(default_factory=dict)
    default_ranking: List[str] = field(default_factory=lambda: [p["external_id"] for p in PRODUCTS[:6]])
    model_version: Optional[str] = MODEL_VERSION
    fail_with: Optional[Exception] = None
    fallback_for_sessions: bool = True

    def _result(self, user_id: Optional[str], top_n: int, exclude: List[str]) -> Recommendations:
        ids = [i for i in self.rankings.get(user_id, self.default_ranking) if i not in set(exclude)][:top_n]
        fallback = user_id is None and self.fallback_for_sessions
        return Recommendations(
            request_id="rec_" + uuid.uuid4().hex[:8],
            items=[RecommendationItem(external_product_id=i, position=n) for n, i in enumerate(ids, start=1)],
            model_version_id=None if fallback else self.model_version,
            strategy="popular_fallback" if fallback else "personalized",
            fallback_used=fallback,
            fallback_tier="tenant_popular" if fallback else "none",
        )

    async def get(self, *, user_id=None, top_n=10, context=None, exclude_product_ids=None) -> Recommendations:
        if self.fail_with:
            raise self.fail_with
        self.calls.append({"kind": "user", "user_id": user_id, "top_n": top_n, "context": dict(context or {}), "exclude": list(exclude_product_ids or [])})
        return self._result(user_id, top_n, list(exclude_product_ids or []))

    async def for_session(self, session_id, *, recent_product_ids=None, user_id=None, top_n=10, context=None, exclude_product_ids=None) -> Recommendations:
        if self.fail_with:
            raise self.fail_with
        self.calls.append({"kind": "session", "session_id": session_id, "recent": list(recent_product_ids or []), "top_n": top_n, "context": dict(context or {}), "exclude": list(exclude_product_ids or [])})
        return self._result(None, top_n, list(exclude_product_ids or []))


@dataclass
class FakeFeedback:
    impressions: List[Dict[str, Any]] = field(default_factory=list)
    clicks: List[Dict[str, Any]] = field(default_factory=list)

    async def impression(self, recs, **options) -> FeedbackReceipt:
        self.impressions.append({"request_id": recs.request_id, **options})
        return FeedbackReceipt(event_id="imp_" + recs.request_id, feedback_type="impression", accepted=True, duplicate=False, received_at=NOW)

    async def click(self, ref, product_id, **options) -> FeedbackReceipt:
        self.clicks.append({"request_id": ref if isinstance(ref, str) else ref.request_id, "product_id": product_id, **options})
        return FeedbackReceipt(event_id="clk_1", feedback_type="click", accepted=True, duplicate=False, received_at=NOW)


@dataclass
class FakeEvents:
    batches: List[List[Any]] = field(default_factory=list)
    seen_ids: set = field(default_factory=set)

    async def create_batch(self, events) -> EventBatchResult:
        items = list(events)
        self.batches.append(items)
        duplicates = sum(1 for e in items if e.event_id in self.seen_ids)
        self.seen_ids.update(e.event_id for e in items)
        batch = EventBatch(id=str(uuid.uuid4()), status="completed", accepted_count=len(items) - duplicates, duplicate_count=duplicates, rejected_count=0, created_at=NOW)
        return EventBatchResult.from_batches([batch])


@dataclass
class FakeTracker:
    """Records what the storefront asks the SDK tracker to do."""

    events: List[Any] = field(default_factory=list)
    builder: EventBuilder = field(default_factory=lambda: EventBuilder(default_context={"source": "demo-storefront"}))
    closed: bool = False

    @property
    def pending(self) -> int:
        return len(self.events)

    def start(self) -> None: ...

    async def close(self) -> None:
        self.closed = True

    def _record(self, event):
        self.events.append(event)
        return event

    async def view(self, user_id, product_id, **o):
        return self._record(self.builder.view(user_id, product_id, **o))

    async def add_to_cart(self, user_id, product_id, **o):
        return self._record(self.builder.add_to_cart(user_id, product_id, **o))

    async def remove_from_cart(self, user_id, product_id, **o):
        return self._record(self.builder.remove_from_cart(user_id, product_id, **o))

    async def add_to_wishlist(self, user_id, product_id, **o):
        return self._record(self.builder.add_to_wishlist(user_id, product_id, **o))

    async def search(self, user_id, query, **o):
        return self._record(self.builder.search(user_id, query, **o))


@dataclass
class FakeClient:
    products: FakeProducts
    recommendations: FakeRecommendations
    feedback: FakeFeedback
    events: FakeEvents
    healthy: bool = True

    async def health(self) -> dict:
        if not self.healthy:
            raise status_error(ServiceUnavailableError, 503, "service_unavailable", "cid-503")
        return {"status": "ok"}

    async def close(self) -> None: ...


def make_settings(**overrides: Any) -> Settings:
    values = {"graphrec_api_key": "gr_live_" + "x" * 43, "graphrec_base_url": "http://graphrec.test", "catalog_cache_seconds": 0.0}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@dataclass
class Harness:
    client: FakeClient
    tracker: FakeTracker
    services: Services
    settings: Settings
    app: Any


def build_harness(**settings_overrides: Any) -> Harness:
    items = [product_model(p) for p in PRODUCTS]
    # One disabled product, to prove it never surfaces.
    items[2] = product_model(PRODUCTS[2], is_active=False, availability_status="unavailable")
    client = FakeClient(products=FakeProducts(items), recommendations=FakeRecommendations(), feedback=FakeFeedback(), events=FakeEvents())
    tracker = FakeTracker()
    settings = make_settings(**settings_overrides)
    services = Services(client=client, tracker=tracker, catalog=CatalogCache(client.products, ttl=0.0), settings=settings)
    app = create_app(settings=settings, svc=services)
    return Harness(client=client, tracker=tracker, services=services, settings=settings, app=app)


@pytest.fixture
def harness() -> Harness:
    return build_harness()


@pytest.fixture
async def api(harness: Harness):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=harness.app), base_url="http://facet.test") as client:
        async with harness.app.router.lifespan_context(harness.app):
            yield client


def as_persona(key: str, session: str = "sess_test_000000000001") -> Dict[str, str]:
    return {"facet_demo_user": key, "facet_demo_session": session}
