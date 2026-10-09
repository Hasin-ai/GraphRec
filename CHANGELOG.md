# Changelog

All notable changes to GraphRec. Entries reference the anomaly register in
`docs/GAP_ANALYSIS.md` (A-xx) and the decisions in `docs/DECISIONS.md` (D-xx).

## [Unreleased] - Glass-box serving pipeline

### Added
- **Glass-box serving pipeline (`graphrec_core/serving/`)** is now the default for `POST /v1/recommendations` and `/session`:
  - query building from stored history plus session clicks (unchanged DGSR encoding);
  - four retrieval sources, each optional and individually timed: `dgsr_personalized` (Qdrant ANN under a 250 ms budget, in-memory item-table scoring when Qdrant is slow or down), `session_neighbors` (cosine neighbours of the last three viewed items), `popular_in_category` and `trending`;
  - one eligibility query against the servable catalogue for every source;
  - exact scoring: `0.85 × DGSR percentile + 0.05 × popularity percentile + 0.10 × source agreement`; items the model does not know stay below the personal median;
  - MMR diversity re-ranking (default 0.25, per request `diversity` 0–1), then the tenant's policy rules as before;
  - guarantee layer: short lists are topped up from the shopper's last good list in Redis (10 min, re-checked for eligibility, fail-open), then the tenant-popular tier.
- Response items carry `reason` (`because_you_viewed`, `picked_for_you`, `popular_in_category`, `trending`, `recently_recommended`), `sources`, `anchor_product_id` and `score`; responses carry `pipeline` and `diversity`, and `explain` (per-stage counts and timings, source status, per-candidate score breakdown) when the request sets `explain: true`.
- Python SDK: `explain` and `diversity` arguments on `recommendations.get` / `for_session` (sync and async) and the new response fields.
- `scripts/eval_serving.py`: offline leave-last-out replay of glass-box vs a plain DGSR Top-K baseline on a DGSR artifact. MovieLens, 3,000 held-out users: Recall@10 0.102 → 0.109, NDCG@10 0.054 → 0.057, intra-list diversity 0.60 → 0.68, catalogue coverage 0.28 → 0.26 (`docs/serving_eval_movielens.json`).
- Reel storefront: reason line on every tile ("Because you watched …", "Popular in Sci-Fi"), diversity slider on the home shelf, and a **Pipeline** tab in the insight drawer drawing the funnel, source status and candidate scores.

### Reel storefront demo controls (2026-10-10)
- **Reset guest:** `POST /api/reel/session/reset` and a "Reset guest" button start the guest over with a fresh anonymous session, so storefront history, the shelf diff and GraphRec's last-good list all begin empty. Named shoppers are refused (409 `reset_not_supported`): their events live in GraphRec.
- **Diversity slider fixes:** changes are committed once the slider settles (350 ms), so a drag or a run of arrow keys sends one request instead of locking the slider after the first step; a late answer can no longer overwrite a newer list; the range is capped at 0.8 (at 1.0 MMR ignores relevance); the shelf says when diversity does not apply (popular fallback).
- Playwright `e2e/reel-controls.spec.ts` covers both.

### Production hardening (full-stack verification 2026-10-10)
- **Qdrant circuit breaker:** after a Qdrant timeout or error the pipeline serves from the in-memory item table for 30 s instead of paying the 250 ms budget on every request; the ANN call now runs in parallel with the in-process sources.
- **Tenant popularity cache:** recent popularity is computed at most once per 15 s per tenant and process (eligibility is still checked per request); popularity failures no longer affect scoring beyond dropping its 5 % weight.
- Vectorised MMR and an `argpartition` Top-K for session neighbours.
- **Security updates (pip-audit / npm audit / Trivy clean):** FastAPI 0.116.1 → 0.136.3 with Starlette 0.47.3 → 1.7.0, PyJWT 2.10.1 → 2.15.0, torch 2.8.0 → 2.14.1 (Dockerfile and CI), setuptools 84, pytest 9.0.3; Reel storefront `react-router-dom` 7.6.0 → 7.18.3; API image runs `apt-get upgrade` and the web image `apk upgrade` at build time.
- Reel storefront build: Rollup pinned to 4.63.1 (4.64.2 hung during `vite build`).
- `VERSION` and the Python SDK version raised to 1.2.0 to match the released console (the version-sync test was failing).
- Lint (ruff F401) clean: 27 unused imports removed. Storefront `openapi.json` / `schema.d.ts` regenerated (were missing the proof endpoints).

### Removed
- The single-source serving funnel (Qdrant Top-K in rank order, popularity only when that came back empty) and its route helpers; the glass-box pipeline is the only serving path.

### Changed
- `RecommendationResult.candidate_source` records the item's primary retrieval source instead of `model_retrieval`.
- Impression feedback items are validated as `FeedbackItem` (identity and rank only), so explanation fields sent back by clients are ignored.

## [Unreleased] - Reel Reference Storefront Production Readiness

### Added (Phase 1 — Correct & Consistent Backend)
- **Single Source of Truth:** Backed shopper history and sequence directly by GraphRec interaction events (`client.storefront.events.list`), eliminating drift from local JSONL mirroring.
- **Durable Shared State:** Implemented `SharedState` (`app/storage.py`) with Redis backing for shelf before/after diffs (`last_lists`, TTL 24h) and impression attribution (`impressions`, TTL 7d), providing full consistency across multiple uvicorn workers and process restarts.
- **Cryptographically Signed Sessions:** Switched session identity cookie from raw unsigned string to HMAC-signed tokens via `itsdangerous`, rejecting tampered cookies safely and generating cold-start ephemeral visitors ("New visitor") on demand.
- **Arbitrary Developer Personas:** Supported arbitrary MovieLens IDs (`user:<id>`) in non-production environments to test arbitrary customer cohorts without modifying code.
- **Resilient Telemetry with Retry:** Added automatic retry for impression, click, and conversion feedback, recording telemetry health counters (`feedback_health`) without failing customer actions.
- **Rich Multi-Event Semantics:** Extended storefront event model to support `view`, `click`, `add_to_wishlist`, `rating` (1-5), and `purchase`, sending real client action timestamps (`occurred_at`).
- **Security Middlewares & Headers:** Added Content-Security-Policy (CSP), X-Frame-Options, X-Content-Type-Options, Referrer-Policy, strict Origin CSRF verification, request body size limit enforcement (413), and sliding window rate limiting (429 with `Retry-After`).
- **Health & Readiness Probes:** Added `/healthz` (liveness) and `/readyz` (deep readiness checking GraphRec API, Redis, catalogue sync, and active model version).
- **Directory Traversal Protection:** Hardened SPA fallback file serving with strict path containment (`is_relative_to`).

### Added (Phase 2 — Operability & Observability)
- **Structured JSON Logging:** Implemented `JsonFormatter` (`app/observability.py`) with ISO 8601 timestamps, request durations, and request correlation IDs propagated through `contextvars`.
- **Prometheus Metrics Exposition:** Added `/metrics` endpoint with token protection (`REEL_METRICS_TOKEN`), reporting HTTP traffic, GraphRec call latencies, fallback frequencies, feedback delivery failures, rate limit hits, and multi-worker Redis aggregation state.
- **Idempotent Tenant Bootstrapping:** Enhanced `scripts/bootstrap_reel.py` to reuse existing active tenants automatically, mask secrets in console logs, and support `--teardown` to suspend tenants and clean local state.
- **Production Hardened Container:** Pinned container dependencies (`requirements.txt`), configured unprivileged non-root user execution (`reel:reel`), and integrated deep readiness health check probes.
- **Operations & Deployment Manuals:** Authored comprehensive deployment guide (`docs/REEL_DEPLOYMENT.md`) and operational runbook (`docs/REEL_OPERATIONS.md`).

### Added (Phase 3 — Capability Proof Suite P1–P19)
- **On-Demand Capability Battery:** Built `app/proof/` package implementing capability checks P1 through P19 covering personalization, accuracy vs popularity, recency sensitivity, real-time dynamic updates, sequence window behavior, session recommendations, cold start, unseen item handling, seen item exclusion, eligibility filtering, event idempotency, determinism, business rules, model lifecycle, graceful degradation, closed feedback loops, tenant isolation, training specifications, and throughput/latency.
- **Standalone Verification CLI:** Created `scripts/prove_graphrec.py` with ASCII summary tables and machine-readable JSON output supporting `--profile tiny` and `--profile full` (achieved 19/19 100% PASS against MovieLens 32M checkpoint).
- **Storefront Proof Endpoints:** Added `POST /api/reel/proof/run` and `GET /api/reel/proof/latest` allowing on-demand proof triggering from browser or automation.

### Added (Phase 4 — UI Polish & Frontend Consistency)
- **OpenAPI Client Generation:** Exported OpenAPI specifications to `apps/reel-storefront/openapi.json` and generated TypeScript definitions (`src/api/schema.d.ts`) with `npm run gen:api` and `npm run check:api` drift CI verification.
- **Storefront Capability Proof Drawer:** Added dedicated "Proof" tab to the Reel storefront "How it works" drawer with interactive on-demand execution of test suite P1–P19 and expandable capability metrics.
- **Deep Readiness & Feedback Health Display:** Enriched the "Status" tab with real-time deep readiness status pills (GraphRec API, Redis, catalogue sync, active model) and telemetry delivery success/failure counters.
- **End-to-End Playwright Reel Verification:** Created `web/e2e/reel.spec.ts` testing the complete shopper journey from shelf loading, drawer inspection, capability battery execution, to film interaction and history updates.

## [1.2.0] - 2026-10-08

### Added (SaaS Elevation & Production-Grade UX)
- **App Shell & Information Architecture:** Re-architected console navigation into 5 core developer SaaS job groups (`Overview`, `Catalog`, `Models`, `Integrate`, `Workspace`).
- **Global Command Palette:** Added accessible `⌘K` / `Ctrl+K` command palette over all console and platform routes with fuzzy search, autocomplete, and keyboard arrow navigation.
- **Platform Operator Mode Indicator:** Added unmistakable prominent operator mode banner and topbar status badge to prevent operator/tenant confusion.
- **Tenant Onboarding Checklist:** First-run experience on Overview guided by real backend state (API credentials, interaction events, catalog sync, model training, playground testing, live activation).
- **Returning Tenant Dashboard:** Added KPI strip (24h requests, p95 latency, model freshness, quota capacity), recent training runs table, and system health status.
- **Interactive Playground:** Ranked item cards with copyable IDs, score indicators, storefront surface context selector, and live cURL & Python SDK code snippet generator.
- **SDK Developer Guide:** Upgraded `/integration` with language switcher tabs (Python SDK and HTTP/cURL) and comprehensive quickstart snippets.
- **Interactive Rule Simulation:** Added live preview on Recommendation Rules to simulate category diversity caps and freshness score boosts before saving.
- **Bundle Optimization:** Implemented `manualChunks` code splitting separating vendor, auth, marketing (<120 KB gzip), platform, and tenant console chunks (<250 KB gzip).
- **Component Documentation:** Published comprehensive UI system documentation in `web/src/ui/README.md`.

## Unreleased

### Added (Phases 4–6)
- XR-F-10 common-set version comparison; UC-24 usage by period; NR-NF-04 load test and `docs/PERFORMANCE.md`; NR-NF-08 fallback chaos tests; XR-NF-03 scheduled-retraining gate tests; SRS traceability guard and `docs/TRACEABILITY.md` (101/101 cited).
- ER-NF-09 `/metrics` and JSON logs; isolation sweep over every route; production Compose overlay with Caddy TLS; backup, staged restore and retention scripts; DEPLOYMENT, OPERATIONS, SECURITY and API docs; final report `docs/FINAL_REPORT.md`.
- Reel is the reference storefront (bugs fixed); Facet archived.

### Added (Phase 3)
- The console moved from `frontend_02/` to `web/` (earlier entries keep the old path).
- UC-27: administrators change a member's role, lock, unlock or disable them, and resend invitations (`GET`/`PATCH /v1/tenant/users/{id}`, `POST …/invitation:resend`, migration `0037`). Every change ends the member's sessions; the last active administrator and your own account are protected.
- UC-31: tenants read their own redacted audit trail (`GET /v1/audit`, scope `audit:read`, console page *Audit trail*). Platform operators appear by role, never by identity.
- UC-29: operators see every tenant's usage against its limits (`GET /v1/platform/usage`, console page *Usage*); unreadable usage shows "Unavailable", never zero.
- Generated TypeScript types (`web/src/api/schema.gen.ts`, `npm run gen:api`) and a compile-time contract between them and the console's types; CI fails on drift.
- D-04 operator accounts, D-11 plan-limit semantics and D-13 restricted sessions for suspended tenants (see `docs/DECISIONS.md`).

### Fixed
- A-04: `POST /v1/platform/tenants/{id}/plan` has a typed response (`PlatformPlanAssignmentResult`: the stored quota plus `warnings`); the acceptance test now checks both. Platform quota, recovery and status responses are typed in OpenAPI.
- A-15: every database connection uses `timezone=UTC`, so replayed responses keep identical timestamps whatever the server's TimeZone. Connections also get a statement timeout and configurable pool/connect timeouts (A-22).
- A-16: training-worker integration tests drain foreign queued jobs first, so they no longer depend on test order or leftover data.
- A-04: the Python SDK covers `GET /v1/events` (`events.list`) and `AuthTokenPair.email`; the contract test also checks the new platform response models. `GET /v1/events` declares `event_type` as a query parameter.
- A-03: unexpected server errors return the standard error envelope (`internal_error`, retryable) with a correlation id instead of a plain-text 500; the console shows that reference.
- A-23: `405` is reported as `method_not_allowed` instead of `400 malformed_request`.
- A-10: new `GRAPHREC_ENV` (`development` | `production`). In production the API, worker and scheduler refuse to start with default, placeholder or short secrets, a development database password, or no Redis.
- A-24: one product version (`VERSION`, now 1.1.0) shared by the API, the console build and the Python SDK. Public `GET /v1/meta` reports version, environment and development features; the console sidebar shows the version.
- A-02: placeholder training and manual `POST /v1/model-versions` are development-only. In production they are refused, non-DGSR versions cannot be activated or served, and the console hides the placeholder option. Fake `rustfs://` URIs are replaced by honest `placeholder://` / `unregistered://` markers.
- **A-01 (Critical):** sign-in, setup, recovery, registration, API-key, subscription and usage limits were per process and keyed on the nginx container's address, so every browser shared one 8-per-minute sign-in budget. They now use a Redis sliding window shared by all API processes; the real client address comes from a trusted proxy (`FORWARDED_ALLOW_IPS`); subjects are hashed; and when Redis is down the limits fall back to a bounded per-process window instead of failing open.
- A-05: sessions no longer end after 15 minutes. New `POST /v1/auth/refresh` (migration `0032_refresh_rotation`) rotates single-use refresh tokens without extending the sign-in's absolute lifetime; reusing a rotated token revokes all of that user's sessions and is recorded as a security event. The console refreshes transparently (single flight), and the SDK adds `auth.refresh()`.
- A-27: new `/readyz` checks PostgreSQL, Redis and Qdrant live and reports each (503 only without the database; `degraded` when Redis or Qdrant is down). Qdrant calls are bounded by `QDRANT_TIMEOUT_SECONDS` (default 5 s, was a hard-coded 10 s).
- A-12: the API image is multi-stage, non-root and contains no tests or test extras (a separate `test` target does). Python dependencies install from the new `constraints.txt` lock. The image runs `WEB_CONCURRENCY` uvicorn workers (default 2) with graceful shutdown and defaults to `GRAPHREC_ENV=production`.
- A-14: Compose binds the API and Qdrant ports to localhost only, trusts nginx as the forwarding proxy, adds restart policies and an `api-test` profile service, and probes `/readyz`.
- A-14/A-27: nginx sends CSP (`frame-ancestors 'none'`, no inline script), `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and `Permissions-Policy`; proxies `/healthz`, `/readyz`, `/docs` and `/openapi.json` to the API instead of answering health with a constant; caches hashed assets. The pre-paint theme script moved to `/theme-init.js`.
- A-17: `registration_requests` now has forced row-level security (migration `0033`). The runtime role sees only its own tenant's rows; pre-tenant replay checks use two SECURITY DEFINER lookups.
- A-18: chunked request bodies (no Content-Length) are bounded by the same per-route limits. Identical denial audits (same credential, reason and route) are capped at 5 per minute so rejected floods cannot become database write floods.
- A-19 / XR-F-09: the cold-start fallback ranks by *recent* popularity (`FALLBACK_POPULARITY_WINDOW_DAYS`, default 30, ending at the tenant's latest interaction) instead of all-time counts.
- A-20 / ER-F-05: `model_version_id` is the version that produced the ranking and is `null` when a fallback served it; new `active_model_version_id` reports the active version.
- A-21b / BRULE-03: recommendation requests no longer create customer records; only accepted interactions do.
- A-21 / ER-NF-01 / ER-NF-05: the training worker separates transient failures (database connection, network, vector store), which are retried once, from deterministic ones, which fail at once with a labelled reason. SIGTERM hands the running job back to the queue without spending an attempt, and partial artifact directories are removed. A new test kills a real worker process mid-batch and proves the job is reclaimed and completes.
- The scheduler stops cleanly after its current tick on SIGTERM/SIGINT (graceful shutdown for API, worker and scheduler).
- A-13: `POST /v1/events` and `POST /v1/auth/recover-password` have response models. Recommendation `context` is typed (`session_id`, `recent_product_ids` up to 200, `surface`; other keys are still accepted). A duplicate event returns its original `received_at`.
- A-25: public `GET /v1/plans` returns the active plans with their current limits; the pricing page and landing teaser read it (and say so when they fall back to the seeded defaults), so operator plan edits show up on the public site.
- A-26: the console labels the workspace with the tenant's registered name (new `tenant_name` in token responses) instead of guessing it from the email domain, and no longer shows a "Workspaces" switcher that implied more than one workspace.
- A-30: `npm audit` reports 0 vulnerabilities (build-time `source-map-js` updated).
- A-09 / ER-F-11 / UC-27 / UC-31 (part): reasons are stored in the audit trail (migration `0034`: a trigger attaches the request's reason to every audit row written in that transaction, including rows from the platform SQL functions). A tenant status change now **requires** a reason; plan, quota, plan-edit, recovery, activation, rollback, archive and training-cancel requests accept an optional one, and the console asks for it in each dialog. `GET /v1/platform/audit` filters by tenant, action, outcome and time range, pages with `next_before`, and returns actor, reason and correlation id. New `POST /v1/model-versions/{id}:rollback`; the older `/v1/models/{id}:rollback` is deprecated. Operator identity is still the shared token (D-04).
- One configuration surface: `.env.example` documents every setting (grouped, with purpose and safe defaults), Compose passes every setting to the services, and a test fails when either drifts from `graphrec_core/settings.py`.
- NR-F-15: usage dimensions carry `measured`; replica runtime (not recorded yet) shows "Not measured" instead of 0, and serving replicas report the tenant's current ready units.
- Console honesty fixes found by the browser suite: the getting-started checklist counts the 4 steps it shows (was "of 6"); placeholder runs are labelled "Synthetic placeholder" instead of "Trained on tenant data"; Service Status states that serving capacity is logical; breadcrumbs match navigation ("Events").
- A-04: Playwright specs updated to the shipped console (labels, menus, required reasons).
- CI (GitHub Actions): lint, migrations round-trip from 0031, unit/integration, SDK contract, OpenAPI drift check (`scripts/export_openapi.py --check`), pip-audit, tsc, vitest, build, npm audit, image build with a no-tests check, Trivy scan, and Playwright against the Compose stack.
- A-32: stale documents corrected: `frontend_02/README.md` (recovery, single job read, cancel, plans, users, sessions), `SRS_ACCEPTANCE.md` (XR features, migrations, recovery, capacity, worker kill), `docs/srs-implementation-matrix.md` (migrations, Redis, SDKs), `docs/srs-implementation-report.md` (marked historical), and the SRS plan table (Free limits from migration 0031). `docs/*.md` is no longer gitignored.
- Root README: production profile, verification commands (the API image no longer contains tests), and the new public endpoints.
- **D-11 (approved):** `active_model_versions` limits retained (non-archived) versions and is enforced when a version would be created; Pro allows 1 concurrent training job; `queued_messages` is removed; `maximum_training_duration_minutes` is enforced by the worker (capped at its 180 s local budget). Migration `0035`. Activation no longer consumes a plan unit, and manual registration no longer writes a stray ledger row.
- **D-04 (approved): named platform operators with roles.** Migration `0036`, `POST /v1/platform/auth/login`, `GET /v1/platform/me`, `/v1/platform/operators` (list, create, update); per-route role checks; operator attribution on every audit row; bootstrap-token rules for production; `scripts/create_operator.py`. The console signs operators in with email and password, filters navigation by role, and has an Operators page. SDK: `client.platform.operators`.
- **D-13 (approved): suspended workspaces.** A member of a suspended or deleting tenant signs in to a status-only session (scope `account:status`) that can call only `GET /v1/tenant/status` and `/v1/auth/logout`; every other route returns `403 tenant_inactive`. The console shows `/account/tenant-status` without navigation. Restricted tokens never become full sessions and cannot be refreshed. SDK: `client.tenant.account.status()`.
