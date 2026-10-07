# GraphRec gap analysis (Phase 1 baseline)

Date: 2026-10-07. Scope: the working tree at `db73cd3` **plus 49 uncommitted changes** (37 modified files, 12 untracked paths: the marketing site, `PlaygroundPage`, `GET /v1/events`, `apps/reel-storefront/`, and others). Every claim below comes from reading the code or running it. Documents were treated as claims to check, not as evidence.

Status key: **Done** = implemented and exercised by a test (no test cites the SRS ID yet unless noted). **Done-but-untested** = implemented, with no test exercising the behaviour. **Partial** = a material part is missing. **Missing** = no usable behaviour.

> Test-naming gap that applies to every row: only 8 test functions cite an SRS ID in their name or docstring. The definition of done requires a citing test for every ID, so even rows marked **Done** still need an ID-cited test or a renamed one.

---

## 1. Architecture map

```
Browser ──► nginx (frontend container :80, host :5180)
             ├─ /            SPA (React 19 / RR7 / Vite): marketing (WIP), tenant console, /admin/*
             ├─ /healthz     static 200 from nginx (A-27: not a real check)
             └─ /v1/*  ──►  api (uvicorn, 1 process, :8000, host :8010 also published)
                              ├─ PostgreSQL 17 (runtime role graphrec_app, NOBYPASSRLS, FORCE RLS)
                              ├─ Redis 7.4 (recommendation admission only: rpm, slots, monthly quota cache)
                              ├─ Qdrant 1.12 (per-tenant, per-version item collections; ports 6333/6334 published)
                              └─ model artifacts: /artifacts (ro import) + trained_models volume
worker     (python -m graphrec_core.dgsr.worker): global advisory lock 714629381, claims via claim_training_job()
scheduler  (python -m graphrec_core.scheduler): retraining policies (XR-F-02/03) + capacity controller (XR-F-08)
migrate    (alembic upgrade head, owner role) one-shot before api/worker/scheduler
demo-storefront (Facet) / reel-storefront (untracked): separate apps that use the Python SDK
```

**Auth realms**

| Realm | Credential | Tenant derivation | Where |
|---|---|---|---|
| Tenant user | HS256 JWT (15 min) + refresh token (7 d, hashed in `refresh_sessions`) | `tid` claim, re-checked against `tenant_users`/`tenants` and `auth_epoch` on every request | `auth/principal.py:80` |
| API key | `ApiKey <secret>`, HMAC-SHA256 with pepper, resolved by SECURITY DEFINER `resolve_api_key_candidate` | key row | `auth/principal.py:162` |
| Platform | One shared `PLATFORM_ADMIN_TOKEN` bearer, constant-time compare | none: SECURITY DEFINER `platform_*` functions | `auth/platform.py` |

**Isolation (verified on a live database):** all 26 tenant tables have `ENABLE` and `FORCE ROW LEVEL SECURITY` with policies. The exceptions are `registration_requests` (no RLS, but readable by `graphrec_app`, see A-17) and `security_events` (no RLS, insert-only grant). `audit_logs` and `usage_events` grant only INSERT and SELECT, so they are append-only at the database level. All 17 SECURITY DEFINER functions pin `search_path=pg_catalog, public`.

---

## 2. Requirement traceability matrix

Abbreviations: `mr` = `models_reg/service.py`, `rec` = `routes/recommendations.py`, `IT` = `tests/integration`, `xr` = `test_xr_features.py`, `srs` = `test_srs_acceptance.py`.

### Normal functional

| ID | Backend | Endpoint | UI | Tests | Status | Gap |
|---|---|---|---|---|---|---|
| NR-F-01 | registration/service | POST /v1/tenants | /register, /setup | IT/test_tenant_registration, test_account_setup | Done | The setup link is shown on screen only; it needs email delivery (A-08) |
| NR-F-02 | auth/service, principal | /v1/auth/login, logout | /login, scope gates | test_tenant_login, test_scope_enforcement | Partial | No refresh flow (A-05). Sessions end at 15 min |
| NR-F-03 | api_keys/service | /v1/api-keys* | /credentials | test_api_keys | Done | Replay timestamp format drifts by DB timezone (A-15) |
| NR-F-04 | catalog/service | /v1/products* | /products* | test_domain_isolation, sdk_live | Done | — |
| NR-F-05 | catalog/service | POST /v1/products:bulk-upsert, /v1/catalog-syncs | /products/sync | srs::catalog_sync… | Done | — |
| NR-F-06 | events/service | /v1/events, /v1/events/batches | /events/submit | srs, sdk_live | Done | `GET /v1/events` (WIP) is missing from the SDK, so the contract test is red (A-04) |
| NR-F-07 | mr.create_training_job | POST /v1/training-jobs | /training | test_training_worker | Done | The placeholder mode is also exposed (A-02) |
| NR-F-08 | worker progress/stage | GET /v1/training-jobs/{id} | /training/:jobId | test_training_worker, e2e training | Done | — |
| NR-F-09 | mr.list | GET /v1/model-versions | /models | sdk_live, e2e lifecycle | Done | Tenant-registered versions show self-declared metrics as "eligible" (A-02) |
| NR-F-10 | mr.activate | POST …:activate | /models/:id | srs, e2e lifecycle | Done | Activation takes no reason (UC-18 input), and none is audited |
| NR-F-11 | mr.rollback | POST /v1/models/{id}:rollback | /models/:id | srs::deployment_tracks… | Done | The path parameter is a version id named `model_id`; no reason is taken |
| NR-F-12 | rec | POST /v1/recommendations | /playground | test_recommendation_contract, sdk_live | Done | — |
| NR-F-13 | rec | POST /v1/recommendations/session | none (SDK only) | test_dgsr_serving_paths (skipped: no artifact) | Done-but-untested in IT | Add an integration test; consider a session mode in the playground |
| NR-F-14 | feedback.py | /v1/feedback/* | none (storefront) | srs::feedback_replay… | Done | — |
| NR-F-15 | usage/service | GET /v1/usage | /usage | test_usage | Done | — |
| NR-F-16 | deployment routes | /v1/deployment, /v1/metrics/summary | /service-status, /home | sdk_live | Done | — |

### Normal non-functional

| ID | Backend | Tests | Status | Gap |
|---|---|---|---|---|
| NR-NF-01 | RLS + principal | test_domain_isolation, test_*_isolated, sdk_live::tenant_isolation | Partial | There is no every-route × every-credential isolation suite (§6 requirement) |
| NR-NF-02 | principal | test_subscription_rejects_public_tenant_selector | Done | — |
| NR-NF-03 | errors.py | registration/login contract tests | Partial | Unhandled exceptions return Starlette plain-text 500s (A-03); 405 is mapped to 400 (A-23) |
| NR-NF-04 | — | warm sequential probe only (P95 49 ms, 20 requests) | Missing | No concurrent load test and no defined supported load |
| NR-NF-05 | events/ingestion idempotency | srs::catalog_sync_and_event_batch… | Done | — |
| NR-NF-06 | middleware correlation id | contract tests | Partial | A 500 carries no envelope or correlation id (A-03) |
| NR-NF-07 | OpenAPI, SDK | sdks/python tests | Partial | 8 routes return untyped `dict`/`list` (A-13); the contract test is red on the working tree |
| NR-NF-08 | rec fallback | srs, xr | Partial | The chain is not tested with Qdrant down, Redis down, no model, or an empty catalog together |

### Expected functional

| ID | Backend | Tests | Status | Gap |
|---|---|---|---|---|
| ER-F-01 | datasets snapshot contents | srs::snapshot_captures_real… | Done | — |
| ER-F-02 | worker.train_job | test_real_tenant_training_and_cancel | Done | — |
| ER-F-03 | worker.evaluate (Hit@1/10, NDCG@10, MRR@10, coverage@10, category diversity@10) | training test (asserts presence) | Partial | Metrics exist. `Recall@10` duplicates `Hit@10`. No test asserts the values |
| ER-F-04 | product/event/training/feedback idempotency | several | Done | — |
| ER-F-05 | rec response `model_version_id`, `strategy` | test_recommendation_contract | Partial | `model_version_id` is reported even when the popularity fallback served the response (A-20) |
| ER-F-06 | mr._validate_activation | srs::training_replays…failed_activation… | Done | — |
| ER-F-07 | mr rollback validation | srs::deployment… | Done | — |
| ER-F-08 | usage ledger | test_usage | Done | — |
| ER-F-09 | limits.require_capacity, admission | test_d16_admission, srs | Partial | `active_model_versions` counts only the single active version (A-06); `maximum_training_duration_minutes`, `concurrent_training_jobs` and `queued_messages` are not enforced (A-07) |
| ER-F-10 | rec fallback | srs, xr | Done | "Recent" popularity is actually all-time (A-19) |
| ER-F-11 | AuditLog writes | partial | Partial | Platform actions have `actor_reference=NULL`; reasons are not persisted for status, plan, quota, activation or rollback; activation and rollback carry no reason (A-09) |
| ER-F-12 | scoped reads | test_scope_enforcement | Done | — |

### Expected non-functional

| ID | Tests | Status | Gap |
|---|---|---|---|
| ER-NF-01 | test_interrupted_job_retries_once_then_fails_visibly (simulated heartbeat) | Partial | No real process-kill test (A-21) |
| ER-NF-02 | isolation tests | Done | Extend with the full route sweep |
| ER-NF-03 | test_dgsr_serving (skipped without artifacts), activation validation | Done | Needs the artifacts mounted in CI |
| ER-NF-04 | training failure_reason | Done | — |
| ER-NF-05 | — | Partial | Every exception is terminal; there is no transient/deterministic split (A-21) |
| ER-NF-06 | rerank tests, stable sort | Done-but-untested end to end | Add a determinism test on the API |
| ER-NF-07 | admission tests | Partial | Cold-start customers grow without bound (A-21b); the fallback aggregates per request (A-19) |
| ER-NF-08 | module layout | Done | — |
| ER-NF-09 | metrics/summary, platform status | Partial | No `/metrics`, structured logs or tracing |

### Exciting functional and non-functional

| ID | Backend | Endpoint / UI | Tests | Status | Gap |
|---|---|---|---|---|---|
| XR-F-01 | rec `_stored_history` + session context | /v1/recommendations | test_dgsr_serving_paths (artifact needed) | Done-but-untested in CI | — |
| XR-F-02 | retraining service + scheduler | /v1/retraining-policy, RetrainingPolicyPanel | xr::schedule_fires_once… | Done | `SRS_ACCEPTANCE.md` says this is unimplemented (stale) |
| XR-F-03 | same | same | xr::event_trigger… | Done | Stale doc, as above |
| XR-F-04 | recommendation_rules (diversity, category cap, freshness) | /v1/recommendation-policy, /recommendation-rules | test_xr_decisions, xr | Done | Brand and seasonality are absent. The SRS says "or", so I propose not adding them (decision D-14) |
| XR-F-05 | rollback of retired | as NR-F-11 | srs | Done | — |
| XR-F-06 | plan limits | — | — | Partial | Retained-version limit not enforced (A-06); serving capacity limited only to slots |
| XR-F-07 | usage/trends | GET /v1/usage/trends, UsageTrends | xr::usage_trends_match_ledger | Done | Stale doc |
| XR-F-08 | capacity.py + scheduler | GET /v1/deployment/scaling, ScalingPanel | xr::capacity_scales…, test_xr_decisions | Partial | "Replicas" are logical slot multipliers inside one process; no real instance scales (decision D-07) |
| XR-F-09 | popularity fallback | — | srs | Partial | Popularity is all-time, not recent; category and content cold start are not used (A-19) |
| XR-F-10 | metrics include popularity baseline | /models/:id | — | Partial | Comparison against the active version uses each job's own split; there is no common evaluation set |
| XR-NF-01 | `_set_deployment` binds capacity to the active version | xr | Done (for logical capacity) | Depends on D-07 |
| XR-NF-02 | rules `version`, `applied_rules`, `rules_version` | xr | Done | — |
| XR-NF-03 | retraining uses create_training_job | xr::nothing_fires_while_training… | Partial | No test for cooldown or plan quota on the *scheduled* path |

### Business rules

| ID | Status | Evidence / gap |
|---|---|---|
| BRULE-01 | Done | credential-derived tenancy; test_signed_cross_tenant_identity_fails_closed |
| BRULE-02 | Done | RLS tests; needs the full route sweep (NR-NF-01) |
| BRULE-03 | Partial | Unique constraint exists, but `ensure_customers` creates a customer for any id seen in a recommendation request (`rec:313`), with no quota and no event |
| BRULE-04 | Done | unique (tenant, external_id) |
| BRULE-05 | Done | event idempotency |
| BRULE-06 | Done | tenant advisory lock + active check (`mr:628`); xr test |
| BRULE-07 | Done | RLS + foreign-id tests |
| BRULE-08 | Done | lifecycle advisory lock; demote-then-promote |
| BRULE-09 | Done | `_servable()` + replay eligibility check |
| BRULE-10 | Partial | see A-06 and A-07 |
| BRULE-11 | Done | srs::feedback_replay_ownership… |
| BRULE-12 | Done | snapshot contents + cutoff |

### Use cases

| UC | Status | Gap |
|---|---|---|
| UC-01 Register | Done | email delivery |
| UC-02 Sign in | Partial | refresh flow |
| UC-03 Recover | Partial | Operator-issued token only. No self-service email. The token is shown to the operator |
| UC-04 Credentials | Done | — |
| UC-05–08 Products | Done | UC-08 "reason" input: check whether `:disable` persists a reason (not verified; will test) |
| UC-09–11 Events | Done | — |
| UC-12 Start training | Done | placeholder mode (A-02) |
| UC-13 Status | Done | — |
| UC-14 Cancel | Done (API, UI) | SRS input "reason" not accepted |
| UC-15 Result | Done | — |
| UC-16 Versions | Done | — |
| UC-17 Quality | Partial | XR-F-10 comparison |
| UC-18 Activate | Partial | reason and confirmation reason not recorded |
| UC-19 Roll back | Partial | reason not recorded |
| UC-20 Archive | Partial | reason not recorded |
| UC-21–23 Serving, feedback | Done | typed hints (A-13) |
| UC-24 Usage | Partial | the period/usage filter is rejected (`usage.py:34`); trends cover part of it |
| UC-25 Model status | Done | — |
| UC-26 Service status | Done | — |
| UC-27 Manage tenants | Partial | reason not persisted; no operator identity |
| UC-28 Plans and quotas | Partial | **UI exists** (the brief's "read-only" claim is stale). Reason and effective-period fields are missing |
| UC-29 Tenant usage | Partial | per-tenant only (`/v1/platform/tenants/{id}/usage`); no cross-tenant `/admin/usage` |
| UC-30 Platform status | Done | measurement gaps shown for worker and Redis |
| UC-31 Failures and audit | Partial | the last N rows only; no tenant, action, severity or time filter; no tenant-side redacted audit; no operator identity |

**Summary (101 IDs):** Done 65 · Done-but-untested 3 · Partial 32 · Missing 1 (NR-NF-04). Tests citing an ID: 8 functions. Most Done rows still need an ID-cited test.

---

## 3. API ↔ UI matrix

68 `/v1` routes. The console client (`frontend_02/src/api/index.ts`) calls 62 of them.

**Backend routes with no console use**

| Route | Verdict |
|---|---|
| POST /v1/recommendations/session | SDK and storefront caller. Add a session mode to the playground |
| POST /v1/feedback/impressions, clicks, conversions | Storefront-only by design. Document as SDK-only; no UI needed |
| POST /v1/model-versions | **Remove, or restrict to development** (A-02): it lets a tenant register a version with arbitrary metrics and a fake `rustfs://` URI |
| GET /v1/datasets/snapshots/{id} | The client has `getSnapshot` but no page calls it. Add a snapshot detail drawer |

**UI actions without a backend.** None found: every `api/index.ts` function maps to a real route. The WIP sidebar's "Workspaces" menu implies switching workspaces, which the backend does not support (A-26).

**Planned in `design/ROUTES.md` but missing on both sides**

| Feature | Backend needed | UI needed |
|---|---|---|
| Tenant audit `/audit` | `GET /v1/audit` (tenant, redacted, filtered) | page |
| Gate 2 `/account/tenant-status` | Today a suspended tenant cannot authenticate at all (`principal.py:125`), so the screen is unreachable. Needs a design decision (D-13) | layout + page |
| Cross-tenant usage `/admin/usage` | `GET /v1/platform/usage` | page |
| Per-user `/users/:id` | `PATCH /v1/tenant/users/{id}` (role), `:lock`, `:unlock`, `:disable`, `:resend-invitation` | page |
| Operator reasons | `reason` on the status, plan, quota and recovery bodies, persisted to audit | dialogs |
| Refresh | `POST /v1/auth/refresh` with rotation and reuse detection | client retry-on-`token_expired` |
| Version, readiness, metrics | `/v1/meta`, `/readyz`, `/metrics` | footer version |

**Brief claims already fixed in code:** plan assignment and plan editing (`TenantPages.tsx:311,386`), training cancel (`POST …:cancel` plus UI), the single job read, recovery and Users UI.

---

## 4. Anomaly register

| # | Sev | Finding | Evidence | Proposed fix |
|---|---|---|---|---|
| A-01 | **Critical** | Login, setup and recovery limit by `request.client.host`. Uvicorn runs without `--proxy-headers` behind nginx, so every browser shares one source bucket (8/min). One script can lock every tenant out of sign-in. The limiters are also per-process (they break with more than one worker), and their dicts grow without bound | `routes/auth.py:21-43`, `registration/rate_limit.py`, Dockerfile CMD, `nginx.conf` | Trusted-proxy client IP (`--proxy-headers --forwarded-allow-ips=<nginx>`). Move auth limiters to Redis with an in-process **fail-closed** fallback. Key them by account hash and by IP separately, with TTLs |
| A-02 | **High** | Fake model paths are live in production: `configuration.mode="placeholder"` creates an instantly "succeeded" model from random vectors, which then serves with a zero query vector. `POST /v1/model-versions` stores tenant-asserted metrics with status `eligible` and a non-existent `rustfs://` URI | `mr:340-455`, `mr:77-120`, `rec:371-383` | Gate both behind `GRAPHREC_ENV=development` (D-06). Mark them visibly in the UI. Remove the `rustfs://` URIs |
| A-03 | **High** | No catch-all exception handler: unhandled errors return Starlette's plain-text 500 with no envelope and no `X-Correlation-ID` | `apps/api/main.py`, `errors.py` | Add an `Exception` handler that returns the envelope and logs with the correlation id. Move the middleware to pure ASGI |
| A-04 | **High** | Suites are red. At HEAD, `test_platform_plan_assignment_preserves_overrides_and_usage` fails (POST returns `warnings` that GET lacks). On the working tree, the SDK contract fails on `GET /v1/events` and `AuthTokenPair.email`, and 4 of the 6 Playwright specs that ran fail (10 more did not run) because the WIP UI changed copy and layout | baseline §5 | Fix the contract, update the SDK, update the e2e specs for the shipped UI |
| A-05 | **High** | A refresh token is issued and stored, but there is no refresh endpoint, so the console signs users out after 15 minutes. This is a dead credential surface | `auth/service.py:561`, `api/client.ts:106` | D-03: rotation with reuse detection (recommended) |
| A-06 | **High** | The `active_model_versions` limit counts `status='active'`, which is always at most 1, so the 2/5/10 plan limit is never binding. `register_model_version` also writes `active_model_versions` ledger rows with random idempotency keys | `usage/limits.py:66`, `mr:107` | D-11: count non-archived versions; enforce at version creation |
| A-07 | **High** | Plan limits shown to users but not enforced: `maximum_training_duration_minutes` (30/60/180; the worker hard-codes 180 s), `queued_messages`, `concurrent_training_jobs` (Pro=2 contradicts BRULE-06 and the single global worker) | `worker.py:92`, `pricing_plans` | Enforce or remove each one (D-11, plan-limit change needs sign-off) |
| A-08 | **High** | No email: setup, invitation and recovery tokens are shown on screen or to the operator | registration, tenant_users, platform recovery | Pluggable transport plus a dev outbox (D-05) |
| A-09 | **High** | Platform audit cannot attribute an operator (`actor_reference=NULL`). Reasons are never captured for status, plan, quota, activation, rollback or archive. Platform audit has no filters (last N only) | `auth/service.py:220`, `platform.py:153-300` | Operator accounts (D-04), `reason` fields, filtered and paginated audit |
| A-10 | **High** | Weak defaults are accepted: `audit_hash_secret` and `api_key_hmac_pepper` have usable defaults, and the `AUDIT_HASH_SECRET=replace-with…` placeholder is *not* rejected (the validator covers only the JWT and platform token). There is no dev/prod profile | `settings.py:12-25,73` | `GRAPHREC_ENV`; in production refuse defaults, placeholders and short secrets |
| A-11 | **High** | 49 uncommitted files on `main`, including a second storefront (`apps/reel-storefront/`) and the marketing site | `git status` | D-01 |
| A-12 | Medium | The production image copies `tests/` and installs test extras. Dependencies are loosely pinned (`torch>=2.4` in pyproject but 2.8.0 in Docker; `numpy>=`, `python-multipart>=`; pydantic is transitive and unpinned, and resolved to 2.13) | `Dockerfile:17-24`, `pyproject.toml` | Multi-stage build, lock file, no tests in the image |
| A-13 | Medium | Untyped responses: `POST /v1/events`, `recover-password`, `platform …/quotas`, `…/recovery`, `…/plan` (None), `platform/status`, `GET /v1/events`, `catalog-syncs`, `plans` (bare `list`). `context` serving hints are `dict[str, Any]` | routes listing | Response models; a typed `RecommendationContext` |
| A-14 | Medium | Qdrant (6333/6334) and the API (8010) are published to the host. There is no TLS and no security headers (HSTS, CSP, frame-ancestors) | `docker-compose.yml`, `nginx.conf` | Production Compose with an internal network and TLS |
| A-15 | Medium | Timestamps come back in the DB session's timezone: on replay, `revoked_at`/`created_at` change from `…Z` to `…+06:00` when PostgreSQL is not set to UTC. This failed 3 integration tests until I set the DB timezone to UTC | `test_api_keys.py:305`, `srs:catalog…` | Normalise every serialized datetime to UTC; pin `timezone=UTC` on connect |
| A-16 | Medium | Tests depend on run order: `claim_training_job` takes the globally oldest queued job, so leftovers from other tests or tenants make the worker tests claim foreign jobs (failed on a reused DB, passed on a fresh one) | `test_training_worker.py` | Drain or isolate the queue in a fixture |
| A-17 | Medium | `registration_requests` has no RLS, and `graphrec_app` can SELECT every tenant's name and administrator email | live `pg_class` query | RLS or a SECURITY DEFINER lookup; revoke SELECT |
| A-18 | Medium | Chunked bodies (no Content-Length) skip the size limit. Every 4xx and 429 for an authenticated principal writes a synchronous audit row, which amplifies writes under abuse | `middleware.py:63-100`, `errors.py:55` | Stream-count body bytes; sample or aggregate denial audits |
| A-19 | Medium | The fallback does a full `GROUP BY` over *all* tenant events on every request. It is not "recent" (XR-F-09) and it is a P95 risk | `rec:431` | A windowed popularity table refreshed by the scheduler, plus a category cold start |
| A-20 | Medium | Responses report `model_version_id` when the popularity fallback served the response | `rec:458` | Report the version that served (null on fallback) and keep the active one separately |
| A-21 | Medium | Worker: every exception is terminal (no transient retry); no SIGTERM handling; failed job directories are not cleaned up; the stale timeout is a hard-coded 5 minutes | `worker.py:206-245`, `claim_training_job` | Classify errors, retry transient ones once, graceful shutdown, cleanup |
| A-21b | Medium | Customer rows are created from recommendation-request ids with no bound | `rec:313` | Create only from accepted events, or meter them |
| A-22 | Medium | DB pool is the default 5+10 under a 40-thread pool, with no statement timeout or connect timeout | `database/session.py` | Configurable pool, `statement_timeout`, timeouts |
| A-23 | Low | `http_error_handler` maps every non-404 (405, 415…) to `400 malformed_request` | `errors.py:150` | Map 405 to `method_not_allowed` |
| A-24 | Low | Four versions: API 0.1.0, package 0.1.0, web 0.2.0, SDK 1.0.0 | `main.py:32`, `package.json`, `_version.py` | One `VERSION` file and `/v1/meta` |
| A-25 | Medium | The pricing page hand-copies plan limits, so they drift as soon as an operator edits a plan | `marketing/plans.ts` | A public `GET /v1/plans` |
| A-26 | Medium | WIP UI invents data: the workspace name comes from the email domain ("example.org" → "Example") instead of the tenant name, and the "Workspaces" switcher implies more than one workspace | `Layouts.tsx:114-118,285` | Use the tenant name from the token or API; remove the switcher |
| A-27 | Medium | The frontend `/healthz` is a static 200 (a constant health value). The API `/healthz` checks only the DB; there is no `/readyz` | `nginx.conf:8`, `main.py:57` | Liveness and readiness probes that check Postgres, Redis and Qdrant |
| A-28 | Medium | The suspended-tenant gate cannot be reached: bearer auth rejects every non-active tenant | `principal.py:125` | D-13 |
| A-29 | Low | `Recall@10` duplicates `Hit@10` (single target) | `worker.py:123` | Drop it or label it |
| A-30 | Low | npm audit: 1 high (`source-map-js`, build-time only) | `npm audit` | Bump |
| A-31 | Low | `/v1/usage` rejects the UC-24 period filter | `usage.py:34` | Accept `period` |
| A-32 | Docs | Stale: `SRS_ACCEPTANCE.md` (says XR-F-02/03/04/07 are unimplemented and that the stack runs migration 0019); `frontend_02/README.md:96,107,120` (no recovery, no single job read, no cancel); `docs/srs-implementation-matrix.md` (migrations 0001–0026, "no Redis", TypeScript SDK); `docs/srs-implementation-report.md:64-66,140` (TS SDK was removed in `f77184b`); SRS plan table (Free 60 rpm / 4 concurrent, but 0031 set 120 / 8); `apps/demo-storefront/README.md:137` | — | Rewrite during Phase 2 |
| A-33 | Docs | `frontend_02/LANDING_PAGE_PROMPT.md` **does not exist** in the tracked or untracked-unignored tree | `git ls-files -co --exclude-standard` | D-02 |
| A-34 | Junk | Root `qa_*.ps1/py`, `.env.bak-qa`; `frontend_02/_ui5_src.tgz`, `dist/`, `e2e-results/`, `e2e-screens/`; `Claude outputs/` (tarballs, logs, screenshots, `HomePage.mine.tsx`, QA reports); `docs/chat-GraphRec E-Commerce Demo.txt`; `Palette and form specs/` (a design prototype, i.e. reference) | tree | D-12 (propose; I won't delete) |
| A-35 | Medium | No CI, no `/metrics`, no structured logs, no backups, no retention rules | — | Phase 5 |
| A-36 | Low | `POST /v1/models/{model_id}:rollback` takes a version id | `model_versions.py:71` | Document it or alias `/v1/model-versions/{id}:rollback` |

There are no open Critical items beyond A-01. A-02, A-03, A-04, A-05, A-06, A-09 and A-10 are the High items that gate Phase 3.

---

## 5. Baseline test results (2026-10-07)

**Environment limitation.** Docker could not run here: the daemon is not permitted in this session's container, and the Linux VM on your computer has no Docker. I therefore ran PostgreSQL **16** (the stack uses 17), Redis 7, and the Qdrant **1.12.0** binary natively, with the API, worker and scheduler under uvicorn/python and the console under Vite. Model artifacts were not mounted, so the artifact-dependent tests skipped.

| Suite | Command | Result |
|---|---|---|
| Backend unit | `pytest tests --ignore=tests/integration --ignore=tests/e2e` | **71 passed, 14 skipped** (artifacts absent) |
| Backend integration | `pytest tests/integration` on a fresh DB with UTC | **122 passed, 1 failed** (`test_platform_plan_assignment_preserves_overrides_and_usage`, A-04). On a non-UTC DB or reused queue: 5 failed (A-15, A-16) |
| SDK (contract + unit) | `pytest sdks/python/tests` | **2 failed**: `GET /v1/events` missing from the SDK; `AuthTokenPair.email` missing (both from the WIP) |
| SDK live | `tests/integration/test_sdk_live.py` | passed (inside integration) |
| Frontend vitest | `npx vitest run` | **74 / 74 passed** |
| Type check and build | `npm run build` | passed (JS 488 kB, 149 kB gzip) |
| npm audit | — | 1 high (dev-only) |
| Playwright | `npx playwright test` (Vite dev server, live API) | **2 passed, 4 failed, 10 did not run** (serial chain broke at console "setup"; lifecycle, training and route-overflow specs fail on the WIP UI) |

---

## 6. Plan for Phases 2–6

**Phase 2 (anomalies).** First, preserve the WIP per D-01. Then fix in this order: A-01, then A-03, A-04, A-15, A-16, then A-02, A-10, A-12, A-17, A-18, then the Medium and Low items. Each fix gets a failing test first and a CHANGELOG entry. Docs in A-32 are rewritten.

**Phase 3 (one product).** `GRAPHREC_ENV` profiles and a validated settings surface. A `VERSION` file with `/v1/meta` and a console footer. nginx serves `/` (marketing), the console, `/admin`, `/v1`, `/docs` (proxied OpenAPI UI), `/healthz` and `/readyz`. Response models on all 68 routes. `openapi-typescript` (justified: it removes hand-copied wire types) generates `src/api/schema.d.ts`, with a drift check. The SDK contract is extended to schemas. Rename `frontend_02` per D-08. Orphans from §3 are closed.

**Phase 4 (SRS).** The Partial and Missing rows above. Main items: a common evaluation set (XR-F-10), recent popularity and a category cold start (XR-F-09), filtered tenant and platform audit with reasons (ER-F-11, UC-31), user management (UC-27-adjacent, `/users/:id`), cross-tenant usage (UC-29), a Locust or k6 load test (NR-NF-04), the fallback chaos matrix (NR-NF-08), a real kill test (ER-NF-01/05), and ID-cited tests for all 101 IDs.

**Phase 5 (production).** Settings fail fast. Redis-backed auth limits that fail closed. Security headers and CSP. Email transport with a dev outbox. Operator accounts (if approved). `/metrics` (`prometheus-client`, justified), JSON logs (stdlib `logging` with a JSON formatter, no new dependency), optional OpenTelemetry. A multi-stage non-root image. `docker-compose.prod.yml` with Caddy or nginx TLS and only 443 exposed. Backup and restore scripts with a tested restore. Retention jobs. GitHub Actions running lint, mypy (scoped), tsc, unit, integration (services), contract, vitest, Playwright, pip-audit, npm audit, Trivy, and the OpenAPI drift check.

**Phase 6 (handover).** Fresh-clone deploy from the docs, all suites plus the load test, an independent review agent grading the matrix, and the final report.

### Open decisions (I need your answer before Phase 2)

| # | Decision | My recommendation |
|---|---|---|
| D-01 | 49 uncommitted files (marketing site, playground, `GET /v1/events`, reel-storefront, auth/event changes). Are they yours and in progress? | Commit them unchanged to a branch `wip/pre-phase2` so nothing is lost, then build Phase 2 on it |
| D-02 | `LANDING_PAGE_PROMPT.md` is missing. Do you have it, or should the WIP marketing site (`src/pages/marketing/*`) be the spec? | Send me the file if you have it |
| D-03 | Refresh tokens | Rotation with reuse detection (a reused token revokes the whole session family); the console refreshes silently on `token_expired` |
| D-04 | Operator accounts with roles `platform`, `plan_management`, `monitoring` and `audit`, argon2 passwords, an operator table, and audit attribution. This changes the auth model | Yes. Keep `PLATFORM_ADMIN_TOKEN` only as a one-time bootstrap to create the first operator, then disable it |
| D-05 | Email transport | SMTP via stdlib `smtplib` (no new dependency) plus a `console`/`outbox` transport in development. Self-service recovery replaces operator-issued tokens; the operator flow remains for support |
| D-06 | Placeholder training and `POST /v1/model-versions` | Development profile only; return 404 in production |
| D-07 | XR-F-08 real replica scaling | Defer real replicas and keep per-tenant slot scaling (honestly labelled "logical capacity"). Needs your sign-off as a deferral |
| D-08 | Rename `frontend_02/` | `web/` |
| D-09 | Two storefronts: `apps/demo-storefront` (Facet, tracked) and `apps/reel-storefront` (untracked). Which is the reference client? | Keep one behind `--profile demo`; you choose which |
| D-10 | Deploy target | Single-host `docker-compose.prod.yml` with Caddy (automatic TLS) on your domain. What is the domain, and do you want Kubernetes/Helm instead? |
| D-11 | Plan limits: count `active_model_versions` as non-archived retained versions; set Pro `concurrent_training_jobs` to 1 (BRULE-06); enforce `maximum_training_duration_minutes`; drop `queued_messages` or enforce it on batch queues. **This changes plan limits** | Approve as listed |
| D-12 | Stray material (A-34) | Move `Claude outputs/`, root `qa_*` and `.env.bak-qa` to an ignored `archive/`; keep `Palette and form specs/` as `docs/design-reference/`; delete build output (`dist`, `e2e-results`, tarballs). Nothing is deleted without your OK |
| D-13 | Gate 2: a suspended tenant cannot sign in at all | Allow sign-in to a restricted session (scope `account:status` only) that sees just `/account/tenant-status` |
| D-14 | XR-F-04 brand and seasonality | Not needed: the SRS uses "or", and diversity, category and freshness are implemented |
| D-15 | Tooling for this work: I need Docker to run the real Compose stack and Playwright against nginx. The daemon is blocked in this session and absent on your machine's VM | Either allow Docker here, or install Docker Desktop and let me drive `docker compose` on your machine. Until then I use native PG16, Redis and Qdrant |
| D-16 | CI: is the repo on GitHub (for Actions)? | GitHub Actions |
