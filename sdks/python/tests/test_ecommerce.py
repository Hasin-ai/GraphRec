from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import httpx
import pytest

import graphrec_sdk as g
from graphrec_sdk.ecommerce import CatalogSync, EventBuilder, EventTracker, RecommendationSession

from . import conftest as fx
from .conftest import MockAPI, error, make_client


def _batch_echo(request: httpx.Request) -> Dict[str, Any]:
    return fx.event_batch(accepted=len(json.loads(request.content)["events"]))


def test_builder_shapes_common_interactions() -> None:
    builder = EventBuilder(default_context={"channel": "web"})
    cart = builder.add_to_cart("u1", "sku-1", quantity=2, price="19.90", session_id="s1")
    assert cart.event_type == "add_to_cart" and cart.external_product_id == "sku-1"
    assert cart.context == {"channel": "web", "quantity": 2, "price": "19.90", "session_id": "s1"}

    line1 = builder.purchase("u1", "sku-1", order_id="ORD-1", line=1)
    replay = builder.purchase("u1", "sku-1", order_id="ORD-1", line=1)
    other = builder.purchase("u1", "sku-1", order_id="ORD-1", line=2)
    assert line1.event_id == replay.event_id != other.event_id
    assert line1.context["order_id"] == "ORD-1"

    search = builder.search(None, "linen shirt")
    assert search.external_product_id is None and search.context["query"] == "linen shirt"

    with pytest.raises(g.InputValidationError):
        builder.rating("u1", "sku-1", 7)
    with pytest.raises(g.InputValidationError):
        builder.add_to_cart("u1", "sku-1", quantity=0)
    with pytest.raises(g.InputValidationError, match="context"):
        builder.view("u1", "sku-1", colour="red")


def test_tracker_flushes_at_batch_size_and_on_close(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/events/batches", _batch_echo)
    with make_client(api, sleeps) as client:
        with EventTracker(client, batch_size=3) as tracker:
            tracker.view("u1", "sku-1")
            tracker.click("u1", "sku-1")
            assert api.calls == [] and tracker.pending == 2
            tracker.add_to_cart("u1", "sku-1")
            assert len(api.calls) == 1 and tracker.pending == 0
            tracker.purchase("u1", "sku-1", order_id="ORD-7")
        assert len(api.calls) == 2
    types = [e["event_type"] for call in api.calls for e in call.json()["events"]]
    assert types == ["view", "click", "add_to_cart", "purchase"]


def test_tracker_requeues_on_failure_without_handler(api: MockAPI, sleeps: List[float]) -> None:
    api.queue(
        "POST", "/v1/events/batches", error(400, "malformed_request"), fx.event_batch(accepted=2)
    )
    with make_client(api, sleeps) as client:
        tracker = EventTracker(client, batch_size=100)
        first = tracker.view("u1", "sku-1")
        tracker.view("u1", "sku-2")
        with pytest.raises(g.MalformedRequestError):
            tracker.flush()
        assert tracker.pending == 2
        result = tracker.flush()
        assert result is not None and result.accepted_count == 2
        assert api.calls[0].json() == api.calls[1].json()  # identical event_ids on retry
        assert api.calls[1].json()["events"][0]["event_id"] == first.event_id


def test_tracker_error_handler_drops_events(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/events/batches", lambda _r: error(403, "insufficient_scope"))
    failures: List[int] = []
    with make_client(api, sleeps) as client:
        tracker = EventTracker(client, on_error=lambda exc, events: failures.append(len(events)))
        tracker.search("u1", "shoes")
        assert tracker.flush() is None
        assert failures == [1] and tracker.pending == 0


def test_tracker_background_thread(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/events/batches", _batch_echo)
    with make_client(api, sleeps) as client:
        tracker = EventTracker(client, batch_size=1000, flush_interval=0.05)
        tracker.view("u1", "sku-1")
        deadline = time.monotonic() + 2
        while not api.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        tracker.close()
    assert len(api.calls) == 1


def test_tracker_bounded_queue_drops_oldest(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps) as client:
        tracker = EventTracker(client, batch_size=100, max_queue_size=2)
        tracker.view("u1", "a")
        tracker.view("u1", "b")
        tracker.view("u1", "c")
        assert tracker.pending == 2 and tracker.dropped == 1


def test_catalog_sync_upserts_and_disables_missing(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/products:bulk-upsert", fx.bulk_result(created=1, updated=1))
    api.on(
        "GET",
        "/v1/products",
        {
            "items": [
                fx.product("sku-1"),
                fx.product("sku-2"),
                fx.product("old", is_active=True),
                fx.product("gone", is_active=False),
            ],
            "total": 4,
        },
    )
    api.on("POST", "/v1/products/old:disable", fx.product("old", is_active=False))
    with make_client(api, sleeps) as client:
        report = CatalogSync(client).run(
            [{"external_id": "sku-1", "title": "A"}, {"external_id": "sku-2", "title": "B"}],
            disable_missing=True,
        )
    assert report.disabled_ids == ["old"] and report.ok
    assert "disabled=1" in report.summary()


def test_catalog_sync_refuses_empty_feed_with_disable(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps) as client:
        with pytest.raises(g.InputValidationError, match="empty feed"):
            CatalogSync(client).run([], disable_missing=True)
    assert api.calls == []


def test_catalog_sync_collects_disable_failures(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/products", {"items": [fx.product("old")], "total": 1})
    api.on("POST", "/v1/products/old:disable", lambda _r: error(403, "insufficient_scope"))
    with make_client(api, sleeps) as client:
        report = CatalogSync(client).run([], disable_missing=True, allow_empty=True)
    assert report.upsert.request_count == 0 and "old" in report.disable_failures and not report.ok


def test_recommendation_session_links_feedback(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/recommendations/session", fx.recommendations(("sku-7", "sku-8")))
    api.on(
        "POST",
        "/v1/feedback/impressions",
        lambda req: fx.feedback("impression", json.loads(req.content)["event_id"]),
    )
    api.on("POST", "/v1/feedback/clicks", fx.feedback("click"))
    api.on("POST", "/v1/feedback/conversions", fx.feedback("conversion"))
    with make_client(api, sleeps) as client:
        session = RecommendationSession(client)
        recs = session.recommend(session_id="sess-1", recent_product_ids=["sku-1"], top_n=2)
        impression_id = api.last().json()["event_id"]
        session.click(recs, "sku-8")
        click = api.last().json()
        session.convert(recs, "sku-8", value="49.90")
        conversion = api.last().json()
    assert api.paths() == [
        "POST /v1/recommendations/session",
        "POST /v1/feedback/impressions",
        "POST /v1/feedback/clicks",
        "POST /v1/feedback/conversions",
    ]
    assert click["impression_event_id"] == impression_id and click["position"] == 2
    assert conversion["value"] == "49.90" and conversion["request_id"] == "rec-abc123"


def test_recommendation_session_skips_impression_for_empty_results(
    api: MockAPI, sleeps: List[float]
) -> None:
    api.on("POST", "/v1/recommendations", fx.recommendations(()))
    with make_client(api, sleeps) as client:
        recs = RecommendationSession(client).recommend(user_id="u1")
    assert len(recs) == 0 and api.paths() == ["POST /v1/recommendations"]
