"""Storefront integration in ~40 lines: catalog, events, recommendations, feedback.

export GRAPHREC_BASE_URL=http://localhost:8010
export GRAPHREC_API_KEY=gr_live_...        # scopes: graphrec_sdk.STOREFRONT_KEY_SCOPES
python examples/storefront_quickstart.py
"""

from __future__ import annotations

from graphrec_sdk import GraphRec, NotFoundError
from graphrec_sdk.ecommerce import EventTracker, RecommendationSession

CATALOG = [
    {
        "external_id": "sku-100",
        "title": "Linen shirt",
        "price": "49.90",
        "category": "shirts",
        "metadata": {"brand": "Acme", "color": "white"},
    },
    {
        "external_id": "sku-101",
        "title": "Chino trousers",
        "price": "59.00",
        "category": "trousers",
        "metadata": {"brand": "Acme"},
    },
    {
        "external_id": "sku-102",
        "title": "Canvas sneakers",
        "price": "79.00",
        "category": "shoes",
        "metadata": {"brand": "Stride"},
    },
]


def main() -> None:
    with GraphRec() as client:
        print("API health:", client.health())

        # 1. Keep the catalog in sync (split automatically to respect the 16 KiB body limit).
        result = client.products.bulk_upsert(CATALOG)
        print(f"catalog: created={result.created_count} updated={result.updated_count}")

        # 2. Record what shoppers do. Events are buffered and sent in batches.
        with EventTracker(client, batch_size=50) as tracker:
            tracker.view("customer-42", "sku-100", session_id="sess-1")
            tracker.add_to_cart("customer-42", "sku-100", quantity=1, price="49.90")
            tracker.purchase("customer-42", "sku-100", order_id="ORD-1001", price="49.90")

        # 3. Show recommendations on the product page and report what happened.
        widget = RecommendationSession(client)
        recs = widget.recommend(user_id="customer-42", top_n=4, exclude_product_ids=["sku-100"])
        print(f"strategy={recs.strategy} fallback={recs.fallback_used} items={recs.product_ids}")
        if recs.items:
            clicked = recs.items[0].external_product_id
            widget.click(recs, clicked)
            widget.convert(recs, clicked, value="59.00")

        try:
            client.products.get("does-not-exist")
        except NotFoundError as exc:
            print("expected 404, correlation id:", exc.correlation_id)


if __name__ == "__main__":
    main()
