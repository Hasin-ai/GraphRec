"""The async client is a second implementation, so it gets a second suite.

`resources/__init__.py` single-sources every spec and decoder, and `_retry.py`
single-sources the policy — but the loop itself is written twice, once around
`time.sleep` and once around `anyio.sleep`. Twice-written is twice-breakable.
These are the same assertions the blocking suite makes, awaited.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from graphrec_sdk import (
    APITimeoutError,
    QuotaExhaustedError,
    SubmissionFailedError,
    UnavailableError,
)
from tests.sdk.conftest import CONTROL, DATA, Recorder, Reply, envelope, make_async_client
from tests.sdk.fixtures import ACCEPTED, FAILED, FEEDBACK, RECEIPT, RECOMMENDATION, SUCCEEDED

if TYPE_CHECKING:
    from collections.abc import Iterator

UNAVAILABLE = Reply(status=503, body=envelope("unavailable", "service_unavailable", retryable=True))


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr("graphrec_sdk.transport.anyio.sleep", record)
    return recorded


async def test_a_recommendation_round_trips() -> None:
    recorder = Recorder(replies=[Reply(body=RECOMMENDATION)])
    async with make_async_client(recorder) as client:
        answer = await client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert str(recorder.calls[0].url) == f"{DATA}/v1/recommendations"
    assert answer.items[0].rank == 1


async def test_every_namespace_answers_on_the_host_it_belongs_to() -> None:
    recorder = Recorder(
        replies=[
            Reply(body=RECOMMENDATION),
            Reply(body=FEEDBACK),
            Reply(body=RECEIPT),
            Reply(status=202, body=ACCEPTED),
            Reply(body=SUCCEEDED),
        ]
    )
    async with make_async_client(recorder) as client:
        await client.recommendations.for_session(request_id="r-1", session_id="s-1")
        await client.feedback.clicks(
            request_id="r-1", events=[{"event_id": "e-1", "external_product_id": "sku-1"}]
        )
        await client.events.submit(
            event_id="e-1",
            customer_id="c-1",
            external_product_id="sku-1",
            event_type="view",
            occurred_at="2026-08-24T10:00:00Z",
        )
        await client.catalog.sync(sync_id="s-1", products=[{"external_id": "sku-1", "title": "T"}])
        await client.submissions.get("sub-1")

    hosts = [f"{call.url.scheme}://{call.url.netloc.decode()}" for call in recorder.calls]
    assert hosts == [DATA, DATA, CONTROL, CONTROL, CONTROL]


async def test_it_retries_what_the_blocking_client_retries(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE, Reply(body=RECOMMENDATION)])
    async with make_async_client(recorder, max_retries=2) as client:
        await client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 2
    assert len(slept) == 1


async def test_it_declines_to_retry_what_the_blocking_client_declines(
    slept: list[float],
) -> None:
    recorder = Recorder(
        replies=[Reply(status=429, body=envelope("limit", "recommendation_quota_exhausted"))]
    )
    async with make_async_client(recorder, max_retries=5) as client:
        with pytest.raises(QuotaExhaustedError):
            await client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 1
    assert slept == []


async def test_a_retry_resends_the_identical_batch_id(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE, Reply(status=202, body=ACCEPTED)])
    async with make_async_client(recorder, max_retries=2) as client:
        await client.events.submit_batch(
            batch_id="nightly-2026-08-24",
            events=[
                {
                    "event_id": "e-1",
                    "customer_id": "c-1",
                    "external_product_id": "sku-1",
                    "event_type": "view",
                    "occurred_at": "2026-08-24T10:00:00Z",
                }
            ],
        )

    assert [body["batch_id"] for body in recorder.bodies] == [
        "nightly-2026-08-24",
        "nightly-2026-08-24",
    ]


async def test_it_gives_up_where_the_blocking_client_gives_up(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE])
    async with make_async_client(recorder, max_retries=3) as client:
        with pytest.raises(UnavailableError):
            await client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 4


async def test_a_read_timeout_becomes_a_timeout() -> None:
    recorder = Recorder(replies=[Reply(raises=httpx.ReadTimeout("timed out"))])
    async with make_async_client(recorder) as client:
        with pytest.raises(APITimeoutError):
            await client.recommendations.for_customer(request_id="r-1", customer_id="c-1")


async def test_wait_polls_and_raises_the_same_submission_failure(slept: list[float]) -> None:
    recorder = Recorder(replies=[Reply(body=ACCEPTED), Reply(body=FAILED)])
    async with make_async_client(recorder) as client:
        with pytest.raises(SubmissionFailedError) as caught:
            await client.submissions.wait("sub-1", timeout=30)

    assert [item.ref for item in caught.value.submission.errors] == ["sku-1"]
    assert len(recorder.calls) == 2
    # A poll that is not terminal sleeps; the async loop has to await that sleep
    # rather than block the event loop for every other request in the process.
    assert slept == [0.5]


async def test_closing_twice_is_not_an_error() -> None:
    recorder = Recorder(replies=[Reply(body=RECOMMENDATION)])
    client = make_async_client(recorder)
    await client.recommendations.for_customer(request_id="r-1", customer_id="c-1")
    await client.aclose()
    await client.aclose()
