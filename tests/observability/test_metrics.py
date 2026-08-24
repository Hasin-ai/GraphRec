"""What the metrics layer promises, and the two ways it could quietly break.

The failure modes worth a test here are not "does the counter go up". They are:

* **Cardinality.** A `route` label carrying real identifiers is a production
  outage and a data-retention problem at once, and it is invisible in
  development because a developer has three products.
* **Silence.** A gauge that is only written when it is non-zero keeps its last
  value forever. The queue-depth alert would then fire on a queue that drained
  an hour ago, and never fire on a job type that has never had work.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from graphrec.observability.metrics import (
    HTTP_DURATION,
    HTTP_REQUESTS,
    LATENCY_BUCKETS,
    REGISTRY,
    reset_metrics_for_test,
)
from graphrec.observability.middleware import UNMATCHED, MetricsMiddleware


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_metrics_for_test()
    yield
    reset_metrics_for_test()


@pytest.fixture
def measured_app() -> TestClient:
    app = FastAPI()

    @app.get("/v1/products/{product_id}")
    async def one(product_id: str) -> dict[str, str]:
        return {"product_id": product_id}

    @app.get("/v1/boom")
    async def boom() -> None:
        raise RuntimeError("no")

    app.add_middleware(MetricsMiddleware, app_name="test_app")
    return TestClient(app, raise_server_exceptions=False)


def _series(name: str) -> dict[tuple[tuple[str, str], ...], float]:
    found: dict[tuple[tuple[str, str], ...], float] = {}
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == name:
                found[tuple(sorted(sample.labels.items()))] = sample.value
    return found


def test_the_route_label_is_the_template_not_the_path(measured_app) -> None:
    """One series for a thousand products, not a thousand series.

    This is the whole reason the middleware reads `scope["route"]` after the
    call instead of `scope["path"]` before it.
    """
    for product in ("p-1", "p-2", "p-3"):
        measured_app.get(f"/v1/products/{product}")

    counted = _series("graphrec_http_requests_total")
    routes = {dict(labels)["route"] for labels in counted}
    assert routes == {"/v1/products/{product_id}"}
    assert sum(counted.values()) == 3


def test_no_identifier_reaches_a_label(measured_app) -> None:
    """Asserted against the exposition text, which is what leaves the process."""
    measured_app.get("/v1/products/a-very-distinctive-identifier")

    assert b"a-very-distinctive-identifier" not in generate_latest(REGISTRY)


def test_an_unmatched_path_is_one_series_not_one_per_probe(measured_app) -> None:
    """A scanner walking invented paths must not be able to grow the registry.

    Worth counting rather than dropping: a spike of these is a scan, and a
    metric that omitted them would make the quietest possible incident.
    """
    for path in ("/wp-admin", "/.env", "/phpmyadmin"):
        measured_app.get(path)

    counted = _series("graphrec_http_requests_total")
    routes = {dict(labels)["route"] for labels in counted}
    assert routes == {UNMATCHED}
    assert sum(counted.values()) == 3


def test_a_handler_that_raises_is_counted_as_a_500(measured_app) -> None:
    """An ASGI app returns nothing, so a status not seen is a status guessed.

    It is guessed as 500 deliberately: a request that vanishes from the count is
    a request that never shows up on the error rate.
    """
    measured_app.get("/v1/boom")

    counted = _series("graphrec_http_requests_total")
    statuses = {dict(labels)["status"] for labels in counted}
    assert statuses == {"500"}


def test_the_latency_buckets_can_resolve_the_alert_they_exist_for() -> None:
    """§24 alerts on inference P95 > 300 ms.

    A histogram can only place a quantile within a bucket, so without a boundary
    at 0.3 the alert is decided by whatever the surrounding boundaries happen to
    be. The default client buckets jump 0.25 to 0.5.
    """
    assert 0.3 in LATENCY_BUCKETS
    around = [b for b in LATENCY_BUCKETS if 0.1 <= b <= 0.5]
    assert len(around) >= 4, around


def test_in_flight_returns_to_zero_even_when_a_handler_raises(measured_app) -> None:
    """The decrement is in a `finally` for this reason.

    A gauge that leaks on the error path climbs forever and eventually reads as
    a permanently saturated service.
    """
    measured_app.get("/v1/boom")
    measured_app.get("/v1/products/x")

    in_flight = _series("graphrec_http_requests_in_flight")
    assert set(in_flight.values()) == {0.0}


def test_duration_and_count_agree_on_how_many_requests_happened(measured_app) -> None:
    """Two metrics written from one `finally`, so they cannot disagree.

    Worth pinning: a dashboard divides one by the other to get an average, and a
    version of this middleware that observed the histogram on the success path
    only would report a service that gets faster as it breaks.
    """
    measured_app.get("/v1/products/x")
    measured_app.get("/v1/boom")

    observed = sum(_series("graphrec_http_request_duration_seconds_count").values())
    counted = sum(_series("graphrec_http_requests_total").values())
    assert observed == counted == 2


def test_reset_actually_empties_the_registry(measured_app) -> None:
    """The fixture above is load-bearing for every other test in this file.

    A `reset_metrics_for_test` that did nothing would leave each test asserting
    over the accumulated state of the ones before it, which passes for as long
    as the assertions are `>=` and fails mysteriously the first time one is not.
    """
    measured_app.get("/v1/products/x")
    assert _series("graphrec_http_requests_total")

    reset_metrics_for_test()

    assert _series("graphrec_http_requests_total") == {}
    assert _series("graphrec_http_request_duration_seconds_count") == {}
    # And the collectors are the same objects the application holds.
    assert HTTP_REQUESTS._name == "graphrec_http_requests"
    assert HTTP_DURATION._name == "graphrec_http_request_duration_seconds"
