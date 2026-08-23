"""NR-NF-04: the 95th percentile of a recommendation stays under 300 ms.

This is the one exit criterion of the phase that cannot be asserted by reading
a row — it is a claim about how the whole path behaves when several callers are
in it at once, so it is measured through the real ASGI application with a real
database and a real bundle.

**Two clocks, and the difference between them matters.**

`server` is what the service spent on a request, recorded on
`recommendation_requests.latency_ms` and reported to the tenant by
`/v1/metrics/summary`. That is the measurement NR-NF-04 names, and it is what
the assertion below is made against.

`wall` is what this test's caller waited, which includes queueing. It is
printed but only loosely bounded, because in this harness the queue is an
artefact of the harness: `httpx.ASGITransport` runs the application in the same
event loop — on the same CPU — as the client generating the load, so ten
in-flight requests are ten coroutines taking turns on one thread. In a
deployment they are spread over `min_replicas` processes that Compose
round-robins between. Asserting the caller's clock here would pin a number
about Python's scheduler and would fail on any slower machine, which is a worse
outcome than not measuring it: an exit criterion that goes red for reasons
unrelated to the service stops being read.

Marked `slow`, because a suite that takes twenty seconds to prove a latency
budget is a suite people stop running.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import httpx
import pytest

pytestmark = [pytest.mark.db, pytest.mark.slow]

#: The requirement, verbatim (NR-NF-04).
P95_BUDGET_MS = 300

#: A collapse guard on the caller's clock, not a budget. Three times the
#: requirement catches "the whole thing fell over" without pretending the
#: harness's own scheduling is the service's latency.
WALL_CEILING_MS = P95_BUDGET_MS * 3

#: Enough for a 95th percentile to mean something — at 20 requests the p95 is
#: "the slowest one", which measures the unluckiest garbage collection rather
#: than the service.
REQUESTS = 200

#: Several callers at once, because the interesting contention is the
#: connection pool and the shared index, and a serial loop exercises neither.
CONCURRENCY = 10


class _Timings:
    """Both clocks, kept together so a run reports one story."""

    def __init__(self) -> None:
        self.wall: list[float] = []
        self.server: list[int] = []

    def p95(self, samples: list[float] | list[int]) -> float:
        ordered = sorted(samples)
        return float(ordered[int(len(ordered) * 0.95)])

    def report(self, label: str) -> str:
        return (
            f"\n{label}: n={len(self.wall)} concurrency={CONCURRENCY} "
            f"server_median={statistics.median(self.server):.0f}ms "
            f"server_p95={self.p95(self.server):.0f}ms "
            f"server_max={max(self.server)}ms | "
            f"wall_median={statistics.median(self.wall):.0f}ms "
            f"wall_p95={self.p95(self.wall):.0f}ms"
        )


async def _fire(
    client: httpx.AsyncClient, headers: dict[str, str], index: int, timings: _Timings | None
) -> None:
    started = time.perf_counter()
    response = await client.post(
        "/v1/recommendations",
        json={
            "request_id": f"load-{index}",
            # Alternating, so half the requests take the customer path and half
            # the anonymous one. Both are on the hot path in production.
            "customer_id": "CUST-1" if index % 2 else None,
            "session_id": None if index % 2 else f"sess-{index}",
            "top_n": 10,
        },
        headers=headers,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200, response.text
    if timings is not None:
        timings.wall.append(elapsed_ms)
        timings.server.append(int(response.json()["latency_ms"]))


async def _drive(client: httpx.AsyncClient, headers: dict[str, str], count: int) -> _Timings:
    """A warm-up that is discarded, then `count` requests at `CONCURRENCY`.

    The first request through a fresh process pays for the connection pool and
    for SQLAlchemy compiling its statements, and neither is a cost a shopper
    ever pays twice.
    """
    for index in range(CONCURRENCY):
        await _fire(client, headers, -index - 1, None)

    timings = _Timings()
    gate = asyncio.Semaphore(CONCURRENCY)

    async def _bounded(index: int) -> None:
        async with gate:
            await _fire(client, headers, index, timings)

    await asyncio.gather(*(_bounded(index) for index in range(count)))
    return timings


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://inference",
    )


async def test_the_p95_of_a_recommendation_stays_within_the_budget_under_load(
    ready_tenant, pinned_app, issue_credential
) -> None:
    tenant_id, _ = ready_tenant
    headers = {"Authorization": f"Bearer {issue_credential(tenant_id)}"}
    app = pinned_app(tenant_id)

    async with app.router.lifespan_context(app), _client(app) as client:
        assert (await client.get("/readyz")).json()["ready"] is True
        timings = await _drive(client, headers, REQUESTS)

    # Printed unconditionally: a run that passes at 280 ms is a run somebody
    # should see, and a failure naming only the threshold does not say how far
    # away it was.
    print(timings.report("NR-NF-04"))

    server_p95 = timings.p95(timings.server)
    assert (
        server_p95 < P95_BUDGET_MS
    ), f"the served p95 was {server_p95:.0f} ms against a {P95_BUDGET_MS} ms budget (NR-NF-04)"
    assert timings.p95(timings.wall) < WALL_CEILING_MS


async def test_a_fallback_answer_is_also_within_the_budget(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    pinned_app,
    issue_credential,
) -> None:
    """The degraded path is a latency path too.

    A model outage that also made the shop slow would turn one incident into
    two, and the fallback lanes are queries rather than a resident matrix — so
    they are the path most likely to miss the budget, not the least.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id, desired_version_id=version_id)
    headers = {"Authorization": f"Bearer {issue_credential(tenant_id)}"}
    app = pinned_app(tenant_id)

    async with app.router.lifespan_context(app), _client(app) as client:
        assert (await client.get("/readyz")).json()["ready"] is False
        timings = await _drive(client, headers, REQUESTS // 2)

    print(timings.report("NR-NF-04 (fallback)"))

    server_p95 = timings.p95(timings.server)
    assert (
        server_p95 < P95_BUDGET_MS
    ), f"the fallback p95 was {server_p95:.0f} ms against a {P95_BUDGET_MS} ms budget"
    assert timings.p95(timings.wall) < WALL_CEILING_MS
