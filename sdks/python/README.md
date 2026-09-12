# GraphRec Python SDK

Typed Python client for the GraphRec multi-tenant recommendation platform. It covers the whole API: catalog sync, customer events, recommendations and feedback for storefront backends; tenant administration (auth, API keys, datasets, training, model versions, deployment, usage); and platform operations.

- Sync (`GraphRec`) and async (`AsyncGraphRec`) clients that share one API.
- Pydantic v2 models for every request and response. Unknown response fields are kept, so a newer server won't break an older SDK.
- Automatic retries that never duplicate side effects. `Retry-After` is honoured.
- One exception type per server error code, each carrying the server's `correlation_id`.
- Password login that renews the 15-minute access token for you (the API has no refresh endpoint).
- Bulk calls split their payload automatically to fit GraphRec's 16 KiB request-body limit.
- E-commerce helpers: a buffered `EventTracker`, `CatalogSync` (can disable products that dropped out of the feed), and `RecommendationSession` for impression, click and conversion bookkeeping.

Requires Python 3.9 or newer, `httpx` and `pydantic` 2.

---

## Installation

From the GraphRec repository:

```bash
pip install ./sdks/python              # or: pip install -e "./sdks/python[dev]"
```

## Quickstart: storefront backend

Create an API key under **Integration → API keys** (or see [Tenant onboarding](#tenant-onboarding)). Then:

```python
from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import EventTracker, RecommendationSession

client = GraphRec(base_url="http://localhost:8010", api_key="gr_live_...")

# 1. Catalog
client.products.bulk_upsert([
    {"external_id": "sku-100", "title": "Linen shirt", "price": "49.90", "category": "shirts",
     "metadata": {"brand": "Acme"}},
    {"external_id": "sku-101", "title": "Chino trousers", "price": "59.00", "category": "trousers"},
])

# 2. Behaviour (buffered, batched, idempotent)
with EventTracker(client, batch_size=100, flush_interval=5) as tracker:
    tracker.view("customer-42", "sku-100", session_id="sess-1")
    tracker.add_to_cart("customer-42", "sku-100", quantity=1, price="49.90")
    tracker.purchase("customer-42", "sku-100", order_id="ORD-1001")   # replay-safe

# 3. Recommendations + feedback
widget = RecommendationSession(client)                  # records impressions automatically
recs = widget.recommend(user_id="customer-42", top_n=6, exclude_product_ids=["sku-100"])
print(recs.strategy, recs.fallback_used, recs.product_ids)
widget.click(recs, recs.product_ids[0])                 # position + impression linked for you
widget.convert(recs, recs.product_ids[0], value="59.00")
```

More in [`examples/`](examples):

| Example | Shows |
|---|---|
| `storefront_quickstart.py` | Catalog, tracking, recommendations and feedback |
| `tenant_onboarding.py` | Register a tenant, activate the admin with the setup token, mint a storefront key |
| `catalog_sync_job.py` | Nightly CSV sync with `disable_missing` and an exit code |
| `order_webhook.py` | Purchase events that are safe when the webhook is redelivered |
| `train_and_deploy.py` | Snapshot, train, review, activate and roll back |
| `fastapi_storefront.py` | `AsyncGraphRec` inside a FastAPI app, with a background tracker |
| `platform_admin.py` | Plans, tenants, quota overrides, failures and audit with the platform token |
| `end_to_end_smoke.py` | Every SDK area against a running `docker compose` stack |

---

## Authentication

| Credential | Constructor | Header | Use for |
|---|---|---|---|
| API key | `GraphRec(api_key="gr_live_…")` | `ApiKey gr_live_…` | Storefront and server-to-server integration |
| Email and password | `GraphRec(email=…, password=…)` | `Bearer <jwt>` | Admin scripts. Logs in on first use and again before the token expires or on `token_expired` |
| Access token | `GraphRec(access_token=…)` | `Bearer <jwt>` | Tokens you manage yourself |
| Platform admin token | `GraphRec(access_token=PLATFORM_ADMIN_TOKEN)` | `Bearer <secret>` | `client.platform` only (the server's shared secret from `.env`) |
| None | `GraphRec()` | none | `tenants.register`, `auth.*`, `health()` |

If no credential is passed, the client reads `GRAPHREC_API_KEY` or `GRAPHREC_ACCESS_TOKEN`, and `GRAPHREC_BASE_URL` (default `http://localhost:8010`). Pass `use_env=False` to turn that off.

Credentials are never sent to public routes. API-key management (`client.api_keys`) only accepts a user's bearer token, and `client.platform` only accepts the `PLATFORM_ADMIN_TOKEN` bearer. The SDK raises `ConfigurationError` before sending a request that can't succeed.

`with_credentials()` returns a client for the same server with different credentials. It shares the connection pool:

```python
public = GraphRec(use_env=False)
admin = public.with_credentials(email="owner@shop.example", password="…")
store = public.with_credentials(api_key=admin.api_keys.create(name="web", scopes=STOREFRONT_KEY_SCOPES).secret)
```

### Tenant onboarding

Registration creates the tenant and an *invited* administrator. The `201` response carries a one-time `setup_token` that activates that account:

```python
public = GraphRec(use_env=False)
tenant = public.tenants.register(name="Acme Outfitters", admin_email="owner@acme.example")
public.auth.setup_password(setup_token=tenant.setup_token, password="a-long-password",
                           email="owner@acme.example")   # email is an optional cross-check
admin = public.with_credentials(email="owner@acme.example", password="a-long-password")
```

The token expires (`setup_token_expires_at`, 24 hours by default), works once, and only activates accounts that are still invited. Treat it like a password. It is not returned again: a replayed registration has `setup_token=None`. If it is lost or expired, an operator issues a new one:

```bash
docker compose exec api python -m scripts.issue_account_setup_token owner@acme.example
```

Any rejected token raises `AuthenticationError` with `code == "invalid_setup_token"`.

### Scopes

Users get their scopes from their role: administrators hold every tenant scope, developers hold `keys:write`, `catalog:*`, `events:*` and `training:read`. Access tokens keep the scopes granted at login, so sign in again after a role change. An API key gets the scopes chosen when it's created, limited to what the creating role may delegate. Administrators can delegate any scope; developers only `catalog:*` and `events:*`. The server checks the scope on every tenant route and answers `403 insufficient_scope` (`PermissionDeniedError`) when it is missing.

| Preset | Scopes |
|---|---|
| `STOREFRONT_KEY_SCOPES` | `catalog:read`, `catalog:write`, `events:read`, `events:write`, `recommendations:read` (the last one needs an administrator to delegate it) |
| `CATALOG_SYNC_KEY_SCOPES` | `catalog:read`, `catalog:write` |

Every scope is available as `graphrec_sdk.Scope`. `ROLE_SCOPES` and `DELEGATABLE_SCOPES` mirror the server.

---

## API reference

Every method maps to exactly one route (`products.update` and the `wait`/`find`/`get_active` helpers are the documented exceptions). The **Scope** column lists the scopes the credential needs; the server enforces all of them. `graphrec_sdk.ROUTES[key].required_scopes` has the same information in code.

| Resource | Method | HTTP | Scope |
|---|---|---|---|
| `client` | `health()` | `GET /healthz` | – |
| `tenants` | `register(name=, admin_email=, idempotency_key=None)` | `POST /v1/tenants` | public |
| `auth` | `login(email=, password=)` | `POST /v1/auth/login` | public |
| | `setup_password(setup_token=, password=, email=None)` | `POST /v1/auth/setup-password` | public (one-time token) |
| `api_keys` | `list()` / `get(key_id)` | `GET /v1/api-keys[/{id}]` | `keys:write` ✔ bearer |
| | `create(name=, scopes=, expires_at=None)` | `POST /v1/api-keys` | `keys:write` ✔ bearer |
| | `rotate(key_id, reason=, grace_period_seconds=0)` | `POST /v1/api-keys/{id}/rotate` | `keys:write` ✔ bearer |
| | `revoke(key_id)` | `DELETE /v1/api-keys/{id}` | `keys:write` ✔ bearer |
| `subscription` | `get()` | `GET /v1/subscription` | `billing:read` ✔ |
| `usage` | `get()` (`summary.get("accepted_events")`) | `GET /v1/usage` | `usage:read` ✔ |
| `products` | `bulk_upsert(products, idempotency_key=None)` | `POST /v1/products:bulk-upsert` | `catalog:write` ✔ |
| | `list()` / `get(external_id)` | `GET /v1/products[/{id}]` | `catalog:read` ✔ |
| | `upsert(product)` | `PUT /v1/products/{id}` | `catalog:write` ✔ |
| | `update(external_id, **fields)` (read, merge, write) | `GET` then `PATCH /v1/products/{id}` | `catalog:write` ✔ |
| | `disable(external_id)` | `POST /v1/products/{id}:disable` | `catalog:write` ✔ |
| `events` | `create(event_type, user_id=, product_id=, context=, occurred_at=, event_id=)` | `POST /v1/events` | `events:write` ✔ |
| | `create_batch(events)` | `POST /v1/events/batches` | `events:write` ✔ |
| | `list_batches()` / `get_batch(batch_id)` | `GET /v1/events/batches[/{id}]` | `events:read` ✔ |
| `datasets` | `upload(file, filename=None, content_type=None)` | `POST /v1/datasets/upload` (multipart) | `catalog:write` + `events:write` ✔ |
| | `create_snapshot(cutoff_at=None, description=None)` | `POST /v1/datasets/snapshots` | `training:write` ✔ |
| | `list_snapshots()` / `get_snapshot(id)` | `GET /v1/datasets/snapshots[/{id}]` | `training:read` ✔ |
| `training_jobs` | `create(model_type="simplified_dgsr", dataset_snapshot_id=, configuration=)` | `POST /v1/training-jobs` | `training:write` ✔ |
| | `list()`, `find(job_id)`, `wait(job_id, timeout=, poll_interval=)` | `GET /v1/training-jobs` | `training:read` ✔ |
| `model_versions` | `create(version_tag=, model_type=, metrics=, artifact_uri=)` | `POST /v1/model-versions` | `models:write` ✔ |
| | `list()` (`.active`), `get(id)`, `get_active()` | `GET /v1/model-versions[/{id}]` | `models:read` ✔ |
| | `activate(id)` / `rollback(id)` | `POST /v1/model-versions/{id}:activate`, `POST /v1/models/{id}:rollback` | `models:deploy` ✔ |
| | `archive(id)` | `POST /v1/model-versions/{id}:archive` | `models:write` ✔ |
| `deployment` | `get()`, `replicas()`, `autoscaling()` | `GET /v1/deployment[/replicas\|/autoscaling]` | `deployments:read` ✔ |
| `metrics` | `summary()` | `GET /v1/metrics/summary` | `metrics:read` ✔ |
| `recommendations` | `get(user_id=None, top_n=10, context=None, exclude_product_ids=None)` | `POST /v1/recommendations` | `recommendations:read` ✔ |
| | `for_session(session_id, recent_product_ids=None, …)` | `POST /v1/recommendations/session` | `recommendations:read` ✔ |
| `feedback` | `impression(recs_or_request_id, items=None, …)` | `POST /v1/feedback/impressions` | `events:write` ✔ |
| | `click(recs_or_request_id, product_id, position=None, impression_event_id=None, …)` | `POST /v1/feedback/clicks` | `events:write` ✔ |
| | `conversion(recs_or_request_id, product_id, value=None, …)` | `POST /v1/feedback/conversions` | `events:write` ✔ |
| `platform` | `list_tenants()`, `get_tenant(id)`, `set_tenant_status(id, TenantStatus.…)` | `/v1/platform/tenants…` | `PLATFORM_ADMIN_TOKEN` ✔ |
| | `list_plans()`, `set_quota_override(id, overrides=)` | `/v1/platform/plans`, `…/quotas` | `PLATFORM_ADMIN_TOKEN` ✔ |
| | `list_failures()`, `list_audit_logs()`, `status()` | `/v1/platform/failures\|audit\|status` | `PLATFORM_ADMIN_TOKEN` ✔ |

List methods return a list model: iterate it, index or slice it, call `len()`, or use `.items`. Constants for string fields are in `graphrec_sdk.enums` (`EventType`, `ModelStatus`, `TrainingStatus`, `AvailabilityStatus`, `TenantStatus`, `UsageType`…).

---

## E-commerce helpers

### `EventTracker` / `AsyncEventTracker`

A thread-safe buffer that sends events through `events.create_batch`.

- Flushes automatically every `batch_size` events, every `flush_interval` seconds (background thread or task), and on `close()` / `with` exit.
- If a flush fails, the events go back in the queue (bounded by `max_queue_size`) and the exception is raised. Pass `on_error=` to log and drop them instead.
- Typed helpers: `view`, `click`, `add_to_cart`, `remove_from_cart`, `purchase`, `rating`, `search`, `add_to_wishlist`, plus `track()` for any event type. Custom attributes go in `context={...}`, and `default_context` is merged into every event.
- `purchase(..., order_id=..., line=...)` derives the event ID from the order line, so a redelivered webhook is recorded only once.

### `CatalogSync`

```python
report = CatalogSync(client).run(feed_rows, disable_missing=True)
print(report.summary())    # created=… updated=… rejected=… disabled=… requests=…
```

The sync validates rows locally, drops duplicate IDs the same way the server does, and splits the upload into requests that fit the body limit. With `disable_missing`, active products absent from the feed are disabled. An empty feed with `disable_missing=True` is refused unless you pass `allow_empty=True`, so a broken export can't switch off your whole catalog.

### `RecommendationSession`

`recommend()` calls `recommendations.get` (or `for_session` when you pass `session_id`) and sends the impression. `click()` and `convert()` look up the item's position and link the impression automatically. If the click happens in another process, persist `recs.request_id` and call `client.feedback.click(request_id, product_id, position=…)` directly.

---

## Errors

```
GraphRecError
├── ConfigurationError            client can't make this call (missing or wrong credential type)
├── InputValidationError          arguments rejected locally (also a ValueError); nothing was sent
├── WaitTimeoutError              polling helper gave up (also a TimeoutError)
└── APIError                      .message .correlation_id .request
    ├── APIConnectionError        DNS, refused connection, TLS
    │   └── APITimeoutError
    ├── APIResponseValidationError  2xx body didn't match the model (.body)
    └── APIStatusError            .status_code .code .retryable .retry_after_seconds .details .response
        ├── MalformedRequestError      400 malformed_request
        ├── AuthenticationError        401 authentication_failed / invalid_setup_token
        │   └── TokenExpiredError      401 token_expired
        ├── PermissionDeniedError      403 insufficient_scope
        ├── NotFoundError              404 resource_not_found
        ├── ConflictError              409
        │   ├── DuplicateResourceError     duplicate_resource
        │   ├── IdempotencyConflictError   idempotency_conflict
        │   └── StateConflictError         state_conflict / conflict
        ├── PayloadTooLargeError       413 payload_too_large
        ├── RequestValidationError     422 validation_failed (.field_errors)
        ├── RateLimitError             429 rate_limit_exceeded
        ├── QuotaExceededError         429 quota_exceeded
        └── InternalServerError        5xx
            └── ServiceUnavailableError  503 service_unavailable
```

If a request fails partway through a bulk call (`products.bulk_upsert`, `events.create_batch`), the exception has a `partial_result` attribute with the totals the server already accepted.

### Retries

`max_retries` (default 2) applies with exponential backoff and jitter, or you can pass a custom `RetryPolicy`.

| Failure | Retried for |
|---|---|
| `429 rate_limit_exceeded`, `503` with `retryable: true` | every route (the server rejected the request before doing anything) |
| Connection refused, DNS failure, pool timeout | every route (nothing was sent) |
| Read timeout, dropped connection, 502/504 | idempotent routes only: reads, upserts, and writes deduplicated by `event_id` or `Idempotency-Key` |
| `quota_exceeded`, every other 4xx, 500 | never |

Non-idempotent calls (`api_keys.create`/`rotate`, `training_jobs.create`, `model_versions.create`, `datasets.*` writes) are not retried after ambiguous failures. A request keeps the same `X-Correlation-ID` across all its attempts.

---

## Configuration

```python
import httpx, logging
from graphrec_sdk import GraphRec, RetryPolicy

client = GraphRec(
    base_url="https://graphrec.internal",
    api_key="gr_live_…",
    timeout=httpx.Timeout(5.0, connect=2.0),                  # default: 30 s, connect 5 s
    retry_policy=RetryPolicy(max_retries=4, max_retry_after=30),
    max_body_bytes=16_384,        # match the server's MAX_REQUEST_BODY_BYTES
    max_batch_items=500,
    default_headers={"X-Shop-Region": "eu"},
    http_client=httpx.Client(proxy="http://proxy:3128"),      # optional; the SDK won't close it
)
logging.getLogger("graphrec_sdk").setLevel(logging.DEBUG)     # method, path, status, latency, correlation id
```

## Async

```python
import asyncio
from graphrec_sdk import AsyncGraphRec

async def main() -> None:
    async with AsyncGraphRec(api_key="gr_live_…") as client:
        recs, usage = await asyncio.gather(
            client.recommendations.get(user_id="customer-42"),
            client.products.list(),
        )

asyncio.run(main())
```

## Testing your integration

Pass an `httpx` client with a mock transport. No network is needed:

```python
import httpx
from graphrec_sdk import GraphRec

def handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/recommendations"
    return httpx.Response(200, json={"request_id": "rec-1", "items": [], "strategy": "popular_fallback",
                                     "fallback_used": True, "fallback_tier": "tenant_popular"})

client = GraphRec(api_key="gr_live_test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
assert client.recommendations.get(user_id="u1").fallback_used
```

---

## Server compatibility notes

The SDK is kept in lockstep with the API in this repository by `tests/test_contract.py`. It also relies on two middleware fixes shipped with it: dataset uploads larger than 16 KiB, and body-less action POSTs such as `:activate`. See [`ANALYSIS.md`](ANALYSIS.md). Current platform limitations the SDK works around or documents:

- **No token refresh endpoint.** `PasswordAuth` logs in again instead.
- **`PATCH /v1/products/{id}` needs a full product.** `products.update()` reads the product, merges your changes and writes it back, so it isn't atomic.
- **No single training-job endpoint and no pagination.** `training_jobs.find()` and `wait()` poll the list.
- **Training runs synchronously today** and indexes placeholder embeddings without offline metrics. `wait()` returns right away and keeps working once training becomes asynchronous.

## Development

```bash
cd sdks/python
pip install -e ".[dev]"
pytest                 # unit, async and contract tests (contract tests parse ../../apps/api)
mypy                   # strict
ruff check . && ruff format --check .
python examples/end_to_end_smoke.py --base-url http://localhost:8010   # against docker compose
```

`tests/test_contract.py` checks the SDK route table (`graphrec_sdk.ROUTES`) and its models against the FastAPI routers and Pydantic schemas using `ast`. If an endpoint, body type, auth rule, enforced scope or schema field changes on the server, that test fails.
