# GraphRec: project analysis and SDK design notes

*Prepared with the Python SDK 0.1.0 and updated for 0.2.0, 2026-09-11. Reflects the repository including the changes made in the working tree while this work was in progress, and the account-setup and scope-enforcement fixes in §3.3.*

## 1. What GraphRec is

GraphRec is a multi-tenant recommendation platform for independent e-commerce businesses (see `GraphRec_Complete_SRS.md`). Each tenant syncs its catalog, streams customer interactions, trains a tenant-specific DGSR (dynamic-graph sequential recommendation) model, manages model versions, and requests Top-N recommendations from its storefront, while usage and quotas are tracked per plan.

| Layer | Implementation |
|---|---|
| API | FastAPI app `apps/api/main.py`: 12 routers, **50 routes** (49 under `/v1` plus `/healthz`) |
| Domain services | `graphrec_core/*`: registration, auth, api_keys, subscription, usage, catalog, events, datasets, models_reg, vector_store |
| Data | PostgreSQL 17 through SQLAlchemy 2 and Alembic (10 migrations); forced row-level security on every tenant-owned table (migration 0009 extends it to the domain tables); runtime role `graphrec_app` without BYPASSRLS |
| Vectors | Qdrant (gRPC), one collection per `tenant × model version`, HNSW, cosine distance |
| Frontend | React 19 + Vite operator console (`frontend_02/`), talking to `/v1` through nginx |
| Ops | Docker Compose: postgres, migrate, qdrant, api, frontend, plus test/demo profiles |

## 2. API contract (what the SDK encodes)

**Envelope and headers.** Every error is `{"error": {code, message, correlation_id, retryable, retry_after_seconds?, details?}}`. `X-Correlation-ID` is echoed back (or generated). On `/v1`, `ContractMiddleware` requires `Accept` to allow JSON and requires JSON (or multipart for dataset uploads) on POST/PUT/PATCH requests that carry a body. Bodies over `MAX_REQUEST_BODY_BYTES` (16 KiB) are rejected with 413; dataset uploads are capped by `MAX_UPLOAD_BODY_BYTES` instead.

**Authentication.**

- *Tenant users:* `Authorization: Bearer <HS256 JWT>`. The access token lasts 15 minutes; `iss=graphrec`, `aud=graphrec-api`, and role and scopes are claims re-checked against the database. A refresh token is issued at login, but **no refresh endpoint exists**.
- *Integrations:* `Authorization: ApiKey gr_live_<43 chars>`. Stored as an HMAC-SHA256 verifier with a pepper; optional expiry; rotation with a grace period of up to 24 h.
- *Platform operators:* `Authorization: Bearer <PLATFORM_ADMIN_TOKEN>`, a shared secret of at least 32 characters. The routes are disabled when the setting is empty.

**Roles.** `tenant_administrator` holds every tenant scope (all 14 API-key scopes plus `keys:write`). `tenant_developer` holds `keys:write`, catalog, events and `training:read`. Administrators can delegate all 14 API-key scopes; developers can delegate only catalog and events. Every tenant route checks its scope and answers `403 insufficient_scope` when it is missing.

**Account setup.** Registration creates an *invited* administrator and returns a one-time `setup_token` in the `201` response only (replays return `null`). `POST /v1/auth/setup-password` takes `{setup_token, password, email?}`, activates the account once, and rejects anything else with `401 invalid_setup_token`. Operators reissue tokens with `python -m scripts.issue_account_setup_token <email>`.

**Idempotency.** `POST /v1/tenants` uses `Idempotency-Key` (a replay returns 200, a conflicting body returns 409). Events deduplicate by `(tenant, event_id)`. Product upserts are idempotent by nature.

**Rate limits** (in-process, per worker). Registration 5/min per source; login 8/min per source and per account; account setup 8/min per source; subscription and usage 30/min; API-key administration 10/min per principal. Exceeding one returns `429 rate_limit_exceeded` with `Retry-After`.

### Endpoint map

| Domain | Routes | Credential | Scope enforced by server? |
|---|---|---|---|
| Health | `GET /healthz` | none | – |
| Tenants / auth | `POST /v1/tenants`, `POST /v1/auth/login`, `POST /v1/auth/setup-password` | none (setup needs the one-time token) | – |
| API keys | `GET/POST /v1/api-keys`, `GET/DELETE /v1/api-keys/{id}`, `POST …/{id}/rotate` | user bearer only | ✔ `keys:write` |
| Billing | `GET /v1/subscription`, `GET /v1/usage` | any | ✔ `billing:read`, `usage:read` |
| Catalog | `POST /v1/products:bulk-upsert`, `GET /v1/products[/{id}]`, `PUT/PATCH /v1/products/{id}`, `POST …/{id}:disable` | any | ✔ `catalog:read`, `catalog:write` |
| Events | `POST /v1/events`, `POST/GET /v1/events/batches`, `GET …/batches/{id}` | any | ✔ `events:read`, `events:write` |
| Datasets | `POST /v1/datasets/upload` (multipart), `POST/GET /v1/datasets/snapshots`, `GET …/{id}` | any | ✔ upload `catalog:write` + `events:write`; snapshots `training:read`/`training:write` |
| Models | `POST/GET /v1/model-versions`, `GET …/{id}`, `POST …/{id}:activate`, `POST …/{id}:archive`, `POST /v1/models/{id}:rollback`, `POST/GET /v1/training-jobs` | any | ✔ `models:read`/`models:write`/`models:deploy`, `training:read`/`training:write` |
| Serving | `GET /v1/deployment`, `…/replicas`, `…/autoscaling`, `GET /v1/metrics/summary` | any | ✔ `deployments:read`, `metrics:read` |
| Recommendations | `POST /v1/recommendations`, `POST /v1/recommendations/session`, `POST /v1/feedback/{impressions,clicks,conversions}` | any | ✔ `recommendations:read`; feedback `events:write` |
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

### 3.3 Security fixes: account setup and scope enforcement

| # | Problem | Fix |
|---|---|---|
| 5 | **Critical.** `POST /v1/auth/setup-password` took only an email and a password, overwrote the first matching account's credential and issued tokens, so anyone who knew an address could take the account over. No rate limit; a 503 leaked exception text. | Migration `0010_account_setup_tokens`: table `account_setup_tokens` (SHA-256 hash only, expiry, `used_at`, `revoked_at`), forced RLS, column-level `UPDATE (used_at, revoked_at)` grant, and a `SECURITY DEFINER` resolver executable only by `graphrec_app`. Registration issues a 24-hour token (`ACCOUNT_SETUP_TOKEN_TTL_SECONDS`) returned only in the `201` body. Setup requires the token; consumes it with a guarded `UPDATE … WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > now()`; activates only `invited` users without a credential; revokes the user's other tokens; audits; and returns one generic `401 invalid_setup_token` for every rejection. Per-source rate limit. No exception detail in errors. Operator reissue script `scripts/issue_account_setup_token.py`. |
| 6 | **High.** Domain routes accepted any valid credential regardless of scope. | `principal.require_scope(...)` in all 31 catalog, event, dataset, model, training, deployment, metrics, recommendation and feedback handlers (upload requires `catalog:write` and `events:write`). `ROLE_SCOPES` updated so the console keeps working: administrators get every tenant scope, developers gain `training:read`. |

The console now has an `/auth/setup` page (token in the URL fragment, so it isn't sent to servers or logs), the registration page shows the setup link once, and navigation hides pages the signed-in role can't use.

**Verification.**

| Check | Result |
|---|---|
| Migration 0010 SQL on PostgreSQL 16 as `graphrec_app` (forced RLS) | Resolver works without tenant context; cross-tenant read/consume/forge blocked; `expires_at`/`token_hash` updates and deletes denied; other roles can't call the resolver; unique hash, composite FK and expiry check enforced; downgrade and re-upgrade clean |
| Two concurrent setups with one token | exactly one consumes it (`1` / `0` rows) |
| `setup_password` control flow with the ORM faked | valid token → consume, activate, revoke, audit, session, one commit; 11 rejection paths → `401 invalid_setup_token` with the right security-event reason and no writes; DB error → generic 503 with rollback |
| Registration with the ORM faked | token in the `201` response, only its hash stored, replay body without it; old replay bodies still validate |
| New backend integration tests | `tests/integration/test_account_setup.py` (8 tests) and `test_scope_enforcement.py` (5 tests) — run them in Compose, see below |

Run in Compose: `docker compose up --build -d`, then `docker compose exec api pytest -m integration`.

## 4. Open issues (not changed)

| Severity | Issue | Where | Suggested fix |
|---|---|---|---|
| Medium | There is still no in-product invitation for additional users or password reset; lost setup tokens need the operator script. | auth | Add an invite/reset flow that emails a setup token. |
| Medium | Plan quotas are never enforced for events, products, training or recommendations (SRS ER-F-09). Recommendation requests aren't metered. Feedback isn't stored, and isn't validated against the recommendation request (BRULE-11). | catalog, events, recommendations | Add a quota check and metering to those services. |
| Low | `PATCH /v1/products/{id}` needs a complete product and can't clear `description` or `metadata`. `Idempotency-Key` on bulk upsert is ignored. There's no `GET /v1/training-jobs/{id}`, no pagination, and no token refresh endpoint. | catalog / models / auth | The SDK works around each of these (see its README). |
| Low | Concurrent duplicate `event_id`s race on the unique constraint (500 instead of `duplicate`). | `events/service.py` | Use `INSERT … ON CONFLICT DO NOTHING`. |
| Low | The JSON body limit relies on `Content-Length`, so chunked JSON bodies bypass it. Rate limiters are per process. | `middleware.py`, `registration/rate_limit.py` | Cap the body stream and move limits to Redis. |

## 5. SDK design

- **Package** `graphrec-sdk` (import `graphrec_sdk`), Python ≥ 3.9, depends only on `httpx` and `pydantic` 2. Lives in `sdks/python`.
- **One route table** (`_routes.py`) holds method, path, auth mode, required scopes, enforcement, idempotency and body kind for all 50 routes. Every resource method goes through it.
- **Transport** (`_base_client.py`) is shared by sync and async clients. It handles headers, credentials, compact JSON, retries (`_retry.py`), error mapping (`errors.py`) and response validation.
- **Models** mirror the server schemas. Responses allow extra fields; inputs forbid them, so typos are caught before sending.
- **Retry safety.** Rate limits and declared-retryable 503s are retried on every route. Pre-send connection errors are always retried. Ambiguous failures are retried only on idempotent routes. `quota_exceeded` is never retried.
- **Bulk operations** are split by exact byte size (the same encoder measures and sends) and duplicates are handled like the server does. Aggregated results, plus `partial_result` on failure.
- **E-commerce layer.** `EventTracker` (buffering, background flush, replay-safe purchase IDs), `CatalogSync` (disable-missing with an empty-feed guard) and `RecommendationSession` (impression, click and conversion linking), each in sync and async form.

### Quality gates

| Check | Result |
|---|---|
| Unit, async, e-commerce and contract tests (`pytest`) | **255 passed** against the fixed backend (0.1.0: 251) |
| Contract test drift detection | 11 failures against the pre-session tree (platform auth, quota body, exclusions); 33 against the tree before §3.3 (scopes, setup body, registration fields) |
| `mypy --strict` on `graphrec_sdk` (44 modules) and 8 examples | clean (the FastAPI example lacks stubs in the sandbox only) |
| `ruff check` / `ruff format` | clean |
| Wheel build and clean install (`py.typed` included) | OK |
| Real middleware over HTTP (§3.2) | all 6 scenarios pass with this change |
