# Performance (NR-NF-04)

This page records what GraphRec was measured to sustain, on which hardware, and how
to repeat the measurement on yours. It is a measurement, not a service-level promise.

## Supported load (reference host)

On the reference host below, one API container with **2 uvicorn workers** sustains
about **80 requests/second** of mixed storefront traffic with **8 concurrent
shoppers**, at **p95 158 ms** overall and **p95 164 ms** for recommendations, with
no errors. That is the supported load for this host.

Beyond about 8 concurrent shoppers throughput does not rise (the two CPUs are
saturated) and requests queue: at 32 concurrent shoppers p95 is about 1.1 s, at 64
about 3.3 s, and one request in 3,900 timed out. Nothing failed with a server error
at any level, and no request was rate limited (the test tenant's limits were raised).

Scale by adding CPU: run more API workers (`WEB_CONCURRENCY`) on a larger host.
Rate limits and admission slots are shared through Redis, so they stay correct
across processes.

## Results

Measured 2026-10-07 with `scripts/load_test.py`, 60 s per run after a 10 s warm-up,
a trained and active DGSR model, 1,000 products, 300 shoppers with 8 views each.
Traffic mix: 70 % recommendations (80 % known shoppers, 20 % anonymous sessions),
20 % single events, 10 % product reads. Latencies in milliseconds. Raw reports are in
`docs/load/`.

| Concurrent shoppers | Requests/s | p50 | p95 | p99 | Failed | 429 |
|---:|---:|---:|---:|---:|---:|---:|
| 1  | 42.0 | 25.9  | 35.1   | 41.1   | 0 | 0 |
| 8  | 83.5 | 96.5  | 157.7  | 183.9  | 0 | 0 |
| 32 | 70.2 | 376.1 | 1074.6 | 1276.4 | 0 | 0 |
| 64 | 64.4 | 539.5 | 3332.0 | 3722.6 | 1 | 0 |

By operation:

| Shoppers | Operation | Requests/s | p50 | p95 | p99 |
|---:|---|---:|---:|---:|---:|
| 1  | recommend | 29.3 | 27.9  | 36.2   | 42.0   |
| 1  | event     | 8.8  | 14.1  | 19.0   | 22.6   |
| 1  | product   | 3.9  | 7.4   | 10.6   | 14.8   |
| 8  | recommend | 57.0 | 110.5 | 164.4  | 191.0  |
| 8  | event     | 17.6 | 69.5  | 120.6  | 142.1  |
| 8  | product   | 8.9  | 32.5  | 58.5   | 72.7   |
| 32 | recommend | 49.8 | 350.7 | 715.7  | 900.0  |
| 32 | event     | 13.7 | 900.6 | 1264.1 | 1415.3 |
| 32 | product   | 6.7  | 120.5 | 256.4  | 421.6  |
| 64 | recommend | 44.5 | 490.9 | 1454.7 | 2884.9 |
| 64 | event     | 13.0 | 2901.8| 3676.3 | 3818.5 |
| 64 | product   | 6.9  | 176.2 | 1582.6 | 3516.5 |

Recommendation strategies served during the runs: personalized for known shoppers,
session-based for anonymous sessions, and popularity fallback for under 1 % of
requests (shoppers whose history had no item known to the model).

**Phase 6 re-run (fresh clone, final code, fresh database):** 8 concurrent shoppers,
79.5 requests/s, p50 103.8 ms, p95 152.6 ms, p99 180.4 ms, 0 failures, 0 timeouts
(`docs/load/phase6-c8.json`). Consistent with the table above.

### Reading the numbers

- **The CPU is the limit.** The reference host has 2 vCPUs, shared by PostgreSQL,
  Redis, Qdrant, the training worker, both API workers *and the load generator*. A
  dedicated host gives better numbers; repeat the test there before planning capacity.
- **Single events degrade first under contention.** At 32 and more concurrent shoppers
  event writes are the slowest operation (p95 1.3 s at 32). Every accepted event takes
  the tenant's `accepted_events` quota lock (a transaction-scoped advisory lock in
  `graphrec_core/usage/limits.py`) so the monthly quota can never be overshot; one
  tenant's events are therefore written one transaction at a time. Storefronts should
  send events in batches (`POST /v1/events/batches`, up to 1,000 events per lock) under
  heavy traffic. The lock is per tenant, so tenants do not wait for each other here.
- **The 64-shopper failure** was one event request; the server logged no error for it.
  The run predates the script's timeout counter, so it was a client timeout (10 s) or a
  transport error. Later reports split timeouts out (`timeouts`).

## Reference host

| | |
|---|---|
| CPU | 2 vCPU (x86_64, cloud VM) |
| Memory | 7 GB |
| Processes | API (uvicorn, 2 workers), training worker, PostgreSQL 16, Redis 7, Qdrant, load generator — all on the same host |
| GraphRec | 1.1.0, `GRAPHREC_ENV=development` |

## Repeat the measurement

With the stack running and the worker up (`docker compose up -d`):

```bash
PLATFORM_ADMIN_TOKEN=... python -m scripts.load_test \
    --base-url http://localhost:8010 --concurrency 8 --duration 60 --train \
    --out docs/load/my-host-c8.json
```

The script creates its own tenant (registration, a raised quota through the
development bootstrap token, a catalog, a history and a storefront API key), so it
does not touch real tenants. Run it against a staging deployment, not production:
the bootstrap token only raises limits in development. The exit code is non-zero
when any request failed.
