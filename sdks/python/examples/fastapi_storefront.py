"""Async integration inside a FastAPI storefront backend.

pip install fastapi uvicorn graphrec-sdk
# the key needs graphrec_sdk.STOREFRONT_KEY_SCOPES
GRAPHREC_API_KEY=gr_live_... uvicorn examples.fastapi_storefront:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Request

from graphrec_sdk import APIError, AsyncGraphRec
from graphrec_sdk.ecommerce import AsyncEventTracker, AsyncRecommendationSession


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncGraphRec(timeout=2.0, max_retries=1)  # keep page latency bounded
    tracker = AsyncEventTracker(client, batch_size=200, flush_interval=2.0)
    tracker.start()
    app.state.graphrec = client
    app.state.tracker = tracker
    app.state.recs = AsyncRecommendationSession(client)
    try:
        yield
    finally:
        await tracker.close()
        await client.close()


app = FastAPI(lifespan=lifespan)


def shopper(request: Request) -> Dict[str, Optional[str]]:
    return {
        "user_id": request.headers.get("X-Customer-Id"),
        "session_id": request.cookies.get("sid"),
    }


@app.get("/products/{sku}")
async def product_page(sku: str, request: Request) -> Dict[str, Any]:
    who = shopper(request)
    await app.state.tracker.view(who["user_id"], sku, session_id=who["session_id"])
    try:
        if who["user_id"]:
            recs = await app.state.recs.recommend(
                user_id=who["user_id"], top_n=6, exclude_product_ids=[sku]
            )
        else:
            recs = await app.state.recs.recommend(
                session_id=who["session_id"] or "anonymous", recent_product_ids=[sku], top_n=6
            )
        related: List[str] = recs.product_ids
        request_id: Optional[str] = recs.request_id
    except APIError:
        related, request_id = [], None  # never break the page because recommendations failed
    return {"sku": sku, "related": related, "recommendation_request_id": request_id}


@app.post("/cart")
async def add_to_cart(payload: Dict[str, Any], request: Request) -> Dict[str, str]:
    who = shopper(request)
    await app.state.tracker.add_to_cart(
        who["user_id"],
        payload["sku"],
        quantity=int(payload.get("quantity", 1)),
        session_id=who["session_id"],
    )
    return {"status": "ok"}
