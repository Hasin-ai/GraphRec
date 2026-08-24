"""The metrics this platform publishes, defined once.

Every counter and histogram lives here rather than beside the code that
increments it. Two reasons, and the second is the one that matters:

* A metric's name and labels are a contract with a dashboard and an alert rule,
  and a contract scattered across nine modules gets renamed by whoever touches
  it last. `docs/observability/` reads this file.
* **Label cardinality is a production failure mode, not a style question.** A
  `path` label carrying `/v1/products/{id}` with real identifiers substituted
  creates one time series per product and takes Prometheus down. So the HTTP
  metrics label the *route template*, and the only identifier that appears
  anywhere below is `tenant_id`, on the serving gauges, where the alert §24 asks
  for — "`ready < 1` for an active tenant" — cannot be written without it. The
  tenant count is bounded by the estate and Prometheus is on the private
  network (§9.1).

Names follow the Prometheus convention: `graphrec_` prefix, base units (seconds
and bytes, never milliseconds), `_total` on counters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

if TYPE_CHECKING:
    from collections.abc import Iterator

#: A registry of our own rather than `prometheus_client.REGISTRY`.
#:
#: The default registry is global and pre-populated with the process and GC
#: collectors, which makes two things awkward: a test cannot get a clean slate,
#: and a metric defined twice — which happens the moment a module is reloaded —
#: raises at import time rather than at the call site. Ours is explicit, and
#: `reset_metrics_for_test` empties it.
REGISTRY: Final = CollectorRegistry()

#: Buckets chosen against the alert, not against a default.
#:
#: §24 alerts on inference P95 > 300 ms, and a P95 computed from a histogram is
#: only as precise as the bucket it lands in. The default client buckets jump
#: 0.25 → 0.5, so a P95 anywhere in that gap reads as 0.5 and the alert fires on
#: a service answering in 260 ms. These have a boundary *at* 0.3 and three more
#: around it.
LATENCY_BUCKETS: Final = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.15,
    0.2,
    0.25,
    0.3,
    0.4,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    10.0,
)

#: Jobs and training runs live on a different scale entirely — a training run is
#: minutes — so they get their own ladder rather than sharing one that would put
#: every observation in `+Inf`.
JOB_DURATION_BUCKETS: Final = (1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 1800.0, 3600.0, 7200.0)


# --------------------------------------------------------------------- http

HTTP_REQUESTS: Final = Counter(
    "graphrec_http_requests_total",
    "HTTP requests served, by route template and outcome.",
    ("app", "method", "route", "status"),
    registry=REGISTRY,
)

HTTP_DURATION: Final = Histogram(
    "graphrec_http_request_duration_seconds",
    "Wall time from first byte of the request to the response being sent.",
    ("app", "method", "route"),
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)

HTTP_IN_FLIGHT: Final = Gauge(
    "graphrec_http_requests_in_flight",
    "Requests currently being served.",
    ("app",),
    registry=REGISTRY,
)


# ---------------------------------------------------------------- inference

RECOMMENDATIONS: Final = Counter(
    "graphrec_recommendations_total",
    "Recommendation responses served, by the strategy that produced them.",
    # `strategy` is what the response reports (ER-F-05) and `degraded` says
    # whether the model lane was available at all. Two labels rather than one
    # because "popularity because this user is cold" and "popularity because the
    # model store is unreachable" are the same strategy and opposite incidents,
    # and §24's "fallback > 5%" alert means only the second.
    ("strategy", "degraded"),
    registry=REGISTRY,
)

INFERENCE_READY: Final = Gauge(
    "graphrec_inference_ready",
    "1 when a verified bundle is resident and this process will serve it.",
    ("tenant_id",),
    registry=REGISTRY,
)


# --------------------------------------------------------------------- jobs

JOBS_FINISHED: Final = Counter(
    "graphrec_jobs_finished_total",
    "Jobs that reached a terminal state, by type and outcome.",
    ("job_type", "outcome"),
    registry=REGISTRY,
)

JOB_DURATION: Final = Histogram(
    "graphrec_job_duration_seconds",
    "Wall time from lease to terminal state.",
    ("job_type",),
    buckets=JOB_DURATION_BUCKETS,
    registry=REGISTRY,
)

JOB_QUEUE_DEPTH: Final = Gauge(
    "graphrec_job_queue_depth",
    "Jobs not yet in a terminal state, by type and status.",
    ("job_type", "status"),
    registry=REGISTRY,
)

JOB_QUEUE_OLDEST_SECONDS: Final = Gauge(
    "graphrec_job_queue_oldest_seconds",
    "Age of the oldest queued job. Depth alone cannot distinguish a busy queue "
    "from a stuck one; this can.",
    ("job_type",),
    registry=REGISTRY,
)


# ------------------------------------------------------------------ serving

SERVING_REPLICAS: Final = Gauge(
    "graphrec_serving_replicas",
    "Serving replicas for a tenant, by state. `ready` is what §24 alerts on.",
    ("tenant_id", "state"),
    registry=REGISTRY,
)


# ------------------------------------------------------------------ metering

METERING_DEGRADED: Final = Counter(
    "graphrec_metering_degraded_total",
    "Times a usage count fell back from the cache to the in-process counter. "
    "Not an error — see `ResilientUsageCounters` — but it is a measurement gap, "
    "and UC-30 says a gap is reported, never absorbed.",
    registry=REGISTRY,
)


# --------------------------------------------------------------- rate limits

RATE_LIMITED: Final = Counter(
    "graphrec_rate_limited_total",
    "Requests refused with a 429 by one of the five configured limit classes.",
    ("limit",),
    registry=REGISTRY,
)

RATE_LIMIT_UNAVAILABLE: Final = Counter(
    "graphrec_rate_limit_unavailable_total",
    "Times the limiter could not reach Redis and allowed the request through. "
    "A security control that has silently stopped applying is worse than one "
    "that is failing loudly, so it is counted rather than left to the logs.",
    ("limit",),
    registry=REGISTRY,
)


# --------------------------------------------------------------------- build

BUILD_INFO: Final = Gauge(
    "graphrec_build_info",
    "Always 1. The labels are the payload: which version is running where.",
    ("app", "version"),
    registry=REGISTRY,
)


def record_build_info(app: str, version: str) -> None:
    """Publish what is running. Called once, at startup.

    Its value is that a deploy is visible on a dashboard as a change in this
    series, so a graph that turns bad at 14:02 can be lined up against the
    release that landed at 14:01 without leaving the page.
    """
    BUILD_INFO.labels(app=app, version=version).set(1)


def all_metric_names() -> Iterator[str]:
    """The published names, for the test that holds alert rules to them."""
    for metric in REGISTRY.collect():
        yield metric.name


def reset_metrics_for_test() -> None:
    """Zero every series. Tests only.

    `clear()` per collector rather than a fresh registry, because the module
    level objects above are what the application code holds references to and
    rebinding them would leave every importer pointing at the old ones.
    """
    for collector in (
        HTTP_REQUESTS,
        HTTP_DURATION,
        HTTP_IN_FLIGHT,
        RECOMMENDATIONS,
        INFERENCE_READY,
        JOBS_FINISHED,
        JOB_DURATION,
        JOB_QUEUE_DEPTH,
        JOB_QUEUE_OLDEST_SECONDS,
        SERVING_REPLICAS,
        METERING_DEGRADED,
        BUILD_INFO,
    ):
        collector.clear()
