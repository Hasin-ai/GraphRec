# GraphRec Python SDK

Typed Python client for the GraphRec multi-tenant recommendation platform. It covers every API route, grouped by audience: `client.storefront` (events, recommendations, feedback), `client.tenant` (auth, users, API keys, catalog, datasets, training, models, policies, serving status, billing and usage analytics) and `client.platform` (tenant lifecycle, plans, quotas, monitoring).

- Sync (`GraphRec`) and async (`AsyncGraphRec`) clients that share one API.
- Pydantic v2 models for every request and response. Unknown response fields are kept, so a newer server won't break an older SDK.
- Automatic retries that never duplicate side effects. `Retry-After` is honoured.
- One exception type per server error code, each carrying the server's `correlation_id`.
- Password login that renews the 15-minute access token for you, and signs in again when a session is revoked.
- Bulk calls split their payload automatically to fit GraphRec's 16 KiB request-body limit.
- E-commerce helpers: a buffered `EventTracker`, `CatalogSync` (can disable products that dropped out of the feed), and `RecommendationSession` for impression, click and conversion bookkeeping.

Requires Python 3.9 or newer, `httpx` and `pydantic` 2.

---

## Installation

From the GraphRec repository:

```bash
pip install ./sdks/python              # or: pip install -e "./sdks/python[dev]"
```

## Client layout

Resources are grouped by who calls them. Each audience uses its own credential:

| Namespace | Audience | Credential | Resources |
|---|---|---|---|
| `client.storefront` | The shop's site, app or backend | Storefront **API key** | `events`, `recommendations`, `feedback` |
| `client.tenant` | Tenant administrators and developers | **Email + password** (or a bearer token); API keys for the scoped data routes | `auth`, `users`, `api_keys`, `catalog`, `datasets`, `training_jobs`, `model_versions`, `retraining_policy`, `recommendation_policy`, `deployment`, `metrics`, `subscription`, `usage` |
| `client.platform` | The platform operator | `PLATFORM_ADMIN_TOKEN` bearer | `tenants`, `plans`, plus `status()`, `list_failures()`, `list_audit_logs()` |

`client.health()` needs no credential.

## Quickstart: storefront integration

Create a storefront API key (console: **Integration → API keys**, or `client.tenant.api_keys.create(...)` as shown in [Tenant administration](#tenant-administration)). Then:

```python
from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import CatalogSync, EventTracker, RecommendationSession

client = GraphRec(base_url="https://graphrec.example.com", api_key="gr_live_...")

# 1. Catalog (a storefront key holds catalog:write, so a sync job can use it)
CatalogSync(client).run([
    {"external_id": "sku-100", "title": "Linen shirt", "price": "49.90", "category": "shirts",
     "metadata": {"brand": "Acme"}},
    {"external_id": "sku-101", "title": "Chino trousers", "price": "59.00", "category": "trousers"},
])

# 2. Behaviour: buffered, batched and idempotent
with EventTracker(client, batch_size=100, flush_interval=5) as tracker:
    tracker.view("customer-42", "sku-100", session_id="sess-1")
    tracker.add_to_cart("customer-42", "sku-100", quantity=1, price="49.90")
    tracker.purchase("customer-42", "sku-100", order_id="ORD-1001")   # replay-safe

# 3. Recommendations and feedback
widget = RecommendationSession(client)                  # records impressions automatically
recs = widget.recommend(user_id="customer-42", top_n=6, exclude_product_ids=["sku-100"])
print(recs.strategy, recs.fallback_used, recs.applied_rules, recs.product_ids)
widget.click(recs, recs.product_ids[0])                 # position and impression linked for you
widget.convert(recs, recs.product_ids[0], value="59.00")

# Or call the resources directly
client.storefront.events.create("view", user_id="customer-7", product_id="sku-101")
anon = client.storefront.recommendations.for_session("sess-9", recent_product_ids=["sku-101"], top_n=4)
```

## Tenant administration

Sign in as a tenant user. The client logs in on first use, and again when the 15-minute token expires or the session is revoked (logout, password recovery):

```python
from graphrec_sdk import GraphRec, STOREFRONT_KEY_SCOPES

public = GraphRec(base_url="https://graphrec.example.com", use_env=False)

# Onboarding: register, then activate the administrator with the one-time setup token
tenant = public.tenant.auth.register(name="Acme Outfitters", admin_email="owner@acme.example")
public.tenant.auth.setup_password(setup_token=tenant.setup_token, password="a-long-password",
                                  email="owner@acme.example")

admin = public.with_credentials(email="owner@acme.example", password="a-long-password")
t = admin.tenant

key = t.api_keys.create(name="web", scopes=STOREFRONT_KEY_SCOPES)   # key.secret is shown once
invite = t.users.invite("dev@acme.example", role="tenant_developer")
t.users.revoke_invitation(invite.id)

# Data, training and deployment
snapshot = t.datasets.create_snapshot(description="weekly")
job = t.training_jobs.wait(t.training_jobs.create(dataset_snapshot_id=snapshot.id).id)
t.model_versions.activate(job.model_version_id)
print(t.deployment.get().status, t.deployment.scaling(limit=5).ready_capacity)

# Policies (full replacement: pass the current policy to change single fields)
policy = t.recommendation_policy.get()
t.recommendation_policy.update(policy, diversity_enabled=True, max_per_category=2)
t.retraining_policy.update(schedule_enabled=True, interval_minutes=1440, event_trigger_enabled=True)

# Billing and analytics
print(t.subscription.get().plan_code, t.usage.get().get("accepted_events"))
trend = t.usage.trends(granularity="day", types=["accepted_events", "recommendation_requests"])
print(trend.totals, t.metrics.summary(window_minutes=60).p95_latency_ms)

t.auth.logout()   # ends every session of this user
```

The setup token expires (24 hours by default), works once, and only activates accounts that are still invited. Treat it like a password. It is not returned again: a replayed registration has `setup_token=None`. If it is lost, an operator issues a new one (`python -m scripts.issue_account_setup_token <email>`) or a recovery token (`client.platform.tenants.issue_recovery`).

## Platform administration

```python
import os
from graphrec_sdk import GraphRec, LimitBelowUsageError, TenantStatus

ops = GraphRec(base_url="https://graphrec.example.com", access_token=os.environ["PLATFORM_ADMIN_TOKEN"])

print(ops.platform.status().status)                       # healthy | degraded
for tenant in ops.platform.tenants.list():
    print(tenant.slug, tenant.status, ops.platform.tenants.get_usage(tenant.id).dimensions[0].used)

shop = ops.platform.tenants.list()[0]
ops.platform.tenants.set_status(shop.id, TenantStatus.SUSPENDED)
ops.platform.tenants.set_status(shop.id, TenantStatus.ACTIVE)

# Limit changes that would leave a tenant above an inventory limit are refused
try:
    ops.platform.tenants.set_quota_override(shop.id, overrides={"stored_products": 100})
except LimitBelowUsageError as exc:
    print(exc.conflicts)                                   # [{"limit_name": ..., "used": ..., ...}]
    quota = ops.platform.tenants.set_quota_override(
        shop.id, overrides={"stored_products": 100}, acknowledge_below_usage=True)
    print(quota.warnings)

pro = next(p for p in ops.platform.plans.list() if p.code == "pro")
ops.platform.tenants.assign_plan(shop.id, pro.id)
recovery = ops.platform.tenants.issue_recovery(shop.id, email="owner@acme.example")
print(len(ops.platform.list_audit_logs()), len(ops.platform.list_failures()))
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
| API key | `GraphRec(api_key="gr_live_…")` | `ApiKey gr_live_…` | `client.storefront`, and scoped `client.tenant` data routes (catalog, datasets…) |
| Email and password | `GraphRec(email=…, password=…)` | `Bearer <jwt>` | `client.tenant`. Logs in on first use, before the token expires, and once more after a `401` |
| Access token | `GraphRec(access_token=…)` | `Bearer <jwt>` | Tokens you manage yourself (not renewed) |
| Platform admin token | `GraphRec(access_token=PLATFORM_ADMIN_TOKEN)` | `Bearer <secret>` | `client.platform` only |
| None | `GraphRec()` | none | `tenant.auth.register/login/setup_password/recover_password`, `health()` |

If no credential is passed, the client reads `GRAPHREC_API_KEY` or `GRAPHREC_ACCESS_TOKEN`, and `GRAPHREC_BASE_URL` (default `http://localhost:8010`). Pass `use_env=False` to turn that off.

Credentials are never sent to public routes. User-management, API-key management and logout (`tenant.users`, `tenant.api_keys`, `tenant.auth.logout`) only accept a user's bearer token; the SDK raises `ConfigurationError` before sending a request that cannot succeed.

`with_credentials()` returns a client for the same server with different credentials, sharing the connection pool:

```python
public = GraphRec(use_env=False)
admin = public.with_credentials(email="owner@shop.example", password="…")
store = public.with_credentials(api_key=admin.tenant.api_keys.create(name="web", scopes=STOREFRONT_KEY_SCOPES).secret)
```

### Scopes

Users get their scopes from their role: administrators hold every tenant scope (including `users:write`), developers hold `keys:write`, `catalog:*`, `events:*` and `training:read`. Access tokens keep the scopes granted at login, so sign in again after a role change. An API key gets the scopes chosen when it is created, limited to what the creating role may delegate. The server checks the scope on every tenant route and answers `403 insufficient_scope` (`PermissionDeniedError`) when it is missing.

| Preset | Scopes |
|---|---|
| `STOREFRONT_KEY_SCOPES` | `catalog:read`, `catalog:write`, `events:read`, `events:write`, `recommendations:read` |
| `CATALOG_SYNC_KEY_SCOPES` | `catalog:read`, `catalog:write` |

Every scope is available as `graphrec_sdk.Scope`. `ROLE_SCOPES` and `DELEGATABLE_SCOPES` mirror the server.

---

## API reference

Every method maps to one route (`catalog.update`, `catalog.iterate` and the `wait`/`find`/`get_active` helpers are the documented exceptions). The **Scope** column lists what the credential needs; `graphrec_sdk.ROUTES[key].required_scopes` has the same information in code. ✔ = enforced by the server; "bearer" = user token only.

### `client.storefront`

| Resource | Method | HTTP | Scope |
|---|---|---|---|
| `events` | `create(event_type, user_id=, product_id=, context=, occurred_at=, event_id=)` | `POST /v1/events` | `events:write` ✔ |
| | `create_batch(events, request_id=None)` | `POST /v1/events/batches` | `events:write` ✔ |
| | `list_batches()` / `get_batch(batch_id)` | `GET /v1/events/batches[/{id}]` | `events:read` ✔ |
| `recommendations` | `get(user_id=None, top_n=10, context=None, exclude_product_ids=None)` | `POST /v1/recommendations` | `recommendations:read` ✔ |
| | `for_session(session_id, recent_product_ids=None, …)` | `POST /v1/recommendations/session` | `recommendations:read` ✔ |
| `feedback` | `impression(recs_or_request_id, items=None, …)` | `POST /v1/feedback/impressions` | `events:write` ✔ |
| | `click(recs_or_request_id, product_id, position=None, impression_event_id=None, …)` | `POST /v1/feedback/clicks` | `events:write` ✔ |
| | `conversion(recs_or_request_id, product_id, value=None, …)` | `POST /v1/feedback/conversions` | `events:write` ✔ |

### `client.tenant`

| Resource | Method | HTTP | Scope |
|---|---|---|---|
| `auth` | `register(name=, admin_email=, idempotency_key=None)` | `POST /v1/tenants` | public |
| | `login(email=, password=)` | `POST /v1/auth/login` | public |
| | `setup_password(setup_token=, password=, email=None)` | `POST /v1/auth/setup-password` | public (one-time token) |
| | `recover_password(recovery_token=, password=, email=None)` | `POST /v1/auth/recover-password` | public (one-time token) |
| | `logout()` | `POST /v1/auth/logout` | bearer |
| `users` | `list()` | `GET /v1/tenant/users` | `users:write` ✔ bearer |
| | `invite(email, role="tenant_developer", display_name=None)` | `POST /v1/tenant/users` | `users:write` ✔ bearer |
| | `revoke_invitation(user_id)` | `DELETE /v1/tenant/users/{id}/invitation` | `users:write` ✔ bearer |
| `api_keys` | `list()` / `get(key_id)` | `GET /v1/api-keys[/{id}]` | `keys:write` ✔ bearer |
| | `create(name=, scopes=, expires_at=None)` | `POST /v1/api-keys` | `keys:write` ✔ bearer |
| | `rotate(key_id, reason=, grace_period_seconds=0)` | `POST /v1/api-keys/{id}/rotate` | `keys:write` ✔ bearer |
| | `revoke(key_id)` | `DELETE /v1/api-keys/{id}` | `keys:write` ✔ bearer |
| `catalog` | `bulk_upsert(products, idempotency_key=None, request_id=None)` | `POST /v1/products:bulk-upsert` | `catalog:write` ✔ |
| | `list_syncs()` / `get_sync(sync_id)` | `GET /v1/catalog-syncs[/{id}]` | `catalog:read` ✔ |
| | `list(limit=, offset=, external_ids=)` / `iterate()` / `get(external_id)` | `GET /v1/products[/{id}]` | `catalog:read` ✔ |
| | `upsert(product)` | `PUT /v1/products/{id}` | `catalog:write` ✔ |
| | `update(external_id, **fields)` (read, merge, write) | `GET` then `PATCH /v1/products/{id}` | `catalog:read` + `catalog:write` |
| | `disable(external_id)` | `POST /v1/products/{id}:disable` | `catalog:write` ✔ |
| `datasets` | `upload(file, filename=None, content_type=None)` | `POST /v1/datasets/upload` (multipart) | `catalog:write` + `events:write` ✔ |
| | `create_snapshot(cutoff_at=None, description=None)` | `POST /v1/datasets/snapshots` | `training:write` ✔ |
| | `list_snapshots()` / `get_snapshot(id)` | `GET /v1/datasets/snapshots[/{id}]` | `training:read` ✔ |
| `training_jobs` | `create(model_type="simplified_dgsr", dataset_snapshot_id=, configuration=)` | `POST /v1/training-jobs` | `training:write` ✔ |
| | `list()` / `get(job_id)` / `find(job_id)` / `wait(job_id, timeout=, poll_interval=)` | `GET /v1/training-jobs[/{id}]` | `training:read` ✔ |
| | `cancel(job_id)` | `POST /v1/training-jobs/{id}:cancel` | `training:write` ✔ |
| `retraining_policy` | `get()` | `GET /v1/retraining-policy` | `training:read` ✔ |
| | `update(policy=None, schedule_enabled=, interval_minutes=, event_trigger_enabled=, event_threshold=, epochs=)` | `PUT /v1/retraining-policy` | `training:write` ✔ |
| `model_versions` | `create(version_tag=, model_type=, metrics=, artifact_uri=)` | `POST /v1/model-versions` | `models:write` ✔ |
| | `list()` (`.active`), `get(id)`, `get_active()` | `GET /v1/model-versions[/{id}]` | `models:read` ✔ |
| | `activate(id)` / `rollback(id)` | `POST /v1/model-versions/{id}:activate`, `POST /v1/models/{id}:rollback` | `models:deploy` ✔ |
| | `archive(id)` | `POST /v1/model-versions/{id}:archive` | `models:write` ✔ |
| `recommendation_policy` | `get()` | `GET /v1/recommendation-policy` | `models:read` ✔ |
| | `update(policy=None, diversity_enabled=, max_per_category=, freshness_enabled=, freshness_weight=, freshness_half_life_days=)` | `PUT /v1/recommendation-policy` | `models:deploy` ✔ |
| `deployment` | `get()` | `GET /v1/deployment` | `deployments:read` ✔ |
| | `scaling(limit=20)` | `GET /v1/deployment/scaling` | `deployments:read` ✔ |
| `metrics` | `summary(window_minutes=None)` | `GET /v1/metrics/summary` | `metrics:read` ✔ |
| `subscription` | `get()` | `GET /v1/subscription` | `billing:read` ✔ |
| `usage` | `get()` (`summary.get("accepted_events")`) | `GET /v1/usage` | `usage:read` ✔ |
| | `trends(granularity="day", start=None, end=None, types=None)` | `GET /v1/usage/trends` | `usage:read` ✔ |

### `client.platform` (`PLATFORM_ADMIN_TOKEN`)

| Resource | Method | HTTP |
|---|---|---|
| `tenants` | `list()` / `get(tenant_id)` | `GET /v1/platform/tenants[/{id}]` |
| | `set_status(tenant_id, TenantStatus.…)` | `POST /v1/platform/tenants/{id}/status` |
| | `get_quota(tenant_id)` | `GET /v1/platform/tenants/{id}/quotas` |
| | `set_quota_override(tenant_id, overrides=, acknowledge_below_usage=False)` | `POST /v1/platform/tenants/{id}/quotas` |
| | `assign_plan(tenant_id, plan_id, acknowledge_below_usage=False)` | `POST /v1/platform/tenants/{id}/plan` |
| | `get_usage(tenant_id)` | `GET /v1/platform/tenants/{id}/usage` |
| | `issue_recovery(tenant_id, email=)` | `POST /v1/platform/tenants/{id}/recovery` |
| `plans` | `list()` | `GET /v1/platform/plans` |
| | `update(plan_id, name=, limits=, is_active=, acknowledge_below_usage=False)` | `PUT /v1/platform/plans/{id}` |
| (namespace) | `status()` / `list_failures()` / `list_audit_logs()` | `GET /v1/platform/status\|failures\|audit` |

List methods return a list model: iterate it, index or slice it, call `len()`, or use `.items`. Constants for string fields are in `graphrec_sdk.enums` (`EventType`, `ModelStatus`, `TrainingStatus`, `AvailabilityStatus`, `TenantStatus`, `UsageType`…).

---

## E-commerce helpers

### `EventTracker` / `AsyncEventTracker`

A thread-safe buffer that sends events through `storefront.events.create_batch`.

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

`recommend()` calls `storefront.recommendations.get` (or `for_session` when you pass `session_id`) and sends the impression. `click()` and `convert()` look up the item's position and link the impression automatically. If the click happens in another process, persist `recs.request_id` and call `client.storefront.feedback.click(request_id, product_id, position=…)` directly.

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
        ├── AuthenticationError        401 authentication_failed / invalid_setup_token / invalid_recovery_token
        │   └── TokenExpiredError      401 token_expired
        ├── PermissionDeniedError      403 insufficient_scope / insufficient_role
        ├── NotFoundError              404 resource_not_found / artifact_not_found
        ├── ConflictError              409 (other codes, e.g. protected_rollback_target, training_in_progress)
        │   ├── DuplicateResourceError     duplicate_resource
        │   ├── IdempotencyConflictError   idempotency_conflict
        │   ├── StateConflictError         state_conflict / conflict
        │   └── LimitBelowUsageError       limit_below_usage (.conflicts)
        ├── PayloadTooLargeError       413 payload_too_large
        ├── RequestValidationError     422 validation_failed (.field_errors)
        ├── RateLimitError             429 rate_limit_exceeded
        ├── QuotaExceededError         429 quota_exceeded
        └── InternalServerError        5xx
            └── ServiceUnavailableError  503 service_unavailable
```

If a request fails partway through a bulk call (`tenant.catalog.bulk_upsert`, `storefront.events.create_batch`), the exception has a `partial_result` attribute with the totals the server already accepted.

### Retries

`max_retries` (default 2) applies with exponential backoff and jitter, or you can pass a custom `RetryPolicy`.

| Failure | Retried for |
|---|---|
| `429 rate_limit_exceeded`, `503` with `retryable: true` | every route (the server rejected the request before doing anything) |
| Connection refused, DNS failure, pool timeout | every route (nothing was sent) |
| Read timeout, dropped connection, 502/504 | idempotent routes only: reads, upserts, and writes deduplicated by `event_id` or `Idempotency-Key` |
| `quota_exceeded`, every other 4xx, 500 | never |

Non-idempotent calls (`tenant.api_keys.create`/`rotate`, `tenant.training_jobs.create`, `tenant.model_versions.create`, `tenant.datasets.*` writes, `platform.tenants.assign_plan`/`issue_recovery`) are not retried after ambiguous failures. A request keeps the same `X-Correlation-ID` across all its attempts.

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
            client.storefront.recommendations.get(user_id="customer-42"),
            client.tenant.usage.get(),
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
assert client.storefront.recommendations.get(user_id="u1").fallback_used
```

---

## Server compatibility notes

The SDK is kept in lockstep with the API in this repository by `tests/test_contract.py` (static) and `tests/integration/test_sdk_live.py` in the repository root (every route against the real app and PostgreSQL). Behaviour worth knowing:

- **No token refresh endpoint.** `PasswordAuth` signs in again instead.
- **`PATCH /v1/products/{id}` takes a full product.** `catalog.update()` reads the product, merges your changes and writes it back, so it is not atomic.
- **Policy updates are full replacements.** Pass the result of `get()` as the first argument to change single fields.
- **Platform list endpoints return the latest 50 failures / audit records** and are not paginated.
- **Naive datetimes** passed to `usage.trends()` are treated as UTC (the server rejects naive values).

## Development

```bash
cd sdks/python
pip install -e ".[dev]"
pytest                 # unit, async and contract tests (contract tests parse ../../apps/api)
# live tests: from the repository root, with the Compose database (and Qdrant) running
pytest tests/integration/test_sdk_live.py
mypy                   # strict
ruff check . && ruff format --check .
python examples/end_to_end_smoke.py --base-url http://localhost:8010   # against docker compose
```

`tests/test_contract.py` checks the SDK route table (`graphrec_sdk.ROUTES`) and its models against the FastAPI routers and Pydantic schemas using `ast`. If an endpoint, body type, auth rule, enforced scope or schema field changes on the server, that test fails.
