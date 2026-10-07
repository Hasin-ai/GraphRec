# GraphRec

GraphRec is a multi-tenant recommendation platform developed as small, working
vertical slices. The hardened paths are public tenant registration, tenant-user
sign-in, the protected subscription/quota overview, current usage
reconciliation, and scoped API-key lifecycle management. A second group of
domain paths (catalog, events, datasets, training, model versions, deployment
status, recommendations, and platform administration) supports real DGSR training
and checkpoint serving. See [SRS acceptance](SRS_ACCEPTANCE.md) for verified
workflows, local capacity limits, and remaining requirements.

## Hardened paths

- Registration: `http://localhost:5180/register` -> `POST /v1/tenants`
- Account setup: `http://localhost:5180/setup#token=...` -> `POST /v1/auth/setup-password`
- Sign-in: `http://localhost:5180/login` -> `POST /v1/auth/login`
- Usage and subscription: `http://localhost:5180/usage` -> `GET /v1/usage`,
  `GET /v1/subscription`
- API keys: `http://localhost:5180/credentials` -> redacted list/detail plus
  create/rotate/revoke endpoints
- Durable effects include tenant setup, hashed tenant-scoped refresh sessions,
  an immutable tenant usage ledger, and versioned HMAC-only API-key verifiers.
- Isolation uses forced PostgreSQL row-level security on every tenant-owned
  table; protected reads derive tenancy from a verified bearer or API key and
  accept no tenant selector.

## Domain scaffold

- Tenant users: `/v1/tenant/users` (administrators invite developers and
  other administrators; the invitee gets a one-time setup token)
- Catalog: `/v1/products` (paginated: `limit`, `offset`, `ids`), `/v1/products:bulk-upsert`
- Events: `/v1/events`, `/v1/events/batches`
- Datasets: `/v1/datasets/upload` (multipart JSON, CSV records, or a raw
  `user_id,item_id,time` interaction log), `/v1/datasets/snapshots`
- Training and models: `/v1/training-jobs`, `/v1/model-versions`
- Serving: `/v1/recommendations`, `/v1/feedback/*`, `/v1/deployment*`, `/v1/metrics/summary`
- Platform administration: `/v1/platform/*`, authenticated with the
  `PLATFORM_ADMIN_TOKEN` shared secret (leave it empty to disable these routes)
- Product: public `/v1/meta` (one version for API, console and SDK), `/v1/plans`
  (live plan limits), `/healthz` (liveness) and `/readyz` (database, Redis and
  Qdrant, measured live)

Configuration lives in `graphrec_core/settings.py` and is documented, setting by
setting, in `.env.example`. With `GRAPHREC_ENV=production` the services refuse
to start on default, placeholder or short secrets. Decisions and their status are
in `docs/DECISIONS.md`; requirement traceability is in `docs/GAP_ANALYSIS.md`.

Training without an artifact queues real tenant-data training in the Compose
worker. Synthetic embeddings require explicit `configuration.mode="placeholder"`
and are refused when `GRAPHREC_ENV=production`.
Feedback is persisted with tenant ownership and replay validation, and admission
limits enforce the main plan quotas. Serving status and metrics are
measured: `/v1/deployment` reports the tenant's active model version and
`/v1/metrics/summary` aggregates the `serving_requests` ledger. The platform
runs one API process per deployment, so it has no replica or autoscaling state
to report and exposes none.

## DGSR serving

`graphrec_core/dgsr/` is the DGSR implementation from `dgsr_notebooks/dgsr-beauty.ipynb`
(config, data, temporal graph sampler, model) plus `serving.py`, which loads a
checkpoint and encodes a shopper into the Eq. 18 query vector. Two paths share
one model: a shopper from the training graph is encoded exactly as the notebook's
`recommend()` does; any other history (a session, a shopper with new events, an
unknown shopper) becomes a *virtual root* whose neighbourhood is expanded through
the saved graph (an unknown shopper starts from the mean user embedding and is
labelled `session`).

A training job with `configuration.pretrained_artifact = "<name>"` imports
`MODEL_ARTIFACT_ROOT/<name>/` (`best.pt`, `config.json`, `id_maps.json`,
`interactions.npz`, optional `final_metrics.json`) instead of training: the
checkpoint's engine, config, data fingerprint and vocabulary are verified, its
item ids must be the tenant's product ids and its user ids the tenant's event
user ids (coverage is recorded in the version metrics), and the real item table
is indexed into Qdrant with dot-product distance. Compose mounts
`MODEL_ARTIFACT_DIR` (default `./model_artifacts`) at `/artifacts`.

Serving reads the shopper's events from PostgreSQL (plus
`context.recent_product_ids`), encodes them, retrieves Top-K from Qdrant with
the shopper's history excluded, filters to active products and returns the
version, strategy (`personalized`, `session` or `popular_fallback`) and
fallback tier. When the Qdrant collection is missing the item table is scored
in-process so one capability stays ready.

### Beauty end-to-end run

`tests/e2e/USER_STORIES.md` writes every SRS role as user stories and
`tests/e2e/beauty_e2e.py` executes them against a live stack with the Amazon
Beauty log and the notebook's checkpoint (71 clauses: registration, invited
developer, storefront credential, 394,908-event upload, artifact import,
activation, rollback, archive, recommendations that match
`recommendations_user_0.csv`, session and fallback behaviour, P95 latency,
feedback, tenant isolation, platform operations):

```bash
mkdir -p model_artifacts/dgsr_beauty_t4_v2   # best.pt, config.json, id_maps.json, interactions.npz, final_metrics.json
docker compose up -d --build
python tests/e2e/beauty_e2e.py --platform-token "$PLATFORM_ADMIN_TOKEN" --write-storefront-env
cd apps/demo-storefront && python scripts/verify_personalization.py   # then run the storefront
```

## Account setup

Registration creates an *invited* administrator and returns a one-time
`setup_token` in the `201` response only. The console shows it once as a setup
link (`/setup#token=…`, kept in the URL fragment so it never reaches a
server log); `POST /v1/auth/setup-password` takes `{setup_token, password,
email?}`, activates the account once, and answers every rejection with
`401 invalid_setup_token`. Tokens expire after
`ACCOUNT_SETUP_TOKEN_TTL_SECONDS` (24 hours by default), are stored only as a
SHA-256 hash, and are revoked when a new one is issued. An idempotent
registration replay never returns the token again; issue a fresh one with:

```bash
docker compose exec api python -m scripts.issue_account_setup_token admin@example.org
```

## Permissions

Every tenant route checks the credential's scope and answers `403
insufficient_scope` when it is missing. `tenant_administrator` holds all
tenant scopes including `users:write`; `tenant_developer` holds `keys:write`,
`catalog:*`, `events:*` and `training:read`. Access tokens carry the scopes
granted at login, so sign in again after a role or scope change. API keys are
limited to the scopes the creating role may delegate (administrators: all 14
API-key scopes; developers: catalog, events and `recommendations:read`, enough
to connect a store).

## Local sign-in demonstration

Create a separate local-only demo credential, then sign in through the
documented endpoint:

```bash
docker compose --env-file .env.example --profile demo run --rm demo-account
```

- Email: the `DEMO_LOGIN_EMAIL` value in `.env` (example default:
  `demo-admin@example.org`)
- Password: the `DEMO_LOGIN_PASSWORD` value in `.env`

The bootstrap is not a public setup endpoint and must not be enabled on a VPS.

The registration contract intentionally asks only for a business name and
administrator email; the password is chosen later on the setup page with the
one-time token.

## Operator console

`web/` is the operator console (React 19, Vite, TypeScript) built from
the Modernist design prototype kept under `web/design/`. It talks to
the API through the nginx `/v1/` proxy in Compose, or the Vite dev proxy
locally. See `web/README.md` for the route map, which prototype
screens are not backed by the API, and how to run it against a bare uvicorn.

- Tenant realm: `/login`, `/register`, `/setup`, then `/home`, `/credentials`,
  `/integration`, `/account`, `/products`, `/products/sync`, `/events/submit`,
  `/submissions/:id`, `/datasets`, `/training`, `/models`, `/usage`,
  `/service-status`. Navigation and route gates are derived from the scopes
  the login returns.
- Platform realm: `/admin/login` with `PLATFORM_ADMIN_TOKEN`, then
  `/admin/status`, `/admin/tenants`, `/admin/plans`, `/admin/audit`.

## Automation, rules, trends and capacity (XR-F-02/03/04/07/08)

| Feature | Endpoint | Read scope | Write scope | Console |
|---|---|---|---|---|
| Scheduled + event-triggered retraining (XR-F-02/03) | `GET/PUT /v1/retraining-policy` | `training:read` | `training:write` | Training → Automatic retraining |
| Diversity / freshness rules (XR-F-04) | `GET/PUT /v1/recommendation-policy` | `models:read` | `models:deploy` | Models → Recommendation Rules |
| Usage trends (XR-F-07) | `GET /v1/usage/trends?granularity=hour\|day\|week&start=&end=&types=` | `usage:read` | – | Usage & Quotas → Usage trends |
| Serving capacity (XR-F-08) | `GET /v1/deployment/scaling` | `deployments:read` | – (controller) | Service Status → Serving capacity |

All four are tenant-scoped exactly like the rest of the API: the tenant comes
from the credential, tables use row-level security, and the background
`scheduler` service discovers work through `SECURITY DEFINER` functions that
return tenant ids only.

* **Retraining.** One policy per tenant: a fixed interval (minimum
  `RETRAINING_MIN_INTERVAL_MINUTES`, default 60) and/or a threshold of events
  accepted since the latest training job started. The `scheduler` service
  evaluates policies every `SCHEDULER_TICK_SECONDS` and requests training
  through the normal training path, so cooldown, quota, data sufficiency and
  one-active-job rules apply (XR-NF-03). Each schedule slot and each event
  condition uses a deterministic request id, so it can start at most one job.
  New versions are `eligible`; activation remains manual.
* **Rules.** Optional category cap and freshness boost
  (`score = (1-w)·relevance + w·0.5^(age/half_life)`, `w ≤ 0.3`). Rules only
  reorder eligible, non-excluded products. Each change bumps a `version`, and
  responses report `applied_rules` and `rules_version` (XR-NF-02).
* **Trends.** Sums from the append-only usage ledger in UTC buckets (weeks
  start Monday). Empty buckets are zero. Hourly ranges are capped at 31 days,
  daily at 366 and weekly at 104 weeks.
* **Capacity.** Each tenant with an active model has 1 to
  `maximum_inference_replicas` logical serving units. Each unit is worth
  `ceil(concurrent_recommendation_requests / maximum_inference_replicas)`
  concurrent slots, and `require_capacity` enforces them. The controller
  scales up at once to `ceil(rpm / CAPACITY_TARGET_RPM_PER_REPLICA)` and
  scales down only after `CAPACITY_SCALE_DOWN_STABILIZATION_SECONDS`. Every
  change is a `capacity_event`. **Limitation:** there is no orchestrator here,
  so serving stays in-process. An orchestrator adapter would consume
  `desired_capacity`.

Configuration (environment variables, also listed in `.env.example`):

| Variable | Default | Range | Purpose |
|---|---|---|---|
| `TRAINING_COOLDOWN_SECONDS` | 60 | 0–86400 | Minimum gap between training requests per tenant (409 `training_cooldown`) |
| `RETRAINING_MIN_INTERVAL_MINUTES` | 60 | 1–43200 | Lower bound for a scheduled retraining interval |
| `SCHEDULER_TICK_SECONDS` | 15 | 1–3600 | How often the scheduler evaluates retraining policies and capacity |
| `CAPACITY_TARGET_RPM_PER_REPLICA` | 120 | ≥1 | Requests per minute one serving replica is sized for |
| `CAPACITY_SCALE_DOWN_STABILIZATION_SECONDS` | 120 | 0–86400 | Quiet period before capacity scales down |

Lower values (for example 2 / 10 / 30 / 60) are useful for local testing only;
do not commit them.

## Recommendation admission control (D16)

GraphRec now requires **Redis** (`redis:7.4.2-alpine`, the compose service is `redis`). It holds the
shared recommendation limits, so every API process and replica enforces one limit per tenant.
Each check is a single atomic Lua call, with no application lock, so concurrent requests are not serialized:

| Limit | Redis structure | Behaviour |
|---|---|---|
| `requests_per_minute` | sorted set `gr:rl:{tenant}:recs` (exact sliding window) | 429 "The recommendation request rate limit has been reached." with `Retry-After` |
| `recommendation_requests` (monthly) | counter `gr:q:{tenant}:recommendation_requests:{YYYYMM}`, seeded from the usage ledger | 429 when exhausted; refunded if the request is not served |
| `concurrent_recommendation_requests` | leased semaphore `gr:slots:{tenant}`; slot count = XR-F-08 `serving_slots` | waits up to `SLOT_WAIT_MS`, then 429 "Concurrent recommendation capacity is in use."; leases expire after `SLOT_LEASE_SECONDS` |

Every recommendation response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Shared admission store |
| `REDIS_TIMEOUT_MS` | 30 | Connect and read timeout for each Redis call |
| `SLOT_WAIT_MS` | 100 | How long a request waits for a free concurrency slot |
| `SLOT_LEASE_SECONDS` | 30 | Lease length; a crashed request's slot is reclaimed after this |

**Fail-open.** If Redis errors or times out, recommendations are still served:

- The first failure opens a circuit breaker. Requests then use a per-process limiter with the same plan
  limits, so ER-F-09 still holds within each process, and never wait on Redis.
- A background probe checks Redis every second and switches back on the first successful `PING`.
- The outage is logged (`admission control: Redis unavailable …`), and `fail_open_total` counts the
  requests admitted without the shared store.
- `/v1/deployment`, `/v1/platform/status` and the console's Service Status (Admission control panel)
  report the store as `degraded` until it recovers.

Limitations:

- While Redis is down, each API replica enforces the limits on its own.
- The first request after Redis disappears can wait for one connection or name-resolution timeout. This
  was about 5.5 s for a stopped container in Docker.

**Plan limits** are data (`pricing_plans.limits`), editable per plan with `PUT /v1/platform/plans/{id}`, and
tenant overrides (`POST /v1/platform/tenants/{id}/quotas`) still apply on top. Defaults after migration 0031:

| Plan | Concurrent slots | Requests per minute | Max replicas |
|---|---|---|---|
| free | 8 | 120 | 1 |
| basic | 12 | 300 | 2 |
| pro | 30 | 1,000 | 3 |

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:5180/register` to create a tenant; the response shows
the one-time setup link, which activates the administrator at `/setup` and
signs you in. Returning users sign in at `http://localhost:5180/login`.
**Usage & Quotas** shows the reconciled current-period usage against plan
limits; **API Credentials** creates, inspects, rotates and revokes a scoped
server credential. One-time secrets must be saved before closing their
confirmation view. The API health check is available at
`http://localhost:8010/healthz` for local operations only. Both host ports are
configurable in `.env`.

For frontend development without rebuilding the image:

```bash
cd web
npm install
npm run dev        # http://localhost:5173, proxies /v1 to http://localhost:8010
```

## Verify

```bash
docker compose --profile test run --rm api-test       # backend unit + integration
docker compose --profile test run --rm frontend-test  # console unit tests, build, npm audit
cd web && E2E_BASE_URL=http://localhost:5180 npx playwright test   # browser suite
```

Or, for the console alone: `cd web && npm test -- --run && npm run build`.

`GraphRec_Complete_SRS.md` is the in-repo specification. Integration tests
require the Compose PostgreSQL database; the unit tests run without it.

## SDKs

The Python SDK (`sdks/python`, `graphrec-sdk` 1.x) covers every API route,
grouped by audience (`client.storefront`, `client.tenant`, `client.platform`),
with retries, body-size splitting and e-commerce helpers. See
[`sdks/python/README.md`](sdks/python/README.md). It has an end-to-end smoke test
for the Compose stack and a live integration suite (`tests/integration/test_sdk_live.py`).
