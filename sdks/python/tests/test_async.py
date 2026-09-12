from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Dict, List

import httpx
import pytest

import graphrec_sdk as g
from graphrec_sdk import resources
from graphrec_sdk.ecommerce import AsyncCatalogSync, AsyncEventTracker, AsyncRecommendationSession

from . import conftest as fx
from .conftest import MockAPI, error, make_async_client

SYNC_TO_ASYNC = {
    resources.Tenants: resources.AsyncTenants,
    resources.Authentication: resources.AsyncAuthentication,
    resources.ApiKeys: resources.AsyncApiKeys,
    resources.Subscriptions: resources.AsyncSubscriptions,
    resources.Usage: resources.AsyncUsage,
    resources.Products: resources.AsyncProducts,
    resources.Events: resources.AsyncEvents,
    resources.Datasets: resources.AsyncDatasets,
    resources.ModelVersions: resources.AsyncModelVersions,
    resources.TrainingJobs: resources.AsyncTrainingJobs,
    resources.Deployment: resources.AsyncDeployment,
    resources.Metrics: resources.AsyncMetrics,
    resources.RecommendationsResource: resources.AsyncRecommendationsResource,
    resources.Feedback: resources.AsyncFeedback,
    resources.Platform: resources.AsyncPlatform,
}


def _public_methods(cls: type) -> Dict[str, Any]:
    return {name: fn for name, fn in vars(cls).items() if callable(fn) and not name.startswith("_")}


@pytest.mark.parametrize("sync_cls", list(SYNC_TO_ASYNC), ids=lambda c: c.__name__)
def test_async_resources_mirror_sync_signatures(sync_cls: type) -> None:
    async_cls = SYNC_TO_ASYNC[sync_cls]
    sync_methods, async_methods = _public_methods(sync_cls), _public_methods(async_cls)
    assert set(sync_methods) == set(async_methods)
    for name, fn in sync_methods.items():
        assert inspect.iscoroutinefunction(async_methods[name]), name
        assert str(inspect.signature(fn)) == str(inspect.signature(async_methods[name])), name


def test_clients_expose_the_same_resources() -> None:
    sync_client = g.GraphRec(use_env=False)
    async_client = g.AsyncGraphRec(use_env=False)
    sync_attrs = {k: type(v) for k, v in vars(sync_client).items() if not k.startswith("_")}
    async_attrs = {k: type(v) for k, v in vars(async_client).items() if not k.startswith("_")}
    assert set(sync_attrs) == set(async_attrs) and len(sync_attrs) == len(SYNC_TO_ASYNC)
    assert all(SYNC_TO_ASYNC[sync_attrs[k]] is async_attrs[k] for k in sync_attrs)
    sync_client.close()
    asyncio.run(async_client.close())


def test_async_storefront_flow(api: MockAPI) -> None:
    api.on("POST", "/v1/products:bulk-upsert", fx.bulk_result(created=2))
    api.on("GET", "/v1/products", {"items": [fx.product("sku-1")], "total": 1})
    api.on(
        "POST",
        "/v1/events/batches",
        lambda req: fx.event_batch(accepted=len(json.loads(req.content)["events"])),
    )
    api.on("POST", "/v1/recommendations", fx.recommendations())
    api.on("POST", "/v1/feedback/impressions", fx.feedback("impression", "imp-1"))
    api.on("POST", "/v1/feedback/clicks", fx.feedback("click"))

    async def main() -> None:
        async with make_async_client(api) as client:
            report = await AsyncCatalogSync(client).run(
                [{"external_id": "sku-1", "title": "A"}, {"external_id": "sku-2", "title": "B"}]
            )
            assert report.upsert.created_count == 2

            async with AsyncEventTracker(client, batch_size=2) as tracker:
                await tracker.view("u1", "sku-1")
                await tracker.add_to_cart("u1", "sku-1")
                await tracker.purchase("u1", "sku-1", order_id="ORD-1")

            session = AsyncRecommendationSession(client)
            recs = await session.recommend(user_id="u1", top_n=3)
            await session.click(recs, "sku-2")

    asyncio.run(main())
    assert api.paths() == [
        "POST /v1/products:bulk-upsert",
        "POST /v1/events/batches",
        "POST /v1/events/batches",
        "POST /v1/recommendations",
        "POST /v1/feedback/impressions",
        "POST /v1/feedback/clicks",
    ]
    assert api.last().json()["impression_event_id"] == "imp-1"


def test_async_retries_and_errors(api: MockAPI) -> None:
    sleeps: List[float] = []
    api.queue(
        "GET", "/v1/products/sku-1", error(429, "rate_limit_exceeded", retry_after=2), fx.product()
    )
    api.on("GET", "/v1/products/missing", lambda _r: error(404, "resource_not_found"))

    async def main() -> None:
        async with make_async_client(api, sleeps) as client:
            product = await client.products.get("sku-1")
            assert product.external_id == "sku-1"
            with pytest.raises(g.NotFoundError):
                await client.products.get("missing")

    asyncio.run(main())
    assert sleeps == [2.0]


def test_async_tracker_background_task(api: MockAPI) -> None:
    api.on("POST", "/v1/events/batches", lambda req: fx.event_batch(accepted=1))

    async def main() -> None:
        async with make_async_client(api) as client:
            async with AsyncEventTracker(client, batch_size=100, flush_interval=0.02) as tracker:
                await tracker.view("u1", "sku-1")
                for _ in range(100):
                    if api.calls:
                        break
                    await asyncio.sleep(0.01)
                assert tracker.pending == 0

    asyncio.run(main())
    assert len(api.calls) == 1


def test_async_timeout_maps_to_api_timeout_error(api: MockAPI) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    api.on("POST", "/v1/training-jobs", slow)

    async def main() -> None:
        async with make_async_client(api) as client:
            with pytest.raises(g.APITimeoutError):
                await client.training_jobs.create()

    asyncio.run(main())
    assert len(api.calls) == 1
