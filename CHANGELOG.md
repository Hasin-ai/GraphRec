# Changelog

All notable changes to GraphRec. Entries reference the anomaly register in
`docs/GAP_ANALYSIS.md` (A-xx) and the decisions in `docs/DECISIONS.md` (D-xx).

## Unreleased

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
