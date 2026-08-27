"""The README's code, compiled and executed.

Every region here is byte-identical to the block that follows the matching
`<!-- example: NAME -->` marker in `sdk/python/README.md`, and `test_readme.py`
asserts both halves of that: the text matches, and the code runs against the
real client. Documentation that is only proofread drifts; documentation that is
executed cannot.

The functions take `gr` as an argument so the suite can hand them a client wired
to a mock transport, and the constructor examples build their own so the README
can show what a caller actually writes.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graphrec_sdk import GraphRec, RecommendationResponse


def importing() -> object:
    # region importing
    from graphrec_sdk import GraphRec

    # endregion importing
    return GraphRec


def construct() -> GraphRec:
    # region construct
    import os

    from graphrec_sdk import GraphRec

    gr = GraphRec(
        api_key=os.environ["GRAPHREC_API_KEY"],
        tenant_id=os.environ["GRAPHREC_TENANT_ID"],
        domain="graphrec.example",
    )
    # endregion construct
    return gr


async def asynchronous() -> RecommendationResponse:
    import os
    import uuid

    # region asynchronous
    from graphrec_sdk import AsyncGraphRec

    async with AsyncGraphRec(
        api_key=os.environ["GRAPHREC_API_KEY"],
        tenant_id=os.environ["GRAPHREC_TENANT_ID"],
        domain="graphrec.example",
    ) as gr:
        answer = await gr.recommendations.for_customer(
            request_id=str(uuid.uuid4()), customer_id="customer-1"
        )
    # endregion asynchronous
    return answer


def recommend(gr: GraphRec) -> RecommendationResponse:
    # region recommend
    import uuid

    answer = gr.recommendations.for_customer(
        request_id=str(uuid.uuid4()),
        customer_id="customer-1",
        top_n=10,
        recent_events=[{"external_product_id": "sku-1", "event_type": "view"}],
        exclude_product_ids=["sku-9"],
    )

    for item in answer.items:
        print(item.rank, item.external_product_id, item.score)
    # endregion recommend
    return answer


def report(gr: GraphRec, answer: RecommendationResponse) -> None:
    # region report
    gr.feedback.impressions(
        request_id=answer.request_id,
        events=[
            {
                "event_id": f"{answer.request_id}:{item.external_product_id}",
                "external_product_id": item.external_product_id,
            }
            for item in answer.items
        ],
    )

    gr.feedback.conversions(
        request_id=answer.request_id,
        events=[{"event_id": "order-4471", "external_product_id": "sku-1", "value": 19.99}],
    )
    # endregion report


def sync(gr: GraphRec) -> None:
    # region sync
    accepted = gr.catalog.sync(
        sync_id="2026-08-24-nightly",
        products=[{"external_id": "sku-1", "title": "Example product", "price": "19.99"}],
    )
    finished = gr.submissions.wait(accepted.submission_id, timeout=120)
    print(finished.counts)
    # endregion sync


def ingest(gr: GraphRec) -> object:
    # region ingest
    from datetime import datetime, timezone

    receipt = gr.events.submit(
        event_id="11111111-1111-4111-8111-111111111111",
        customer_id="customer-1",
        external_product_id="sku-1",
        event_type="view",
        occurred_at=datetime.now(timezone.utc),
    )
    # endregion ingest
    return receipt


def handle(gr: GraphRec) -> RecommendationResponse | None:
    import uuid

    # region handle
    from graphrec_sdk import QuotaExhaustedError, RateLimitedError, RecommendationResponse

    def recommend_or_fall_back(customer_id: str) -> RecommendationResponse | None:
        try:
            return gr.recommendations.for_customer(
                request_id=str(uuid.uuid4()), customer_id=customer_id
            )
        except QuotaExhaustedError:
            return None  # Waiting will not help: the allowance resets with the period.
        except RateLimitedError:
            return None  # The SDK already retried inside your timeout budget.

    # endregion handle
    return recommend_or_fall_back("customer-1")


def failed(gr: GraphRec) -> list[str]:
    # region failed
    from graphrec_sdk import SubmissionFailedError

    def sync_and_report(sync_id: str, products: list[dict]) -> list[str]:
        accepted = gr.catalog.sync(sync_id=sync_id, products=products)
        try:
            gr.submissions.wait(accepted.submission_id)
        except SubmissionFailedError as failure:
            return [f"{item.ref}: {item.reason}" for item in failure.submission.errors]
        return []

    # endregion failed
    return sync_and_report("s-1", [{"external_id": "sku-1", "title": "T"}])


__all__ = [
    "asynchronous",
    "construct",
    "failed",
    "handle",
    "importing",
    "ingest",
    "recommend",
    "report",
    "sync",
]

_: Any = None
