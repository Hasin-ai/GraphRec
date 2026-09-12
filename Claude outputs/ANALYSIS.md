# GraphRec: project analysis and SDK design notes

*Prepared with the Python SDK 0.1.0, 2026-09-11. Reflects the repository including the changes made in the working tree while this work was in progress.*

## 1. What GraphRec is

GraphRec is a multi-tenant recommendation platform for independent e-commerce businesses (see `GraphRec_Complete_SRS.md`). Each tenant syncs its catalog, streams customer interactions, trains a tenant-specific DGSR (dynamic-graph sequential recommendation) model, manages model versions, and requests Top-N recommendations from its storefront, while usage and quotas are tracked per plan.

| Layer | Implementation |
|---|---|
| API | FastAPI app `apps/api/main.py`: 12 routers, **50 routes** (49 under `/v1` plus `/healthz`) |
| Domain services | `graphrec_core/*`: registration, auth, api_keys, subscription, usage, catalog, events, datasets, models_reg, vector_store |
| Data | PostgreSQL 17 through SQLAlchemy 2 and Alembic (9 migrations); forced row-level security on every tenant-owned table (migration 0009 extends it to the domain tables); runtime role `graphrec_app` without BYPASSRLS |
| Vectors | Qdrant (gRPC), one collection per `tenant × model version`, HNSW, cosine distance |
| Frontend | React 19 + Vite admin console (`frontend/`), talking to `/v1` through nginx |
| Ops | Docker Compose: postgres, migrate, qdrant, api, frontend, plus test/demo profiles |

## 2. API contract (what the SDK encodes)

**Envelope and headers.** Every error is `{"error": {code, message, correlation_id, retryable, retry_after_seconds?, details?}}`. `X-Correlation-ID` is echoed back (or generated). On `/v1`, `ContractMiddleware` requires `Accept` to allow JSON and requires JSON (or multipart for dataset uploads) on POST/PUT/PATCH requests that carry a body. Bodies over `MAX_REQUEST_BODY_BYTES` (16 KiB) are rejected with 413; dataset uploads are capped by `MAX_UPLOAD_BODY_BYTES` instead.

**Authentication.**

- *Tenant users:* `Authorization: Bearer <HS256 JWT>`. The access token lasts 15 minutes; `iss=graphrec`, `aud=graphrec-api`, and role and scopes are claims re-checked against the database. A refresh token is issued at login, but **no refresh endpoint exists**.
- *Integrations:* `Authorization: ApiKey gr_live_<43 chars>`. Stored as an HMAC-SHA256 verifier with a pepper; optional expiry; rotation with a grace period of up to 24 h.
- *Platform operators:* `Authorization: Bearer <PLATFORM_ADMIN_TOKEN>`, a shared secret of at least 32 characters. The routes are disabled when the setting is empty.

**Roles.** `tenant_administrator` holds keys, billing, usage, training, models, deployments and metrics. `tenant_developer` holds keys, catalog and events. Administrators can delegate all 14 API-key scopes; developers can delegate only catalog and events.

**Idempotency.** `POST /v1/tenants` uses `Idempotency-Key` (a replay returns 200, a conflicting body returns 409). Events deduplicate by `(tenant, event_id)`. Product upserts are idempotent by nature.

**Rate limits** (in-process, per worker). Registration 5/min per source; login 8/min per source and per account; subscription and usage 30/min; API-key administration 10/min per principal. Exceeding one returns `429 rate_limit_exceeded` with `Retry-After`.

### Endpoint map

| Domain | Routes | Credential | Scope enforced by server? |
|---|---|---|---|
| Health | `GET /healthz` | none | – |
| Tenants / auth | `POST /v1/tenants`, `POST /v1/auth/login`, `POST /v1/auth/setup-password` | none | – |
| API keys | `GET/POST /v1/api-keys`, `GET/DELETE /v1/api-keys/{id}`, `POST …/{id}/rotate` | user bearer only | ✔ `keys:write` |
| Billing | `GET /v1/subscription`, `GET /v1/usage` | any | ✔ `billing:read`, `usage:read` |
| Catalog | `POST /v1/products:bulk-upsert`, `GET /v1/products[/{id}]`, `PUT/PATCH /v1/products/{id}`, `POST …/{id}:disable` | any | ✘ |
| Events | `POST /v1/events`, `POST/GET /v1/events/batches`, `GET …/batches/{id}` | any | ✘ |
| Datasets | `POST /v1/datasets/upload` (multipart), `POST/GET /v1/datasets/snapshots`, `GET …/{id}` | any | ✘ |
| Models | `POST/GET /v1/model-versions`, `GET …/{id}`, `POST …/{id}:activate`, `POST …/{id}:archive`, `POST /v1/models/{id}:rollback`, `POST/GET /v1/training-jobs` | any | ✘ |
| Serving | `GET /v1/deployment`, `…/replicas`, `…/autoscaling`, `GET /v1/metrics/summary` | any | ✘ |
| Recommendations | `POST /v1/recommendations`, `POST /v1/recommendations/session`, `POST /v1/feedback/{impressions,clicks,conversions}` | any | ✘ |
| Platform | `GET /v1/platform/{tenants,plans,failures,audit,status}`, `GET /v1/platform/tenants/{id}`, `POST …/{id}/status`, `POST …/{id}/quotas` | `PLATFORM_ADMIN_TOKEN` bearer | ✔ shared secret |

### Implementation maturity

The registration, login, subscription, usage, API-key and platform paths are production-shaped: they have audit logs, security events, row-level security and tests. The domain pipeline is a working scaffold, as the repository README now says:

- **Training** runs synchronously inside the request, indexes random embeddings into Qdrant and records **no** offline metrics (`metrics: {}`).
- **Recommendations** query Qdrant with a fixed placeholder vector, so every user gets the same ranking even though `strategy` reads `personalized`. Exclusions are honoured and an empty catalog returns an empty list.
- **Feedback** endpoints return `accepted=True` but store nothing. `recommendation_requests` usage is never metered.
- **Deployment, autoscaling and metrics** return constants.

The SDK models all of these responses faithfully, so client code keeps working as the server implementations mature.

## 3. Fixes

### 3.1 Already made in the working tree during this work

While the SDK was being built, the repository received changes that fix several issues this analysis had identified. The SDK was re-checked against them and adapted: platform bearer auth, the `{"overrides": …}` quota body, `TenantStatus`, and the 200-item exclusion limit.

| Issue | Change found in the tree |
|---|---|
| API couldn't start on a clean checkout: `graphrec_core.datasets.service` was imported but never committed, because `.gitignore`'s `datasets/` matched the package | `graphrec_core/datasets/service.py` added; data-directory ignore rules anchored to the repo root (`/datasets/` …) |
| `/v1/platform/*` was unauthenticated and returned invented tenants | `platform_administrator` dependency (`PLATFORM_ADMIN_TOKEN`); SQL functions and audit trail in migration 0009; real 404s |
| Domain tables had no row-level security | Migration 0009 enables and forces RLS on products, events, batches, versions, jobs and snapshots |
| `exclude_product_ids` was read by the route but missing from the schema; the fallback returned a fake `demo-item-1` | Field added (≤200), applied in both tiers, fake item removed |
| Fabricated training metrics; naive `utcnow()` defaults; `TrainingJob.dataset_snapshot_id` not mapped | Removed, made timezone-aware, and mapped |
| Multipart uploads always rejected by the middleware | `/v1/datasets/upload` accepts `multipart/form-data` |

### 3.2 Fixed by this change

| # | Problem (still present in the tree) | Impact | Fix |
|---|---|---|---|
| 1 | The middleware requires `Content-Type: application/json` on **every** POST, even without a body | The console's **Activate, Archive, Rollback and Disable** buttons send body-less POSTs and get `400 malformed_request` | JSON is required only when a body is present (`Content-Length > 0` or chunked) |
| 2 | Uploads share the 16 KiB JSON body limit | Any dataset file over 16 KiB returns `413 payload_too_large` | New `MAX_UPLOAD_BODY_BYTES` setting (default 10 MiB) for the upload path, also enforced in the route for chunked bodies; compose/`.env.example` entries; nginx `client_max_body_size 10m` |
| 3 | `infrastructure/postgres/10-create-runtime-role.sh` has CRLF line endings on Windows checkouts | The Postgres init hook fails (`set: Illegal option -`), `graphrec_app` is never created, and the API can't connect | Script rewritten with LF; `.gitattributes` pins `*.sh` to LF |
| 4 | `SetupPasswordRequest` used in `auth/service.py` without an import | Fails static analysis (`F821`) | Import added |

**Verification.** The repository's real `ContractMiddleware` was exercised over HTTP (uvicorn) with the SDK:

| Scenario | Tree as found | With this change |
|---|---|---|
| SDK body-less action POST (`:activate`) | pass | pass |
| SDK bulk upsert of 400 products (8 requests, largest 16,264 bytes) | pass | pass |
| SDK multipart dataset upload (62 KiB CSV) | **413 payload_too_large** | pass |
| Body over 16 KiB → `PayloadTooLargeError` | pass | pass |
| Console-style POST without Content-Type | **400 malformed_request** | 200 |
| Body with the wrong Content-Type still rejected | pass | pass |

This sandbox couldn't install FastAPI, SQLAlchemy or psycopg (PyPI was blocked), so the database-bound paths were not run here. **Run `docker compose up`, the backend `pytest`, and `python sdks/python/examples/end_to_end_smoke.py` to confirm against a live stack.**

## 4. Open issues (not changed)

| Severity | Issue | Where | Suggested fix |
|---|---|---|---|
| **Critical** | `POST /v1/auth/setup-password` needs no token and no invitation check. Anyone who knows an administrator's email can set a new password and receive tokens (account takeover). It isn't rate-limited either. | `graphrec_core/auth/service.py` `setup_password` | Accept only users with `status='invited'` and no credential, require a signed one-time setup token, and add the login limiter. |
| High | Domain routes don't check scopes. An API key with only `billing:read` can write the catalog, start training or activate models. | products, events, datasets, models, deployment, recommendations routes | Call `principal.require_scope(...)` per the endpoint map. `tenant_administrator` also needs `catalog:*`, `events:*` and `recommendations:read`, or the console's Products and Events pages will return 403 once scopes are enforced. |
| Medium | `setup_password` prints the exception and returns `f"...: {exc}"` in its 503 message (information leak). | `auth/service.py` | Log server-side and return the generic message. |
| Medium | Plan quotas are never enforced for events, products, training or recommendations (SRS ER-F-09). Recommendation requests aren't metered. Feedback isn't stored, and isn't validated against the recommendation request (BRULE-11). | catalog, events, recommendations | Add a quota check and metering to those services. |
| Low | `PATCH /v1/products/{id}` needs a complete product and can't clear `description` or `metadata`. `Idempotency-Key` on bulk upsert is ignored. There's no `GET /v1/training-jobs/{id}`, no pagination, and no token refresh endpoint. | catalog / models / auth | The SDK works around each of these (see its README). |
| Low | Concurrent duplicate `event_id`s race on the unique constraint (500 instead of `duplicate`). | `events/service.py` | Use `INSERT … ON CONFLICT DO NOTHING`. |
| Low | The JSON body limit relies on `Content-Length`, so chunked JSON bodies bypass it. Rate limiters are per process. | `middleware.py`, `registration/rate_limit.py` | Cap the body stream and move limits to Redis. |

## 5. SDK design

- **Package** `graphrec-sdk` (import `graphrec_sdk`), Python ≥ 3.9, depends only on `httpx` and `pydantic` 2. Lives in `sdks/python`.
- **One route table** (`_routes.py`) holds method, path, auth mode, scope, enforcement, idempotency and body kind for all 50 routes. Every resource method goes through it.
- **Transport** (`_base_client.py`) is shared by sync and async clients. It handles headers, credentials, compact JSON, retries (`_retry.py`), error mapping (`errors.py`) and response validation.
- **Models** mirror the server schemas. Responses allow extra fields; inputs forbid them, so typos are caught before sending.
- **Retry safety.** Rate limits and declared-retryable 503s are retried on every route. Pre-send connection errors are always retried. Ambiguous failures are retried only on idempotent routes. `quota_exceeded` is never retried.
- **Bulk operations** are split by exact byte size (the same encoder measures and sends) and duplicates are handled like the server does. Aggregated results, plus `partial_result` on failure.
- **E-commerce layer.** `EventTracker` (buffering, background flush, replay-safe purchase IDs), `CatalogSync` (disable-missing with an empty-feed guard) and `RecommendationSession` (impression, click and conversion linking), each in sync and async form.

### Quality gates

| Check | Result |
|---|---|
| Unit, async, e-commerce and contract tests (`pytest`) | **251 passed**, both against the tree as found and with this change |
| Contract test against the pre-session tree | 11 failures (platform auth, quota body, exclusions), which shows it tracks server changes |
| `mypy --strict` on `graphrec_sdk` (44 modules) and 8 examples | clean (the FastAPI example lacks stubs in the sandbox only) |
| `ruff check` / `ruff format` | clean |
| Wheel build and clean install (`py.typed` included) | OK |
| Real middleware over HTTP (§3.2) | all 6 scenarios pass with this change |
