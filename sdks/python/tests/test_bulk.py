from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

import graphrec_sdk as g

from .conftest import MockAPI, error, event_batch, make_client


def _bulk_echo(request: httpx.Request) -> Dict[str, Any]:
    products = json.loads(request.content)["products"]
    return {
        "accepted_count": len(products),
        "created_count": len(products),
        "updated_count": 0,
        "skipped_count": 0,
        "rejected_count": 0,
        "failures": [],
    }


def _catalog(n: int, description_size: int = 200) -> List[Dict[str, Any]]:
    return [
        {
            "external_id": f"sku-{i:05d}",
            "title": f"Product {i}",
            "description": "d" * description_size,
            "price": "19.99",
            "category": "home",
            "metadata": {"brand": "Acme", "tags": ["a", "b"]},
        }
        for i in range(n)
    ]


def test_bulk_upsert_splits_on_the_byte_budget(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/products:bulk-upsert", _bulk_echo)
    with make_client(api, sleeps) as client:
        result = client.products.bulk_upsert(_catalog(500), idempotency_key="sync-1")
    sizes = [len(call.request.content) for call in api.calls]
    assert all(size <= 16_384 for size in sizes)
    assert max(sizes) > 14_000  # chunks are packed, not tiny
    assert result.created_count == 500 and result.request_count == len(api.calls) > 1
    sent_ids = [p["external_id"] for call in api.calls for p in call.json()["products"]]
    assert sent_ids == [f"sku-{i:05d}" for i in range(500)]
    keys = [call.headers["Idempotency-Key"] for call in api.calls]
    assert keys[0] == f"sync-1:1/{len(keys)}" and len(set(keys)) == len(keys)


def test_bulk_upsert_respects_custom_limits(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/products:bulk-upsert", _bulk_echo)
    with make_client(api, sleeps, max_body_bytes=4096, max_batch_items=7) as client:
        client.products.bulk_upsert(_catalog(40, description_size=10))
    assert all(len(call.request.content) <= 4096 for call in api.calls)
    assert all(len(call.json()["products"]) <= 7 for call in api.calls)


def test_duplicates_are_rejected_locally_like_the_server(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/products:bulk-upsert", _bulk_echo)
    items = [
        {"external_id": "a", "title": "A"},
        {"external_id": "b", "title": "B"},
        {"external_id": "a", "title": "A again"},
    ]
    with make_client(api, sleeps) as client:
        result = client.products.bulk_upsert(items)
    assert [p["title"] for p in api.last().json()["products"]] == ["A", "B"]
    assert result.accepted_count == 2 and result.rejected_count == 1
    assert result.failures[0].external_id == "a"


def test_oversized_single_item_is_rejected_before_sending(
    api: MockAPI, sleeps: List[float]
) -> None:
    with make_client(api, sleeps) as client, pytest.raises(g.InputValidationError, match="sku-big"):
        client.products.bulk_upsert(
            [{"external_id": "sku-big", "title": "x", "description": "x" * 20_000}]
        )
    assert api.calls == []


def test_partial_result_is_attached_on_failure(api: MockAPI, sleeps: List[float]) -> None:
    calls = {"n": 0}

    def second_fails(request: httpx.Request) -> Any:
        calls["n"] += 1
        return _bulk_echo(request) if calls["n"] == 1 else error(422, "validation_failed")

    api.on("POST", "/v1/products:bulk-upsert", second_fails)
    with make_client(api, sleeps) as client, pytest.raises(g.RequestValidationError) as info:
        client.products.bulk_upsert(_catalog(200))
    partial = info.value.partial_result  # type: ignore[attr-defined]
    assert (
        partial.created_count == len(api.calls[0].json()["products"]) and partial.request_count == 1
    )


def test_event_batches_are_chunked_and_summed(api: MockAPI, sleeps: List[float]) -> None:
    def echo(request: httpx.Request) -> Dict[str, Any]:
        return event_batch(accepted=len(json.loads(request.content)["events"]))

    api.on("POST", "/v1/events/batches", echo)
    events = [
        g.EventInput(
            event_type=g.EventType.VIEW,
            user_id=f"u{i}",
            external_product_id="sku-1",
            context={"page": "p" * 100},
        )
        for i in range(400)
    ]
    with make_client(api, sleeps) as client:
        result = client.events.create_batch(events)
    assert result.accepted_count == 400 and len(result.batches) == len(api.calls) > 1
    assert all(len(call.request.content) <= 16_384 for call in api.calls)
    first_ids = [e["event_id"] for e in api.calls[0].json()["events"]]
    assert first_ids[0] == events[0].event_id


def test_event_batch_partial_result(api: MockAPI, sleeps: List[float]) -> None:
    api.queue(
        "POST", "/v1/events/batches", event_batch(accepted=1), error(413, "payload_too_large")
    )
    events = [{"event_type": "view", "context": {"x": "y" * 500}} for _ in range(60)]
    with make_client(api, sleeps) as client, pytest.raises(g.PayloadTooLargeError) as info:
        client.events.create_batch(events)
    assert info.value.partial_result.accepted_count == 1  # type: ignore[attr-defined]


def test_empty_bulk_inputs_are_rejected(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps) as client:
        with pytest.raises(g.InputValidationError):
            client.products.bulk_upsert([])
        with pytest.raises(g.InputValidationError):
            client.events.create_batch([])
