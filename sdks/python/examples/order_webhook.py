"""Turn an order webhook into purchase events that are safe to replay.

Payment providers and shop platforms retry webhooks. Because each purchase
event ID is derived from ``(order_id, line)``, GraphRec records every order
line exactly once no matter how often the webhook is delivered.

The API key needs the ``events:write`` scope.
"""

from __future__ import annotations

from typing import Any, Dict

from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import EventBuilder

builder = EventBuilder(default_context={"channel": "web"})


def handle_order_paid(client: GraphRec, order: Dict[str, Any]) -> None:
    events = [
        builder.purchase(
            order.get("customer_id"),
            line["sku"],
            order_id=order["id"],
            line=index,
            quantity=line["quantity"],
            price=line["unit_price"],
            currency=order.get("currency"),
        )
        for index, line in enumerate(order["lines"], start=1)
    ]
    result = client.events.create_batch(events)
    print(
        f"order {order['id']}: accepted={result.accepted_count} duplicates={result.duplicate_count}"
    )


if __name__ == "__main__":
    sample = {
        "id": "ORD-2001",
        "customer_id": "customer-42",
        "currency": "EUR",
        "lines": [
            {"sku": "sku-101", "quantity": 1, "unit_price": "59.00"},
            {"sku": "sku-102", "quantity": 2, "unit_price": "79.00"},
        ],
    }
    with GraphRec() as graphrec:
        handle_order_paid(graphrec, sample)
        handle_order_paid(graphrec, sample)  # replay -> duplicates, no double counting
