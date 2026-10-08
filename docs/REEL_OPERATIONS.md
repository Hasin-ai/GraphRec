# Operating Reel Storefront

This runbook covers operational monitoring, telemetry, log structure, multi-worker scaling, and incident response for the Reel storefront (`apps/reel-storefront`).

---

## 1. Operational Endpoints

### 1.1 Liveness (`GET /healthz`)
- **Purpose:** Fast container orchestrator probe.
- **Behavior:** Returns `200 {"status": "ok"}` immediately without querying dependencies.

### 1.2 Readiness (`GET /readyz`)
- **Purpose:** Deep dependency probe ensuring traffic is only routed when the system is capable of serving recommendations.
- **Checks evaluated:**
  1. `graphrec`: Verifies GraphRec API `/health` responds healthy.
  2. `redis`: Verifies shared state connection is reachable.
  3. `catalogue`: Verifies 7,951 MovieLens films are loaded into memory.
  4. `model`: Verifies an active DGSR model version is configured.
- **Response:**
  - Status `200` when all checks pass (`{"status": "ready", "checks": {...}}`).
  - Status `503` if any core check fails (`{"status": "not_ready", "checks": {...}}`).

### 1.3 Telemetry & Prometheus Metrics (`GET /metrics`)
- **Purpose:** Prometheus text exposition format (version 0.0.4).
- **Security:** If `REEL_METRICS_TOKEN` is configured, requests must supply `Authorization: Bearer <token>`. In production (`REEL_ENV=production`), unauthenticated requests receive `401 Unauthorized` or `403 Forbidden`.
- **Exported Metric Families:**
  - `reel_http_requests_total{method="...", route="...", status="2xx|4xx|5xx"}`: Total HTTP requests.
  - `reel_http_request_duration_seconds{route="..."}`: Request latency histogram.
  - `reel_graphrec_calls_total{endpoint="...", outcome="success|error"}`: Outbound calls to GraphRec.
  - `reel_graphrec_duration_seconds{endpoint="..."}`: Latency histogram of GraphRec API calls.
  - `reel_fallbacks_total{strategy="..."}`: Executed recommendation fallbacks (`popular`, `mean_user_vector`).
  - `reel_feedback_errors_total{kind="impression|click|conversion"}`: Failed telemetry feedback deliveries.
  - `reel_rate_limit_hits_total`: Total 429 Too Many Requests responses emitted.
  - `reel_metrics_shared`: Gauge indicating `1` if counters are aggregated in Redis, `0` if isolated in memory.

---

## 2. Structured JSON Logging

Reel logs in structured JSON format by default (`REEL_LOG_FORMAT=json`), suitable for ingestion into Datadog, Vector, Loki, or CloudWatch:

```json
{
  "ts": "2026-10-08T17:51:57.457+00:00",
  "level": "info",
  "logger": "reel",
  "message": "GET /api/reel/films 200 (6.40ms)",
  "correlation_id": "reel-a4f91b72e90c1284",
  "method": "GET",
  "route": "/api/reel/films",
  "status": 200,
  "duration_ms": 6.4
}
```

### Correlation ID (`X-Correlation-ID`)
- Every incoming request extracts or generates an `X-Correlation-ID`.
- Stored in Python `contextvars`, making the correlation ID automatically present across all log records emitted during the request lifecycle.
- Propagated to GraphRec outbound requests in the `X-Correlation-ID` header so backend audit traces correlate with storefront requests.

---

## 3. Shared State & Redis Architecture

When scaling across multiple Uvicorn worker processes or container replicas, Reel connects to Redis (`REDIS_URL`):

| Key Pattern | Data Structure | TTL | Purpose |
|---|---|---|---|
| `reel:last_list:{shopper}:{shelf}` | String (JSON array) | 24 hours | Shelf state before/after diffing. |
| `reel:impression:{request_id}` | String | 7 days | Impression event ID linked to recommendation request ID. |
| `reel:session_events:{session_id}` | List (JSON items) | 30 days | Ephemeral shopper interactions for anonymous personalizations. |
| `reel:feedback_metrics:{kind}` | Hash (`success`, `failure`) | Persistent | Live feedback delivery health counters. |
| `reel:ratelimit:{ip}` | Sorted Set (scores=timestamp) | 65 seconds | Sliding window rate limiting. |
| `reel:metrics:v1` | Hash (counters/sums) | Persistent | Shared Prometheus counters across all Uvicorn worker processes. |

---

## 4. Runbook & Incident Handling

### 4.1 Degraded GraphRec Backend
- **Symptom:** `/readyz` returns 503 with `"graphrec": "unreachable"`. Shelves fall back to popular films or return `Unavailable`.
- **Resolution:**
  1. Inspect GraphRec container health: `docker compose ps api`.
  2. Inspect GraphRec logs with correlation ID: `docker compose logs -f api`.
  3. Verify API key validity and quota limits in GraphRec console (`/console/credentials`, `/console/usage`).

### 4.2 Telemetry Feedback Errors
- **Symptom:** `reel_feedback_errors_total` increments or Insight drawer Status tab reports feedback failures.
- **Resolution:**
  1. Check rate limits on the storefront key.
  2. Inspect network timeout settings (`GRAPHREC_TIMEOUT_SECONDS`). Reel retries once automatically.
  3. Review GraphRec dead-letter queue or event ingestion logs.

### 4.3 Catalogue Sync Mismatch
- **Symptom:** Recommendation logs warn of `omitted > 0` items dropped from `films.json`.
- **Resolution:**
  1. Re-run `python scripts/bootstrap_reel.py` to synchronize any missing products.
  2. Ensure GraphRec tenant product quota is high enough (`stored_products >= 10000`).

### 4.4 Tenant Teardown & Reset
To completely reset or suspend the tenant:
```bash
python apps/reel-storefront/scripts/bootstrap_reel.py \
    --teardown \
    --platform-token $PLATFORM_ADMIN_TOKEN
```
This suspends the tenant via the platform operator API, clears `state/live_events.jsonl`, and strips stored credentials from `.env`.
