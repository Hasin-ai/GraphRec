# Prompt: audit GraphRec end to end, fix it, unify it into one SaaS, complete the SRS, harden for production

> Paste everything below this line into a coding agent running at the repository root (`graphrec/`). It is a long-running, multi-phase task. Work through the phases in order and commit after each one.

---

## 0. Role, outcome and ground rules

You are the lead engineer taking GraphRec from "working vertical slices" to **one coherent, deployable SaaS product**. When you finish, all of these must be true:

1. **Anomalies fixed.** Every defect, inconsistency and stale claim you find in code, tests, configuration and docs has been fixed or explicitly recorded as out of scope, with a reason.
2. **One product.** The marketing site, tenant console, operator console, public API, worker and scheduler ship as a single product, behind one domain, with one deploy, one configuration surface and one version number.
3. **Frontend and backend in sync.** Every API capability a user needs has a UI. Every UI action is backed by a real endpoint. The wire types are generated from one contract, not hand-copied.
4. **SRS complete.** Every requirement in `GraphRec_Complete_SRS.md` is implemented and verified by a test, or formally deferred with the user's sign-off. This covers NR-F, NR-NF, ER-F, ER-NF, XR-F, XR-NF, BRULE and UC-01–31.
5. **Production ready**, as defined in §6. That definition is the bar, not "it runs on my machine".

**Ground rules**

- **Trust code and tests over documents.** The docs in this repo contradict each other and the code (examples in §2). Verify every claim by reading code and running it. Never mark something done because a document says so.
- **No fake behaviour.** No placeholder metrics, constant health values, invented data, or UI that implies a capability the backend lacks. If something cannot be built, say so in the UI and in the docs.
- **Tenant isolation is sacred.** Never weaken forced PostgreSQL RLS, credential-derived tenancy (NR-NF-02, BRULE-01/02), the non-BYPASSRLS runtime role `graphrec_app`, scope checks, or non-disclosing errors. Every change touching data access needs an isolation test.
- **Migrations are forward-only.** Add new Alembic revisions after `0031_*` and never edit applied ones. Every migration must upgrade cleanly on a fresh database and on a database at `0031`.
- **Keep the stack.** FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 17 + Redis + Qdrant + PyTorch DGSR on the backend; React 19 + React Router 7 + Vite + TypeScript with hand-written CSS tokens on the frontend; the Python SDK in `sdks/python`. Add a dependency only when it removes real risk, such as an OpenAPI type generator, a structured logging library or an email transport, and justify each one in the PR notes.
- **Stop and ask the user before** anything irreversible or product-defining: deleting a directory or app, changing the auth model (for example replacing the shared platform token), adding real payments, changing plan limits, or deferring an SRS requirement. Otherwise make the reasonable call and record it in `docs/DECISIONS.md`.
- **Work in small commits**, one concern each. The full test suite must pass at the end of every phase.

---

## 1. Phase 1: complete analysis (read-only; deliver the report before you change code)

Read the whole repository. At minimum read these:

- **Requirements:** `GraphRec_Complete_SRS.md` (2,372 lines: requirements §2, QFD §3, use cases and activity diagrams §4, data model §5, architecture, test plan), `SRS_ACCEPTANCE.md`, `docs/srs-implementation-matrix.md`, `docs/srs-implementation-report.md`.
- **Backend:** `apps/api/` (`main.py`, `middleware.py`, `errors.py`, `routes/*.py`), `graphrec_core/` (every package: auth, registration, api_keys, subscription, usage, catalog, events, ingestion, datasets, dgsr incl. `worker.py` and `serving.py`, models_reg, retraining, recommendation rules and policy, capacity, scheduler, vector_store, feedback, customers, database, schemas, settings), `migrations/versions/0001…0031`, `infrastructure/postgres/`, `scripts/`.
- **Frontend:** `frontend_02/` (README, `AUDIT.md`, `UI_AUDIT.md`, `IMPLEMENTATION.md`, `design/ROUTES.md`, `src/**`, `e2e/**`, `nginx.conf`, `Dockerfile`), plus `frontend_02/LANDING_PAGE_PROMPT.md`, the already-written spec for the public marketing site.
- **SDK and reference client:** `sdks/python/` (README, ANALYSIS.md, `src`, contract tests), `apps/demo-storefront/` (the "Facet" reference store).
- **Operations:** `docker-compose.yml`, root `Dockerfile`, `.env.example`, `.dockerignore`, `.gitignore`, `.gitattributes`, `pyproject.toml`, `alembic.ini`.
- **Tests:** `tests/` (unit, `integration/`, `e2e/`), `frontend_02/src/**/*.test.ts(x)`, `frontend_02/e2e/*.spec.ts`.
- **Stray material:** `Claude outputs/`, `Palette and form specs/`. Decide whether each one is product, reference or junk. Propose, don't delete.

Bring the stack up (`docker compose up -d --build`) and run every test suite to establish a baseline: backend unit, backend integration, SDK contract and live, frontend vitest, Playwright.

**Deliverable: `docs/GAP_ANALYSIS.md`**, containing:

1. **Architecture map.** Services, data stores, request paths, auth realms (tenant JWT, API key, platform token) and the background processes (worker, scheduler).
2. **Requirement traceability matrix.** One row for every SRS ID (NR-F-01…16, NR-NF-01…08, ER-F-01…12, ER-NF-01…09, XR-F-01…10, XR-NF-01…03, BRULE-01…12, UC-01…31). Columns: requirement → backend code → endpoint → UI route → test(s) → status (`Done` / `Partial` / `Missing` / `Done-but-untested`) → the concrete gap.
3. **API ↔ UI matrix.** Every `/v1` route and whether the console uses it. Every console action and the endpoint it calls. Flag orphans on both sides.
4. **Anomaly register.** Bugs, contract mismatches, dead code, stale docs, insecure defaults, missing tests, and performance risks. Give each a severity (Critical / High / Medium / Low), file:line evidence and a proposed fix.
5. **Baseline test results.**
6. **A plan** for Phases 2–6 with the open decisions listed for the user.

Post a summary to the user and **wait for confirmation on the open decisions** before Phase 2.

---

## 2. Known anomalies to verify first (from a prior read; confirm each, some may already be fixed)

**Documentation that contradicts the code**
- `SRS_ACCEPTANCE.md` says scheduled/event-triggered retraining, diversity policies, period trends and tenant autoscaling are unimplemented. Yet migrations `0027_retraining_policies`, `0028_recommendation_policies` and `0029_serving_capacity` exist, along with `routes/retraining.py`, `routes/recommendation_policy.py`, `GET /v1/usage/trends`, `GET /v1/deployment/scaling`, and the console pages `RecommendationRulesPage`, `RetrainingPolicyPanel`, `ScalingPanel` and `UsageTrends`. Find out what is really done.
- `frontend_02/README.md` says there is no recovery endpoint and no users UI, yet `POST /v1/auth/recover-password`, `RecoverPage`, `/v1/tenant/users` and `UsersPage` exist. It also says there is no single training-job read and no cancel endpoint, but `GET /v1/training-jobs/{id}` and a `POST /v1/training-jobs/{id}:…` action route exist.
- `Claude outputs/ANALYSIS.md` refers to `frontend/` and 9 migrations, and describes placeholder training and constant metrics. Check which of these are still true.
- The SRS "Provisional Demonstration Plan Limits" table is stale for Free: migration `0031` changed it to 120 rpm and 8 concurrent.

**Product and contract gaps**
- `POST /v1/auth/login` returns a refresh token, but the console has no refresh flow and signs users out when the 15-minute access token expires. Decide on refresh rotation (with reuse detection) or remove refresh tokens. Do not leave it half-built.
- Account setup and invitation tokens are shown on screen and nothing emails them. Recovery tokens depend on an operator. Production needs email delivery (§6).
- The platform realm is one shared `PLATFORM_ADMIN_TOKEN`. The prototype in `design/ROUTES.md` defines named permissions (platform, plan-management, authorized scope, monitoring, audit), and the audit trail cannot say *which* operator acted. Propose real operator accounts with roles; this needs user sign-off.
- Plan assignment (`0018`) and plan edit (`0020`, `PUT /v1/platform/plans/{id}`) exist in the backend, but the console treats plans as read-only.
- Operator "reason" inputs (tenant status change, rollback) have been removed or are not persisted. ER-F-11 needs reasons in the audit trail.
- These were planned in `design/ROUTES.md` and are missing: tenant-scoped audit (`/audit`), the gate-2 tenant-status screen (`/account/tenant-status`), cross-tenant usage (`/admin/usage`) and per-user management (`/users/:id`: lock, unlock, disable, change role, resend invitation).
- Optional serving hints are untyped. Cold-start IDs register as customers on successful requests; check this against BRULE-03.
- ER-F-03 / XR-F-10: there is no common-dataset comparison across versions; metrics come from each job's own split.
- XR-F-08 / XR-NF-01: capacity control against a single API process. Decide what "adjusting serving capacity" means in a real deploy and implement it honestly (§5).
- NR-NF-04: P95 < 300 ms at supported concurrent load has never been characterised.
- ER-NF-01/05: abrupt worker termination during a real training batch is uncertified.

**Production and operations gaps**
- There is no CI pipeline. Nothing gates merges.
- The production image copies `tests/` and installs test extras.
- Qdrant publishes ports 6333/6334 to the host.
- There is no TLS, no secret management beyond `.env`, no backups, no structured logs, no metrics endpoint and no tracing.
- The API runs as one uvicorn process. Rate limits and slot leases rely on Redis, so check what happens when Redis is down.

---

## 3. Phase 2: fix anomalies

Work through the anomaly register from Critical to Low. For each fix:

- write a failing test that reproduces it, then fix it;
- update every document that described the old behaviour;
- log the fix in `CHANGELOG.md` under an "Unreleased" heading.

Never delete a test to make a suite pass.

---

## 4. Phase 3: one SaaS and a synced contract

**Product shape** (record the final choices in `docs/DECISIONS.md`):

- **One origin.** `/` is the public marketing site (implement `frontend_02/LANDING_PAGE_PROMPT.md` as written). The console lives at `/home`, `/products` and its other routes; the operator console at `/admin/*`; the API at `/v1/*`; health checks at `/healthz` and `/readyz`; API reference docs at `/docs`.
- **Naming.** Rename `frontend_02/` → `web/` (or a name the user chooses) and fix every reference: Compose, Dockerfiles, READMEs, SDK docs and Playwright config. Remove the leftover `frontend/` references.
- **The demo storefront stays a separate reference client.** It consumes GraphRec only through the public SDK and gets an optional Compose profile (`--profile demo`). It is not part of the SaaS deploy.
- **One version.** A single version string shared by API, web build and SDK, exposed at `GET /v1/meta` and shown in the console footer.
- **One configuration surface.** Every setting lives in `graphrec_core/settings.py`, is documented in `.env.example` with its purpose and a safe default, is validated at startup (fail fast on missing or weak secrets in production mode), and is split into `development` / `production` profiles.

**Contract sync**

- Make the FastAPI OpenAPI schema the single source of truth. Every route needs an accurate response model, error responses and scope documentation.
- Generate the frontend wire types from it (for example `openapi-typescript`) and replace hand-written `frontend_02/src/api/types.ts`. Add a CI check that fails when the generated types drift.
- Extend the SDK contract test (`sdks/python/tests/test_contract.py`) so it fails on any route or schema drift.
- Close every orphan from the API ↔ UI matrix: build the missing UI or remove the dead endpoint. The minimum list:
  - plan assignment and plan edit in `/admin`;
  - per-user management;
  - tenant audit;
  - the tenant-status gate;
  - cross-tenant usage;
  - training cancellation if the endpoint exists;
  - persisted operator reasons;
  - the refresh flow (or its removal).
- Errors use one envelope everywhere (`error.code`, `message`, `correlation_id`, `retryable`, `details.fields`), and the frontend maps every code.

---

## 5. Phase 4: complete the SRS

For every `Partial` or `Missing` row in the matrix, implement it to the SRS wording and the matching use case and activity diagram in §4 of the SRS. Each requirement ID needs at least one automated test whose name or docstring cites the ID (for example `test_er_f_06_failed_activation_keeps_previous_version`).

Areas that need specific attention:

- **ER-F-03 / XR-F-10.** Evaluate next-item accuracy (HR@K), ranking quality (NDCG@K, MRR), catalog coverage and intra-list diversity on a held-out split. Compare the candidate against the popularity baseline *and* the active version on a **common** evaluation set before activation, and show the comparison in the model-version UI.
- **XR-F-02 / 03 / XR-NF-03.** Scheduled and event-count retraining must obey cooldown, plan quota and one-active-training (BRULE-06). Test all three constraints.
- **XR-F-04 / XR-NF-02.** Diversity and freshness rules must be bounded and versioned. Every response reports `applied_rules` and `rules_version`. Add brand or seasonality only if the SRS demands them for completion; ask if unclear.
- **XR-F-08 / XR-NF-01.** Capacity adjustment within plan limits must keep tenant and active-version consistency. If true per-tenant replicas are not feasible in the target deploy, implement the closest honest form (per-tenant concurrency slots that scale with measured demand), document the gap, and get the user's sign-off on the deferral of real replica scaling.
- **NR-NF-04.** Write a reproducible load test (k6 or Locust) that defines "supported demonstration load" in numbers, measures P95 for identified and session recommendations, and records results in `docs/PERFORMANCE.md`. Fix hot paths until the target holds or the gap is documented.
- **NR-NF-08 / ER-F-10 / XR-F-09.** Define and test the fallback chain end to end, including with Qdrant down, Redis down, no active model and an empty catalog.
- **ER-NF-01 / 05.** Kill the worker mid-batch (a real process kill, not a simulated heartbeat). Prove the job retries once on transient failure and terminates visibly on deterministic failure.
- **ER-F-11 / UC-31.** The audit trail must be append-only and record actor, action, target, reason and correlation ID for credentials, activation, rollback, quota and plan changes and every operator action. The tenant can read its own audit trail in redacted form.
- **NR-F-15 / XR-F-07.** Usage, limits, remaining quota, reset period and trends must reconcile with the ledger. Never show a zero for an unavailable measurement.

Out of scope per the SRS: real payment processing, multi-region, enterprise DR and HA, tenant-supplied model code, and online training. Do not build these. Payments in particular need explicit user approval.

---

## 6. Phase 5: production readiness (the definition)

**Security**
- No default or weak secrets in production mode; the app refuses to start.
- Secrets come from the environment or a secret manager, never baked into images.
- Argon2 password hashing with set parameters.
- Login and recovery rate limits that still work if Redis is down (fail closed for auth).
- Security headers at nginx: HSTS, CSP suited to the SPA, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`.
- Strict CORS: same origin by default, with an explicit allowlist when configured.
- Dependency and image scanning (`pip-audit`, `npm audit`, Trivy or equivalent) in CI.
- An isolation test suite proving that tenant A cannot read or change any of tenant B's resources over every route and credential type.
- Operator authentication with individual identities and audit attribution, if the user approves (§2).

**Email**
- A pluggable transport (SMTP / provider) for setup links, invitations and self-service password recovery.
- A console "outbox" transport for development.
- Tokens are single-use, time-limited and stored only as hashes.

**Reliability**
- `/healthz` (liveness) and `/readyz` (checks Postgres, Redis and Qdrant and reports each).
- Graceful shutdown for API, worker and scheduler.
- Timeouts and bounded retries on every outbound call.
- Idempotency everywhere the SRS asks for it (ER-F-04).
- Multiple API workers or replicas behind nginx without breaking rate limits, slot leases or sessions.
- Compose `restart` policies and resource limits.

**Data**
- Migrations run as a one-shot job before rollout.
- Documented backup and restore for Postgres, Qdrant and the model-artifact volume, with a tested restore script.
- Retention rules for events, serving logs and audit records.

**Observability**
- Structured JSON logs carrying the correlation ID across API, worker and scheduler, with no secrets or PII.
- A Prometheus `/metrics` endpoint (request rate, latency histogram, errors by code, quota rejections, training jobs by state, fallback rate).
- Optional OpenTelemetry tracing.
- Example alert rules.

**Delivery**
- Multi-stage, minimal, non-root images with no tests or test extras in production images.
- Pinned versions.
- A production Compose file (or Helm chart, if the user wants Kubernetes) with TLS termination, no publicly exposed internal ports (Qdrant, Redis and Postgres stay internal), and persistent volumes.
- CI, for example GitHub Actions:
  - lint (`ruff`, `mypy` where feasible, `tsc`, ESLint if added);
  - unit, integration (against Compose services), SDK contract, vitest and Playwright;
  - OpenAPI drift check;
  - image build and scan.

**Docs**
- Root `README.md`: product overview, quick start and architecture diagram.
- `docs/DEPLOYMENT.md`: production deploy, configuration reference, TLS, scaling, upgrades.
- `docs/OPERATIONS.md`: runbooks for a stuck training job, Qdrant down, quota disputes, key compromise, restore from backup.
- `docs/SECURITY.md`: threat model and isolation design.
- `docs/API.md` (or the hosted `/docs`).
- An updated `SRS_ACCEPTANCE.md` that matches reality.
- A `CHANGELOG.md`.

**Honesty**
- The marketing site and console must not claim uptime, SLAs, certifications or capacity beyond what §5's load test measured.
- SRS CON-05 framed the semester build as educational. Update the positioning only as far as the evidence from this work supports.

---

## 7. Phase 6: verification and handover

1. Start from a fresh clone, `cp .env.example .env`, fill in the secrets, and bring up the production profile. Everything must come up healthy with no manual steps beyond those in `docs/DEPLOYMENT.md`.
2. Run every test suite and the load test. Record the results.
3. Walk the SRS user story (§2.7) through the real UI and SDK, end to end. Use a separate review agent or a checklist you didn't write to grade the traceability matrix, so the work isn't grading itself.
4. Regenerate `docs/GAP_ANALYSIS.md` as the final traceability matrix: every row is `Done` with a test, or `Deferred (approved by user on <date>)`.

**Final report to the user:**
- what changed, per phase;
- the final traceability summary (counts by status);
- every deferral and decision, with links to `docs/DECISIONS.md`;
- test and load-test results;
- known risks;
- the exact commands to deploy.

---

## Definition of done (all must hold)

- [ ] Every SRS ID is `Done` with a citing test, or its deferral was approved by the user.
- [ ] The anomaly register has no open Critical or High items.
- [ ] One domain, one deploy, one version and one config surface. The marketing site is live at `/`.
- [ ] Wire types are generated from OpenAPI, CI fails on drift, and the SDK contract test passes.
- [ ] There is no orphan endpoint and no UI action without a backing endpoint.
- [ ] Isolation, security, reliability and observability items from §6 are in place and tested.
- [ ] CI is green: lint, unit, integration, contract, vitest, Playwright, image scan.
- [ ] A fresh-clone production deploy works from the docs alone.
- [ ] The docs match the code, and no stale or contradictory document remains.
