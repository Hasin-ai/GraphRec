"""Design tests 4 and 5: what gets retried, and what a retry sends.

Test 4 is the pair. A rate limit and an exhausted quota are both `429` and both
`class: "limit"`, and a client that treated them alike would either give up on a
wait of two seconds or hammer an allowance that will not reset until the billing
period does.

Test 5 is the one that would have caught the convenience the design rejected:
generating `batch_id` inside the SDK. It would have looked like an improvement,
and it would have turned every retry into a second submission of the same five
thousand events under a key the server had never seen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from graphrec_sdk import (
    APITimeoutError,
    CallOptions,
    PermissionDeniedError,
    QuotaExhaustedError,
    RateLimitedError,
    TransportError,
    UnavailableError,
    ValidationError,
)
from tests.sdk.conftest import Recorder, Reply, envelope, make_client
from tests.sdk.fixtures import ACCEPTED, RECOMMENDATION

if TYPE_CHECKING:
    from collections.abc import Iterator

EVENT = {
    "event_id": "e-1",
    "customer_id": "c-1",
    "external_product_id": "sku-1",
    "event_type": "view",
    "occurred_at": "2026-08-24T10:00:00Z",
}


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """Records what the transport *would* have waited, and waits none of it.

    Retries are exercised deliberately here; a suite that slept for real would
    eventually be made fast by shortening the budget rather than by fixing the
    test.
    """
    recorded: list[float] = []
    monkeypatch.setattr(
        "graphrec_sdk.transport.time.sleep", lambda seconds: recorded.append(seconds)
    )
    return recorded


UNAVAILABLE = Reply(status=503, body=envelope("unavailable", "service_unavailable", retryable=True))


def test_retries_a_503_because_the_server_called_it_retryable(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE, Reply(body=RECOMMENDATION)])
    with make_client(recorder, max_retries=2) as client:
        answer = client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert answer.request_id == RECOMMENDATION["request_id"]
    assert len(recorder.calls) == 2
    assert len(slept) == 1


def test_waits_exactly_as_long_as_it_was_told_to(slept: list[float]) -> None:
    recorder = Recorder(
        replies=[
            Reply(
                status=429,
                body=envelope("limit", "rate_limited", retry_after_seconds=41, retryable=True),
            ),
            Reply(body=RECOMMENDATION),
        ]
    )
    with make_client(recorder, max_retries=2, timeout=120.0) as client:
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    # Not jittered backoff. `graphrec/http/rate_limit.py` computes the seconds
    # left in the window, so waiting less is a guaranteed second rejection.
    assert slept == [41.0]


def test_does_not_retry_an_exhausted_quota_not_even_once(slept: list[float]) -> None:
    recorder = Recorder(
        replies=[Reply(status=429, body=envelope("limit", "recommendation_quota_exhausted"))]
    )
    with make_client(recorder, max_retries=5) as client, pytest.raises(QuotaExhaustedError):
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 1
    assert slept == []


def test_does_not_retry_a_validation_failure_which_will_be_refused_identically(
    slept: list[float],
) -> None:
    recorder = Recorder(replies=[Reply(status=422, body=envelope("validation", "invalid_request"))])
    with make_client(recorder, max_retries=5) as client, pytest.raises(ValidationError):
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 1


def test_does_not_retry_a_403_because_no_number_of_attempts_grants_a_scope(
    slept: list[float],
) -> None:
    recorder = Recorder(replies=[Reply(status=403, body=envelope("auth", "insufficient_scope"))])
    with make_client(recorder, max_retries=5) as client, pytest.raises(PermissionDeniedError):
        client.submissions.get("s-1")

    assert len(recorder.calls) == 1


def test_retries_a_connection_failure_and_names_tls_when_it_gives_up(
    slept: list[float],
) -> None:
    recorder = Recorder(replies=[Reply(raises=httpx.ConnectError("connection refused"))])
    with make_client(recorder, max_retries=2) as client, pytest.raises(TransportError) as caught:
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    # "connection refused" is not a diagnosis when both edges pin TLS 1.3 and a
    # handshake failure never becomes an HTTP status.
    assert "TLS 1.3" in str(caught.value)
    assert caught.value.reference is None
    assert len(recorder.calls) == 3


def test_a_read_timeout_becomes_a_timeout_not_a_transport_error(slept: list[float]) -> None:
    recorder = Recorder(replies=[Reply(raises=httpx.ReadTimeout("timed out"))])
    with make_client(recorder, max_retries=0) as client, pytest.raises(APITimeoutError):
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")


def test_stops_at_max_retries(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE])
    with make_client(recorder, max_retries=3) as client, pytest.raises(UnavailableError):
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 4


def test_the_budget_is_a_deadline_not_an_attempt_count(slept: list[float]) -> None:
    recorder = Recorder(
        replies=[
            Reply(
                status=429,
                body=envelope("limit", "rate_limited", retry_after_seconds=60, retryable=True),
            )
        ]
    )
    # A minute of backoff does not fit in a one-second budget, so the caller gets
    # the rate limit itself rather than a hot path blocked for a minute.
    with (
        make_client(recorder, max_retries=5, timeout=1.0) as client,
        pytest.raises(RateLimitedError),
    ):
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert len(recorder.calls) == 1
    assert slept == []


def _keys(recorder: Recorder, key: str) -> list[Any]:
    return [body[key] for body in recorder.bodies]


def test_a_retry_resends_the_identical_batch_id(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE, Reply(status=202, body=ACCEPTED)])
    with make_client(recorder, max_retries=2) as client:
        client.events.submit_batch(batch_id="nightly-2026-08-24", events=[EVENT])

    assert _keys(recorder, "batch_id") == ["nightly-2026-08-24", "nightly-2026-08-24"]


def test_a_retry_resends_the_identical_sync_id_and_the_identical_products(
    slept: list[float],
) -> None:
    recorder = Recorder(
        replies=[Reply(raises=httpx.ConnectError("reset")), Reply(status=202, body=ACCEPTED)]
    )
    with make_client(recorder, max_retries=2) as client:
        client.catalog.sync(sync_id="sync-1", products=[{"external_id": "sku-1", "title": "T"}])

    assert recorder.bodies[0] == recorder.bodies[1]
    assert _keys(recorder, "sync_id") == ["sync-1", "sync-1"]


def test_a_retry_resends_the_identical_request_id_which_feedback_will_refer_to(
    slept: list[float],
) -> None:
    recorder = Recorder(replies=[UNAVAILABLE, Reply(body=RECOMMENDATION)])
    with make_client(recorder, max_retries=2) as client:
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    assert _keys(recorder, "request_id") == ["r-1", "r-1"]


def test_a_caller_supplied_trace_id_rides_on_every_attempt(slept: list[float]) -> None:
    recorder = Recorder(replies=[UNAVAILABLE, Reply(body=RECOMMENDATION)])
    with make_client(recorder, max_retries=2) as client:
        client.recommendations.for_customer(
            request_id="r-1", customer_id="c-1", options=CallOptions(request_id="trace-abc")
        )

    assert [call.headers["X-Request-Id"] for call in recorder.calls] == ["trace-abc", "trace-abc"]


def test_a_per_call_timeout_overrides_the_client_budget(slept: list[float]) -> None:
    recorder = Recorder(
        replies=[
            Reply(
                status=429,
                body=envelope("limit", "rate_limited", retry_after_seconds=5, retryable=True),
            ),
            Reply(body=RECOMMENDATION),
        ]
    )
    with make_client(recorder, max_retries=2, timeout=1.0) as client:
        client.recommendations.for_customer(
            request_id="r-1", customer_id="c-1", options=CallOptions(timeout=30.0)
        )

    # Seconds, not milliseconds — the divergence from the TypeScript client is
    # deliberate, because `httpx` and `time.sleep` both take seconds.
    assert slept == [5.0]
    assert len(recorder.calls) == 2
