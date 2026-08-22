# GraphRec — Full-Stack Build Prompt

**Audience:** the engineer or AI coding agent implementing GraphRec.
**Companion document:** `BACKEND_PLAN.md` — the architecture of record. This prompt is the *instruction*; that plan is the *reference*. Where this prompt says "see §N", it means `BACKEND_PLAN.md` §N.
**Scope:** the complete backend **and** the React console, wired together and working end to end.

---

## 0. Your mission

Build GraphRec: a multi-tenant recommendation platform-as-a-service. Independent e-commerce businesses register as tenants, provision users and API credentials, synchronize a product catalog, stream customer-interaction events, train a tenant-specific DGSR model, review its quality, activate or roll back a model version, and consume real-time Top-N recommendations server-to-server.

You are building two things that must fit each other exactly:

1. **The backend** — a Python 3.12 / FastAPI modular monolith plus four specialised processes, over PostgreSQL with Row-Level Security, Redis and S3-compatible object storage.
2. **The React console** — 36 routes, 4 layout shells, 3 authorization realms, built from an existing prototype and wired to the real API.

### The four documents that bind you

| Document | Authority over |
|---|---|
| `docs/BSSE1415_SPL3_mid.docx` | **Requirements.** NR/ER/XR ids, UC-01…UC-31, the 16 logical entities in §5.2. Highest authority |
| `Design system decision pending/GraphRec Console.dc.html` | **The console.** Routes, gates, enumerations, data shapes, action preconditions, user-facing copy |
| `BACKEND_PLAN.md` | **The architecture.** Schema, endpoints, module boundaries, phases |
| `docs/FRONTEND_BUILD_PROMPT.md` | Endpoint paths and naming recovered from a prior implementation; frontend design system §11 |

**`API.md` is NOT binding.** See D1 below.

### Ground rules

1. **Read before you write.** Read `BACKEND_PLAN.md` in full and open `GraphRec Console.dc.html` before Phase 1. The prototype is 1,860 lines and is the single most information-dense artefact in the repository.
2. **The prototype is an executable specification.** Every enum value, every disabled-button reason, every error string in it is a requirement. Reproduce them, do not paraphrase them.
3. **Build in the phase order in §11.** Phases 1–2 are hard prerequisites. Retrofitting `tenant_id` and RLS onto a populated schema is the single most expensive mistake available in this project.
4. **Stop at the CONFIRM gates.** Decisions D1–D12 are provisional. Each names a phase before which a human must confirm it. Do not build past a gate on an unconfirmed decision.
5. **Never weaken tenant isolation to make something work.** If isolation and a feature conflict, the feature is wrong.
6. **Report what you could not do.** A phase report that says "skipped the isolation tests" is far more useful than one that silently omits them.

---

## 1. What exists in this workspace, and what does not

Before you plan any work, understand the starting state. It is unusual.

**There is no code.** `git` has zero commits; every file is untracked. There is no `apps/`, no `graphrec/`, no `migrations/`, no `frontend/`, no tests.

**`docs/PROJECT_OVERVIEW.md` describes a system that is not here.** It documents `apps/api/`, `graphrec_core/`, eight Alembic migrations and 57 tests. None of it exists. Treat that document as a historical record of a prior build — useful evidence of API shape, worthless as a description of current state. `docs/FRONTEND_BUILD_PROMPT.md §2b` confirms this: its endpoint table is *"Paths recovered from a prior implementation of this system."*

**The "existing frontend" is a prototype, not an application.** `Design system decision pending/GraphRec Console.dc.html` is a hash-routed single file with an in-memory `seed()` store, ~30 page functions and **no network layer whatsoever**. `support.js` beside it is a generated design-canvas runtime, not application code — do not read it as a source of truth and do not copy from it.

**What you inherit that is real and must be honoured:**

| File | What it gives you |
|---|---|
| `alembic.ini` | Migration config already pointing at `script_location = migrations`, with a **separate owner role** (`graphrec_owner`) distinct from the runtime role — the RLS separation the design requires |
| `.env` / `.env.example` | 30+ real settings: token TTLs, five rate-limit classes, API-key HMAC pepper and hash version, credential caps, demo-account bootstrap. Keep every key that §22.4 marks "keep" |
| `.dockerignore` | Excludes `frontend`, confirming the React app sits beside the backend at repo root |
| `.gitignore` | Already excludes `.env`. Keep it that way |

**Start by initialising the repository properly:** first commit should be the existing documents, so the build history begins from a known state.

---

## 2. Locked decisions — provisional, each with a CONFIRM gate

`BACKEND_PLAN.md §7` found twelve conflicts across the four architecture documents in this workspace. Each is resolved below **with a recommendation you should build to**, and each is marked with the phase before which a human must confirm it.

Treat these as settled *for planning purposes* so you build one coherent system. But **halt at the named gate and ask** before the phase that depends on the decision. If a decision is overridden, update `BACKEND_PLAN.md` and this prompt before continuing.

| # | Decision | Build this | Rejected | CONFIRM before |
|---|---|---|---|---|
| **D1** | **API resource model** | **SRS-native**: tenants, users, credentials, products, events, submissions, training jobs, snapshots, model versions, deployments, recommendations, feedback, usage, plans, audit | `API.md`'s AWS Personalize model (dataset groups, schemas, solutions, campaigns). The console has **none** of those nouns; the SRS §5.2 has none of them either | **Phase 2 — blocking** |
| **D2** | Job queue | **PostgreSQL `SELECT … FOR UPDATE SKIP LOCKED`** over a `jobs` table | RabbitMQ + Celery + transactional outbox + publisher process | Phase 4 |
| **D3** | Orchestration | **Docker Compose + systemd**, with a `ServingDriver` port so a **k3s adapter** can be added for the XR-F-08 scaling demonstration | k3s as a day-one dependency | Phase 11 |
| **D4** | Candidate retrieval | **In-process exact top-K** behind a `CandidateIndex` port; **Qdrant adapter** implementing the SRS §6.3 collection contract, added when that contract must be demonstrated | Qdrant as a day-one dependency | Phase 10 |
| **D5** | Token signing | **EdDSA (Ed25519)** + published JWKS | HS256 with a shared secret (what `.env` currently has). Per-tenant inference must verify locally without a control-plane call, and a shared secret would let every inference process *mint* tokens | Phase 2 |
| **D6** | Path versioning | Everything under **`/v1`**; platform-realm endpoints under **`/v1/platform/*`** | The recovered inventory's unversioned `POST /login`, `GET /tenants`, `GET /audit` — and two same-named resources in different realms | Phase 2 |
| **D7** | Request body limits | **Per-endpoint.** 16 KB default; ~2 MB for `:bulk-upsert` and `/events/batches` | A single `MAX_REQUEST_BODY_BYTES=16384`, which is 37× too small for the 5,000-product sync the console offers | Phase 1 |
| **D8** | Model version lifecycle | **The prototype's seven values**: `registered · eligible · active · retired · rejected · archived · failed_deployment`. `TRAINING`/`EVALUATED`/`FAILED` stay inside the training job; `DEPLOYING` becomes `model_deployments.state = 'progressing'` | Overlapping 11-value vocabularies from `API.md` / `SYSTEM_DESIGN.md` | Phase 10 |
| **D9** | Product create verb | **All three.** `POST /v1/products` create-only (409 on duplicate, serves `/products/new`); `PUT /v1/products/{external_id}` idempotent upsert; `PATCH` partial update | Upsert-only, which can never produce the 409 the console renders | Phase 5 |
| **D10** | Pagination | **`limit`/`offset` + `total`** for console lists; **cursor** for high-volume reads (`interaction_events`, `audit_logs`, `recommendation_requests`) | Cursor everywhere — every console table renders `"8 of 12"`, which needs a total | Phase 5 |
| **D11** | Plan codes and limits | **The prototype's**: `STARTER` / `GROWTH` / `SCALE` with its event/rec/training/product/storage numbers | `Ultimate §20`'s Free/Basic/Pro table | Phase 2 |
| **D12** | Field naming | **`snake_case`** throughout | `camelCase` | Phase 2 |

**D1 is the blocking one.** If it is overridden in favour of the Personalize model, `BACKEND_PLAN.md §12` and the whole console integration map are invalid and this prompt must be rewritten. Get it answered first.

### Also confirm before you start

These are open questions with no recommendation, because they need a human:

- **Email delivery.** Invitations (`/invite/accept`) and account recovery (`/recover`) both need out-of-band token delivery. Does SMTP exist? If not, build an admin CLI that prints the token and say so in your report.
- **The 15-minute training cooldown** appears only on a stat card in the prototype and nowhere in the SRS. Is it a real rule?
- **The last-active-administrator rule** is explicitly *"Derived safety rule, not in the SRS"* (root `ROUTES.md`). Build it — but confirm.
- **Customer data lifecycle.** SRS §5.2.5 defines `active · anonymized · deleted` but no use case exposes customers to any human. Store customers (events reference them), expose no console route, and provide an unadvertised admin-only anonymization endpoint. Confirm with the supervisor.

---

## 3. Technology stack — pin these

| Layer | Use | Notes |
|---|---|---|
| Language | Python 3.12 | Same toolchain as PyTorch |
| API | FastAPI + Pydantic v2 + Uvicorn | Pydantic models are the API contract |
| ORM | SQLAlchemy 2.0 | Explicit sessions — required for `SET LOCAL` per transaction |
| Migrations | Alembic | `alembic.ini` already exists; do not replace it |
| Database | PostgreSQL 16+ | RLS, `SKIP LOCKED`, JSONB, BRIN — all load-bearing |
| Cache | Redis 7 | Rate limits, locks, session context, `jti` denylist. **Nothing authoritative** |
| Object storage | S3-compatible (MinIO or RustFS) | One client; endpoint is configuration |
| ML | PyTorch 2.x + PyTorch Geometric | CON-01 fixes DGSR as the model family |
| Artifacts | **safetensors** + JSON/Parquet manifests | **Never `pickle` across the worker→inference boundary** |
| Passwords | Argon2id | |
| Tokens | JWT, EdDSA (Ed25519) | D5 |
| API credentials | HMAC-SHA-256 + server pepper, versioned | `.env` already has `API_KEY_HMAC_PEPPER`, `API_KEY_HASH_VERSION` |
| Lint / types | Ruff + mypy | CI gate |
| Tests | pytest + httpx + testcontainers + Locust | |
| **Frontend** | **React 18 + TypeScript + Vite** | |
| Routing | React Router (nested routes, layout routes, loaders) | The prototype's gate model maps onto loaders — see §10 |
| Server state | TanStack Query | Polling, cache invalidation, optimistic updates |
| Forms | React Hook Form + Zod | Zod schemas mirror the backend's Pydantic models |
| Styling | Plain CSS with tokens | Design system is **not final** — see §10.7 |
| FE tests | Vitest + React Testing Library + MSW | MSW mocks the API for component tests |

**Do not add:** RabbitMQ, Celery, Kubernetes (until D3 says so), Qdrant (until D4 says so), MLflow, Ray, a vector database, OpenTelemetry, a state-management library beyond TanStack Query, or a component library. Each was considered and rejected with reasons in `BACKEND_PLAN.md §8.6`.

---

## 4. Repository layout

```
graphrec/
├── apps/
│   ├── control_api/        FastAPI — routers, deps, middleware, errors
│   ├── job_worker/         CPU worker — claim loop + handlers
│   ├── training_worker/    GPU worker — nine pipeline stages
│   ├── reconciler/         deployment controller, leader-locked
│   └── inference/          per-tenant serving process
├── graphrec/               shared library — imported by every app
│   ├── domain/             identity · tenancy · credentials · catalog · ingestion
│   │                       training · registry · serving · metering · audit · platform
│   ├── db/                 models · session · tenant_context · repositories
│   ├── jobs/               queue client · claim · lease · retry · fair share
│   ├── storage/            S3 client · bucket layout · presigning · manifests
│   ├── ml/                 features · graph · model · train · eval · index · bundle
│   ├── serving_driver/     ServingDriver port + compose/k3s adapters
│   └── common/             config · logging · errors · clock · ids
├── frontend/               React console
│   ├── src/
│   │   ├── api/            generated types + typed client + hooks
│   │   ├── auth/           token store, session context, realm handling
│   │   ├── routes/         one file per route, mirroring the prototype's pg_* functions
│   │   ├── layouts/        PublicLayout · StateGateLayout · TenantLayout · PlatformLayout
│   │   ├── guards/         gates 1–4 as loaders
│   │   ├── components/     the 19 primitives — see §10.5
│   │   ├── lib/            enums (generated), formatting, error rendering
│   │   └── styles/         tokens.css + global.css
│   └── tests/
├── migrations/             alembic
├── deploy/                 single/ · node1/ · node2/ · node3/ · k3s/ · systemd/
├── tests/                  unit/ integration/ api/ authz/ isolation/ db/ ml/
│                           inference/ load/ contract/
├── scripts/                backup · restore · seed · smoke · demo-account · gen-enums · gen-client
└── docs/                   existing docs + runbooks + ADRs + openapi.json
```

**One shared library, five thin applications.** Domain logic lives in `graphrec/domain/`; apps wire transport to it. Modules import each other only through published interfaces — enforce it with an import-linter rule in CI.

---

## 5. The API contract

Full endpoint specification: `BACKEND_PLAN.md §12` (~70 endpoints). What follows is the part you must not get wrong.

### 5.1 Conventions

| Aspect | Rule |
|---|---|
| Base | `/v1`. Trailing slashes rejected |
| Naming | `snake_case` everywhere |
| Timestamps | RFC 3339, UTC, explicit offset |
| Money | **Decimal as a string** (`"8.40"`), never a float |
| Tenant scope | **Never** a path, query or body parameter on tenant routes (NR-NF-02) |
| Unknown request fields | `422` — silent acceptance hides client bugs |
| Correlation | `X-Request-Id` on every response; echoed as `error.reference` on failure |
| Actions | Colon suffix: `:activate`, `:rotate`, `:disable`, `:cancel`, `:rollback`, `:archive`, `:bulk-upsert`, `:status`, `:close`, `:accept`, `:confirm` |
| Async | `202` + a job or submission resource. Console polls at 2 s |

### 5.2 The two envelopes

```jsonc
// list
{ "items": [ … ],
  "pagination": { "limit": 25, "offset": 0, "total": 12, "has_more": false } }

// error — every failure, without exception
{ "error": {
    "class": "conflict",                    // validation·conflict·limit·unavailable·auth·not_found·internal
    "code":  "product_already_exists",      // stable machine-readable cause
    "reason": "a product with identifier SKU-4471 already exists",
    "reference": "err-3f81-7a20c",
    "field_errors": [ { "field": "external_product_id", "reason": "Already exists in this tenant." } ],
    "retryable": false,
    "retry_after_seconds": null } }
```

`class`, `reason` and `reference` are what the prototype's `/integration` page publishes to tenants and what the console renders. `code` and `field_errors` are additive. **Do not change the three published field names.**

| `class` | HTTP | Console behaviour |
|---|---|---|
| `validation` | 422, 413 | Inline field errors + banner |
| `conflict` | 409 | Banner; **form stays filled** |
| `limit` | 429 | Warn-toned banner **with the numbers** |
| `unavailable` | 503 | Status message |
| `auth` | 401, 403 | Gate redirect |
| `not_found` | 404 | `/404` — **never names the resource type** |
| `internal` | 500 | `/error` with the reference |

### 5.3 Authentication

Two **separate realms**. A tenant token on `/v1/platform/*` is `403`; a platform token on a tenant route is `403`. Check the realm before any handler runs.

| Realm | Table | Token carries | Login |
|---|---|---|---|
| Tenant | `tenant_users` | `tid`, `role` | `POST /v1/auth/login` |
| Platform | `platform_users` | `perms[]`, **no `tid`** | `POST /v1/platform/auth/login` |

**Claims:** `iss`, `sub`, `tid` (tenant realm only — **the only authoritative tenant source**), `realm`, `role`, `perms[]`, `scp[]`, `typ` (`user`\|`apikey`), `jti`, `iat`, `exp`. Ed25519. Public keys at `GET /v1/.well-known/jwks.json`.

**Refresh rotation:** every use issues a new refresh token and consumes the old. Presenting a consumed token **revokes the entire chain**.

**API credentials:** `gr_live_XXXX` prefix + secret. Stored **only** as `HMAC-SHA-256(pepper, secret)`. **Shown once, at creation and rotation, never retrievable again.** Rotation keeps `predecessor_hash` valid for a grace period.

### 5.4 Idempotency — business identifiers, not headers

The prototype's `/integration` page states it: **"External identifiers are the idempotency key."**

| Operation | Key | Repeat |
|---|---|---|
| `POST /v1/events` | `(tenant_id, event_id)` | `200 {"status":"duplicate_confirmed"}` — **a success, not an error** |
| `POST /v1/events/batches` | `(tenant_id, batch_id)` | Returns the original submission |
| `POST /v1/products:bulk-upsert` | `(tenant_id, sync_id)` | Returns the original submission |
| `POST /v1/products` | `(tenant_id, external_product_id)` | `409` — creation is deliberately not idempotent |
| `POST /v1/training-jobs` | `(tenant_id, request_ref)` | Returns the original job |
| `POST /v1/feedback/*` | `(tenant_id, event_id)` | `duplicate_confirmed` |
| `POST /v1/recommendations` | `request_id` | **Metering deduplication only — never a cached recommendation** |

An optional `Idempotency-Key` header (24 h TTL) covers operations without a natural business key.

---

## 6. The shared vocabulary — generate it, do not retype it

These enumerations appear in the prototype's `GROUPS`, `JOB_STAGES`, `SCOPES` and `PERMS` constants (`GraphRec Console.dc.html` L622–636). They are the badge vocabulary; **any value the backend emits outside these sets renders as an untoned badge**.

```
job (12)        queued · waiting_for_resources · preparing_data · building_graph ·
                training · evaluating · indexing_embeddings · registering ·
                cancelling · cancelled · failed · succeeded
JOB_STAGES (9, ordered — drives the stage rail)
                queued → waiting_for_resources → preparing_data → building_graph →
                training → evaluating → indexing_embeddings → registering → succeeded
model (7)       registered · eligible · active · retired · rejected · archived · failed_deployment
deploy (6)      stopped · pending · progressing · degraded · rolling_back · available
tenant (5)      pending · active · suspended · deleting · deleted
user (4)        invited · active · locked · disabled
outcome (4)     succeeded · failed · denied · cancelled
severity (4)    info · warning · error · critical
availability    in_stock · low_stock · out_of_stock
event_type      view · add_to_cart · purchase · remove_from_cart
submission kind product_sync · event_batch
submission status  processing · succeeded · failed
submission stages  received → validating → applying → completed
usage_type (6)  events · recommendations · training · products · storage · service_capacity
measurement     measured · delayed · unavailable
audit actor     tenant_user · tenant_application · system_process · platform_administrator
audit action    credential · training · activation · rollback · quota · tenant · access · security
failure area    serving · ingestion · training · activation · capacity
credential state (derived)  usable · expired · revoked
roles           tenant administrator · tenant developer
PERMS (5)       platform permission · plan-management permission ·
                authorized platform scope · monitoring access · audit permission
```

**Build `scripts/gen-enums.py` in Phase 1.** It parses `GraphRec Console.dc.html`, extracts these constants, and emits:
- `graphrec/common/enums.py` — Python enums
- `frontend/src/lib/enums.ts` — TypeScript unions and the badge-tone map
- A pytest fixture asserting the database enum types match

Run it in CI. **A drift between backend enums and the prototype's vocabulary must fail the build.** This is the single most likely regression in this project.

### Credential scopes — console label ↔ machine name

| Console label (`SCOPES`) | Machine name | Grants |
|---|---|---|
| catalog write & synchronization | `catalog:write` | `POST/PUT/PATCH /v1/products*`, `:bulk-upsert`, `:disable` |
| event submission (single and batch) | `events:write` | `POST /v1/events`, `/v1/events/batches` |
| recommendation requests | `recommendations:read` | `POST /v1/recommendations*` |
| recommendation feedback | `feedback:write` | `POST /v1/feedback/*` |
| submission result read | `submissions:read` | `GET /v1/submissions/{id}` |

`GET /v1/scopes` returns `[{name, label, description}]` so dialogs render the human labels while the wire carries stable machine names. **A credential can never hold a scope its creating role lacks.**

---

## 7. Database — the non-negotiable parts

Full schema: `BACKEND_PLAN.md §11` (27 tables with columns, constraints and indexes). Build it exactly. These are the parts that will break the system if you get them wrong.

### 7.1 Row-Level Security

```sql
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON products
  USING      (tenant_id = current_setting('app.tenant_id')::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

- **`FORCE` is mandatory, not decorative** — table owners bypass RLS otherwise.
- The application connects as `graphrec_app`, a **non-superuser, non-owner**. Migrations run as `graphrec_owner`. `alembic.ini` already configures the owner URL.
- Every request opens a transaction and issues `SET LOCAL app.tenant_id = …` **from the verified token claim, never from a request field**. `SET LOCAL` scopes to the transaction, so a pooled connection cannot leak context.
- **`WITH CHECK` matters as much as `USING`** — without it a tenant can *insert* a row bearing another tenant's id.
- **Platform sessions never set `app.tenant_id`.** They set `app.platform_scope = 'on'` and filter by tenant in the query. Tenant is a filter, never an ambient scope.

### 7.2 Constraints that enforce business rules at the schema level

Put these in the schema, not only in code. They are the last line of defence against a race.

| Constraint | Enforces |
|---|---|
| `UNIQUE (tenant_id, email)` on `tenant_users` | SRS §5.2.3 — duplicate email is a **conflict**, not a validation error |
| `UNIQUE (tenant_id, external_product_id)` on `products` | SRS §5.2.6 |
| `UNIQUE (tenant_id, external_event_id)` on `interaction_events` | **This is NR-NF-05** — one durable effect per event id |
| `UNIQUE (tenant_id, kind, external_ref)` on `submissions` | Sync/batch idempotency |
| **Partial `UNIQUE (tenant_id) WHERE state NOT IN (terminal)`** on `training_jobs` | At most one active training job per tenant |
| **Partial `UNIQUE (tenant_id) WHERE status='active'`** on `model_versions` | One active model version per tenant |
| **`UNIQUE (tenant_id)`** on `model_deployments` | SRS §5.2.11 — zero or one deployment per tenant |
| `UNIQUE (tenant_id, model_id, version_number)` on `model_versions` | Monotonic per-tenant version numbering |
| `UNIQUE (tenant_id, usage_period_start, usage_type)` on `monthly_usage_aggregates` | SRS §5.2.15 |
| `UNIQUE (request_id, rank_position)` and `UNIQUE (request_id, product_id)` on `recommendation_results` | A product appears once per request |
| Composite `(tenant_id, id)` foreign keys throughout | Cross-tenant references become **structurally impossible** |

### 7.3 Immutable ledgers

```sql
GRANT SELECT, INSERT         ON usage_events TO graphrec_app;  -- never UPDATE or DELETE
GRANT SELECT, INSERT         ON audit_logs   TO graphrec_app;  -- never UPDATE or DELETE
GRANT SELECT, INSERT, UPDATE ON api_keys     TO graphrec_app;  -- DELETE withheld
```

Write a test that asserts `UPDATE` and `DELETE` on `usage_events` and `audit_logs` raise. `api_keys` rows are retained and marked `revoked_at`, never deleted, so audit history cannot be purged.

### 7.4 Indexes that matter on the hot path

| Index | For |
|---|---|
| Partial `(status, job_type, run_after) WHERE status IN ('queued','running')` on `jobs` | The claim query — stays tiny regardless of history size |
| Partial `(tenant_id) WHERE is_active AND availability <> 'out_of_stock'` on `products` | The eligibility filter, read on every recommendation |
| `(tenant_id, customer_id, occurred_at DESC)` on `interaction_events` | Sequence retrieval for training and serving |
| BRIN `(tenant_id, occurred_at)` on `interaction_events` | Snapshot cutoff scans |

**Do not partition `interaction_events` initially.** Correct RLS, constraints and indexes matter more, and partitioning complicates uniqueness and retention. Add monthly range partitioning only when a load test demonstrates a need.

---

## 8. The five authorization gates

This model is the spine of both the backend and the console. `FRONTEND_BUILD_PROMPT.md §4` and the prototype both specify it. **Evaluate in this exact order.**

| # | Gate | Blocks on | Console result | Backend result |
|---|---|---|---|---|
| 1 | **Identity** | No session; user status `invited`/`locked`/`disabled` | → `/login` | `401 auth/unauthenticated` |
| 2 | **Tenant state** | Tenant status ≠ `active` | → `/account/tenant-status`, navigation suppressed | `403 auth/tenant_not_active` on everything **except** `/v1/auth/*` and `GET /v1/tenant` |
| 3 | **Role / permission** | Role or named permission not held | `/403`, terminal, no retry | `403 auth/insufficient_role` \| `insufficient_permission` |
| 4 | **Ownership** | Resource belongs to another tenant | **`/404`, never `/403`** | RLS returns zero rows → `404 not_found` |
| 5 | **Resource state** | Lifecycle forbids the action | Control **disabled in place** with an inline reason. **No navigation** | `409` if attempted anyway |

**Three rules that are easy to get wrong:**

1. **Gate 4 must run before gate 5.** If eligibility were checked first, probing with another tenant's version id would return *"not eligible"* instead of *"not found"* — leaking that the resource exists. Write `test_gate4_precedes_gate5` explicitly.
2. **A foreign resource is indistinguishable from a missing one.** `/404` never names the resource type. A `403` would confirm existence, which is itself a cross-tenant leak.
3. **Gate 5 must be *published*, not computed.** The prototype computes `eligibility()`, `canActivate`, `canRollback`, `canArchive` and `isLast` client-side from the whole mock store. A real client cannot. **Every read response must carry its own preconditions:**

```jsonc
// GET /v1/model-versions/{id} — excerpt
"actions": {
  "activate": { "allowed": false, "reason": "This version is already active." },
  "rollback": { "allowed": true,  "reason": null },
  "archive":  { "allowed": false, "reason": "An active version cannot be archived." } }
```

The reason strings are the prototype's, verbatim. Same pattern on credentials (`can_rotate`, `can_revoke`, `blocked_reason`), training jobs (`can_cancel`), products (`can_disable`), users (`is_last_active_administrator`), and a dedicated `GET /v1/training-jobs/eligibility` for the Start-training button.

### Role capability matrix

The two tenant roles are **near-disjoint** — they share only sign-in and credentials. This is intentional and comes from the use-case diagrams.

| Capability | Tenant Admin | Tenant Dev |
|---|:--:|:--:|
| Sign in, own account | ● | ● |
| Credential management | ● | ● |
| Tenant user management | ● | ○ |
| Catalog write (add/update/disable/sync) | ○ | ● |
| Event submission | ○ | ● |
| Submission result read | ○ | ● |
| Training request & cancellation | ● | ○ |
| Model version read & lifecycle | ● | ○ |
| Usage, quota, model and service status | ● | ○ |
| Tenant audit read | ● | ○ |

**The Tenant Administrator having no catalog access is deliberate.** `/products` as an administrator → `403`.

### Platform permissions

Five **independently grantable** permissions, not one blanket role:

| Permission | Grants | Routes |
|---|---|---|
| `platform permission` | Tenant accounts and status transitions | `/admin/tenants`, `/admin/tenants/:tenantId` |
| `plan-management permission` | Plan limits, tenant assignment, quota overrides | `/admin/plans*`, plan section on tenant detail |
| `authorized platform scope` | Cross-tenant usage summaries | `/admin/usage`, usage section on tenant detail |
| `monitoring access` | Shared health, workload, capacity, failures | `/admin/status` |
| `audit permission` | Redacted failures and audit history | `/admin/audit` |

**`/admin/tenants/:tenantId` composes three permissions.** The route is gated on `platform permission`; the plan and usage *sections* are gated separately. A holder of only `platform permission` gets `200` with those sections marked withheld — **not a whole-route `403`**:

```jsonc
{ "tenant": { … },
  "sections": {
    "status": { "granted": true,  "data": { … } },
    "plan":   { "granted": false, "reason": "This section requires the plan-management permission." },
    "usage":  { "granted": false, "reason": "This section requires the authorized platform scope." } } }
```

`/admin` redirects to the first permitted route, driven by `GET /v1/platform/auth/me`.

---

## 9. Business rules to enforce server-side

The prototype enforces these client-side. **Every one must be enforced by the backend**, because the console is a convenience, not an authority.

| Rule | Behaviour | Source |
|---|---|---|
| Duplicate email in a tenant | **`409`**, not `422` — *"Email is unique per tenant, so this is a conflict rather than a validation error"* | `dc.html` L1235; SRS §5.2.3 |
| Duplicate business name at registration | `409` — *"A tenant account named 'X' already exists…"*; **form stays filled** | L1582 |
| Last active administrator | **Cannot be demoted or disabled.** `409 last_active_administrator`. Enforce inside the transaction with `SELECT … FOR UPDATE` on the active-admin count — two concurrent demotions would both pass a naive check | L1243–1244 |
| Global training concurrency | **1, platform-wide.** *"Job job-2292 is already running. Global training concurrency is 1."* Backed by the partial unique index | L1646; ASM-03 |
| Training data floor | ≥ 1,000 eligible interaction sequences, else `422` — *"Dataset snapshot held fewer than 1,000 eligible interaction sequences."* | L697 |
| Training cooldown | 15 minutes between requests (**confirm — see §2**) | L1666 |
| Training request identifier | **Required.** *"A request identifier is required so a repeated request is not applied twice."* | L1681 |
| Activation eligibility | Only a version with `status = eligible` may be activated. `409` otherwise | L1746 |
| Failed activation | **The previous version keeps serving.** New version → `failed_deployment`; `deployment_revisions` records why. Load and verify the bundle **before** any pointer swap | L704; ER-F-06 |
| Rollback | Requires a `retired` target and a **reason**. Target validated **before** the active version changes | L1747, L1792; ER-F-07 |
| Archive protection | Allowed for `registered`/`rejected`/`retired` — **except the retired version immediately preceding the active one**, which is *"Retained as the rollback target for the active version."* | L1748–1749 |
| Product sync bound | 5,000 products. `413` — *"A synchronization is bounded to 5,000 products. Split the collection and submit it in parts."* | L1357, L1612 |
| Event batch bound | 5,000 events. `413` — *"A batch is bounded to 5,000 events. Split the collection and submit it in parts."* | L1370, L1627 |
| Duplicate event | **Success**, `{"status":"duplicate_confirmed"}`. Not an error | L1175, L1375; NR-NF-05, ER-F-04 |
| Credential scopes | ≥ 1 required — *"A credential with no scope cannot authorize anything."* | L1137 |
| Revoked credential | Cannot be rotated or revoked again. `409` | L1118 |
| Active credential cap | `MAX_ACTIVE_API_KEYS_PER_TENANT=25` → `429` | `.env` |
| Closed plan | Keeps assigned tenants, accepts no new ones — *"Plan SCALE is closed to new assignments. Reopen the plan or choose another."* Re-assigning to the same plan is allowed | L1454 |
| Negative plan limits | `422` — *"A negative limit conflicts with the quota model. Enter zero to withhold a usage type entirely."* | L1635; SRS §5.2.1 |
| Product quota | `429` **naming the numbers** — *"This tenant holds 50,000 of 50,000 products on plan GROWTH."* Response carries `{used, limit, plan_code}` | L1603 |
| Reason required (≥ 4 chars) | Disable product · cancel training · roll back · change tenant status | L1342, L1717, L1792, L1420 |
| Unavailable measurement | Reported as a **status**, never as a zero. `measurement_status ∈ measured\|delayed\|unavailable` | L715, L1824; UC-30 |
| Sign-in failure | **Identical response whether the email exists or not** — *"The credentials supplied are not valid, or the account cannot sign in."* | L1572 |
| Product eligibility | **Derived, never stored**: `eligible = active AND availability <> 'out_of_stock' AND deleted_at IS NULL`. Reasons: *"Out of stock — excluded from serving"* / *"Inactive — excluded from serving"* | L683, L686 |
| Quota checks | **Inside the creating transaction, before acceptance.** Rejecting at dequeue wastes the queue delay and confuses a user who already saw a `202` | ER-F-09 |
| Recommendation response | **`model_version` and `strategy` in every response**, without exception | ER-F-05 |
| Recommendation ordering | **Deterministic** for identical model, catalog, context and policy. Stable sort, ties broken by product id, versioned `ordering_policy` in the bundle | ER-NF-06, XR-NF-02 |
| Retry policy | **Transient failures only** (network, storage timeout, GPU busy, OOM). Deterministic failures (schema, insufficient data, quota) go straight to `failed` **without consuming attempts** | ER-NF-05 |

### The error copy catalogue

The prototype contains ~40 finished user-facing strings. **Treat them as approved product copy and return them as `error.reason`.** Do not paraphrase.

Build `graphrec/common/error_copy.py` as a single catalogue keyed by `error.code`, and add a contract test asserting the catalogue contains the strings at the line numbers cited above. The console imports the same catalogue for any client-side pre-validation, so the two can never disagree.

---

## 10. The React console

36 routes, 4 layout shells, 3 realms. `docs/FRONTEND_BUILD_PROMPT.md` is the full design brief — read §5, §7, §10, §11, §12 before starting. What follows is the part specific to wiring it to a real backend.

### 10.1 Build it from the prototype, not from scratch

`Design system decision pending/GraphRec Console.dc.html` contains one `pg_<routeId>` function per route returning a declarative page descriptor: `{crumbs, kicker, title, badge, subtitle, actions, stats, filters, table, dl, panels, rail, form, footnote}`. `Design system decision pending/ROUTES.md` §"For the React build" states the mapping: routes become nested React Router routes, the four layouts become layout routes, gates 1–3 belong in layout loaders, gate 4 in each detail route's loader, gate 5 in the page component.

**Port each `pg_*` function to a route component of the same shape**, replacing `this.state.store` reads with TanStack Query hooks. The declarative descriptor is a good design — keep it. What changes is where the data comes from and that gate-5 preconditions arrive from the server instead of being computed locally.

### 10.2 Route tree

```
PublicLayout          /register  /login  /recover  /recover/confirm  /invite/accept  /admin/login
StateGateLayout       /account/tenant-status
TenantLayout          /home  /credentials  /integration  /account                 [Admin · Dev]
                      /users  /users/:userId  /audit                             [Admin]
                      /training  /training/:jobId  /models  /models/:versionId
                      /usage  /service-status                                     [Admin]
                      /products  /products/new  /products/sync  /products/:productId
                      /events/submit  /submissions/:submissionId                  [Dev]
PlatformLayout        /admin/tenants  /admin/tenants/:tenantId
                      /admin/plans  /admin/plans/:planId
                      /admin/usage  /admin/status  /admin/audit
Errors                /403  /404  /error
Redirects             /  →  /home | /admin | /login   (by identity)
                      /admin  →  first permitted platform route
                      /products as Admin  →  /403
```

### 10.3 The API layer

```
frontend/src/api/
├── types.gen.ts      generated from openapi.json — never hand-edited
├── client.ts         fetch wrapper: base URL, auth header, error envelope parsing,
│                     X-Request-Id capture, 401 → refresh → retry once
├── errors.ts         ApiError class carrying {class, code, reason, reference, field_errors}
└── hooks/            one file per domain — useProducts, useTrainingJobs, useModelVersions, …
```

**Generate `types.gen.ts` from the backend's OpenAPI.** Add `scripts/gen-client.sh` and run it in CI; a drift between the backend schema and the frontend types must fail the build.

**The client must:**
- Attach `Authorization: Bearer <access token>` from the in-memory token store.
- On `401 token_expired`, call `/v1/auth/refresh` **once**, retry, and on a second failure clear the session and redirect to `/login`.
- Parse the error envelope into a typed `ApiError` — never surface a raw response.
- Capture `X-Request-Id` and attach it to `ApiError.reference` so `/error` can display it.
- Never send a tenant identifier. Ever. (NR-NF-02)

**Token storage:** access token in memory only; refresh token in an httpOnly cookie if the deployment allows, otherwise `sessionStorage` with a documented trade-off. **Never `localStorage`.**

### 10.4 Guards — gates 1–4 as loaders

```ts
// guards/tenantGuard.ts — runs in TenantLayout's loader
export async function tenantGuard({ request }) {
  const session = await requireSession();                 // gate 1 → redirect /login
  const tenant  = await queryClient.fetchQuery(tenantQuery);
  if (tenant.status !== 'active')                          // gate 2
    throw redirect('/account/tenant-status');
  return { session, tenant };
}

// guards/roleGuard.ts — per route
export function roleGuard(allowed: Role[]) { … }           // gate 3 → /403

// gate 4 lives in each detail route's loader: a 404 from the API throws to the
// error boundary, which renders /404 WITHOUT naming the resource type.
```

**Gate 5 is not a guard.** It renders a disabled control with the server-supplied reason as a tooltip or inline note, and never navigates.

### 10.5 Components

Build these 19 primitives, per `FRONTEND_BUILD_PROMPT.md §11`:

`Button · Input · Select · Textarea · Table · Badge · Dialog · Banner · Skeleton · EmptyState · Breadcrumbs · Sidebar · StatCard · Tabs · Pagination · FilterBar · CopyField · StageRail · DefinitionList`

`Badge` takes an enum group and a value and looks up the tone from the generated `enums.ts` map — never a hard-coded colour per value.

### 10.6 Dialogs, never routes

Per `Design system decision pending/ROUTES.md`: one-time credential secret (**shown once, not re-openable**) · create/rotate/revoke credential · disable product (reason required) · start training · cancel training (reason required) · activate/roll back (reason required)/archive version · invite user · change role · resend invitation · lock/unlock/disable/re-enable user · tenant status change (reason required) · assign plan · approve quota override · close plan.

### 10.7 Design system — currently undecided

The prototype is bound to a "Modernist" design system (`Design system decision pending/_ds/…/styles.css`) with semantic state colours (`--ok / --warn / --danger / --info / --neu`) defined alongside it. `FRONTEND_BUILD_PROMPT.md §11` specifies a different Claude palette.

**The folder is literally named `Design system decision pending`.** Do not resolve this yourself. Build against **CSS custom properties only** — every colour, radius, spacing and font goes through a token in `styles/tokens.css`. Swapping design systems must then be a single-file change. Ask which system to use before Phase 14; until then use the Modernist tokens the prototype already renders with, so screenshots stay comparable.

Both light and dark themes must be fully token-defined.

### 10.8 Polling

The prototype polls at 2.2 s (`setInterval(() => this.advance(), 2200)`). Use TanStack Query `refetchInterval`:

| Route | Interval | Stop when |
|---|---|---|
| `/training/:jobId` | 2 s | Job reaches a terminal state |
| `/submissions/:submissionId` | 2 s | Submission reaches `succeeded` or `failed` |
| `/service-status` | 15 s | Never (it is a live board) |
| `/admin/status` | 15 s | Never |

**Preserve scroll position and expanded state across refetches** — the prototype says so explicitly: *"This view updates in place; your position is preserved."*

### 10.9 The seven backend endpoints that exist only for the console

The prototype computes these from its whole mock store. A real client cannot, so the backend must provide them. **These are easy to forget and the console is broken without them.**

| Endpoint | Replaces | Serves |
|---|---|---|
| `GET /v1/onboarding` | `hasProducts`/`hasEvents`/`okJob`/`act` computed at L1088 | `/home` launcher + the 10-step §3.5 checklist |
| `GET /v1/training-jobs/eligibility` | `eligibility()` L1643 | The Start-training button's enabled state **and its reason** |
| `GET /v1/model-versions/summary` | `c(k)` counts L1725 | The five stat cards on `/models` |
| `actions` block on `GET /v1/model-versions/{id}` | `canActivate`/`canRollback`/`canArchive` L1746–1749 | Activate / Roll back / Archive enablement |
| `is_last_active_administrator` on user reads | `isLast` L1243 | Change-role and Disable enablement |
| Server-derived credential `state` | `expires < today` computed at L1107 | The Authorizes column — server time is authoritative |
| Server-derived `eligible` + `ineligible_reason` on products | L683, L686 | The Serving column |

Plus `pagination.total` on every list, because every table renders `"N of M"`.

### 10.10 Frontend tests

Per `FRONTEND_BUILD_PROMPT.md §14`, using Vitest + RTL + MSW:

- **Each guard's allow and deny path** — all five gates.
- **The gate-4 → `/404` behaviour**, asserting the page never names the resource type.
- **One full workflow per role:** Admin (request training → watch stages → review quality → activate), Developer (add product → sync catalog → submit events → read submission), Platform (list tenants → open a partially-permitted tenant detail → confirm sections are withheld, not the route).
- **Enum parity:** assert `enums.ts` matches the generated source.
- Every interactive element keyboard-reachable with a visible focus state; dialogs trap focus.

---

## 11. Build order

Fourteen phases. Each is independently testable. **Do not reorder.** Full detail per phase: `BACKEND_PLAN.md §21`.

### Phase 1 — Foundation
Repo layout · Pydantic Settings covering the **full** config surface (`BACKEND_PLAN.md §22.4`) · structured logging with `request_id` · the error envelope and copy catalogue · `scripts/gen-enums.py` · Compose (Postgres, Redis, object store, API, `migrate`) · Alembic wired to the existing `alembic.ini` · both database roles · CI (ruff, mypy, pytest, migration up **and down**) · `/healthz`, `/readyz`.
**Confirm D7 (per-endpoint body limits) before finishing this phase.**
**Done when:** `docker compose up` gives a healthy stack, CI is green, and `gen-enums` output matches the prototype.

### Phase 2 — Identity, tenancy, RLS ← the hard prerequisite
🛑 **CONFIRM D1, D5, D6, D11, D12 before starting.**
Migration: tenants, tenant_users, platform_users + permissions, invitations, refresh_sessions, recovery_tokens, pricing_plans, tenant_subscriptions, tenant_resource_quotas, quota_overrides · **RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK` on every tenant table** · `tenant_context.py` · Ed25519 keypair + JWKS · Argon2id · `deps.py` implementing gates 1–4 **in order** · endpoints `POST /v1/tenants`, `/v1/auth/*`, `/v1/platform/auth/*`, `/v1/invitations:accept`, `GET /v1/tenant`, `/v1/me`, `/v1/users*` · last-active-administrator under a row lock · seed the three plans.
**Done when:** the **isolation suite** and the **authorization matrix** pass and are wired as required CI gates; a foreign resource returns `404`; a platform token cannot reach a tenant route and vice versa.

### Phase 3 — Credentials
`api_keys` + `scopes` · HMAC generation and verification with versioned pepper · create/list/describe/rotate-with-grace/revoke · scope enforcement in `deps.py` · scope-delegation refusal · `GET /v1/scopes`.
**Done when:** the secret is returned exactly once, a rotated key's predecessor still verifies during grace, and cross-tenant access is blocked.

### Phase 4 — Job system
🛑 **CONFIRM D2 (Postgres queue) before starting.**
`jobs` table with the partial claim index · claim query with `FOR UPDATE SKIP LOCKED` and fair-share ordering · lease, heartbeat, expiry sweeper · retry classifier · cooperative cancellation at stage boundaries · `job_worker` claim loop.
**Done when:** two workers claim disjoint jobs; a killed worker's job requeues automatically; a deterministic failure consumes no attempts.

### Phase 5 — Catalog
🛑 **CONFIRM D9 (POST + PUT + PATCH) and D10 (pagination) before starting.**
`products`, `product_categories` with the partial eligibility index · **the shared eligibility predicate — one function, called by both the API and the serving path** · `POST` (409 on duplicate), `PUT`, `PATCH`, `GET`, `:disable` (reason required) · product-count quota with the counts in the message.
**Done when:** `/products*` endpoints are complete and the eligibility function returns identical results from both call sites.

### Phase 6 — Ingestion
`customers`, `interaction_events`, `submissions`, `submission_errors` · `POST /v1/events` with `duplicate_confirmed` · `POST /v1/events/batches` and `POST /v1/products:bulk-upsert` → `202` + submission + job · worker handlers: streaming, bounded-memory validation, staging then a single merge transaction, capped error samples · **unified `GET /v1/submissions/{id}`** plus the `/events/batches/{id}` alias.
**Done when:** the same `event_id` twice yields one row and two successes; an oversize batch returns `413`; a partial failure keeps the accepted remainder.

### Phase 7 — Metering
`usage_events` (INSERT-only grant), `monthly_usage_aggregates` · Redis fast counters + durable ledger + reconciliation rollup · effective-limit resolution (plan, then active override) · `GET /v1/usage`, `/trends`, `/subscription` **with `measurement_status`** · quota checks inside creating transactions.
**Done when:** `UPDATE` on `usage_events` raises, and a delayed measurement renders as a status rather than a zero.

### Phase 8 — DGSR offline ← parallelisable from Phase 1
`FeatureBuilder` · graph construction + bounded 2-hop sampling · DGSR: GNN pathway, sequence pathway, gated fusion · training loop, negative sampling, BPR, checkpointing · **temporal leave-last-out split** · Recall@10 / HR@10 / NDCG@10 / coverage · popularity baseline · fixture dataset with a deterministic seed.
**Done when:** metrics beat the popularity baseline on the fixture and the leakage test passes.
> Run this **offline-first**, before wiring it to jobs and storage. Debugging a model and a distributed job system simultaneously is how ML projects stall.

### Phase 9 — Training jobs
`models`, `training_jobs`, `dataset_snapshots`, `training_metrics` · **the partial unique index for one active job per tenant** · `training_worker` implementing the nine stages, writing `progress` and `stage_index` at each · `POST /v1/training-jobs` with all four admission checks at enqueue · `GET /v1/training-jobs/eligibility` · `GET /v1/training-jobs/{id}` with the stage-rail contract · `:cancel` with a required reason · `GET /v1/datasets/snapshots/{id}`.
**Done when:** two concurrent training requests yield one job and one `409`; a crash mid-training resumes from the last checkpoint; `stage_index` survives failure and cancellation.

### Phase 10 — Model registry
🛑 **CONFIRM D4 (in-process index) and D8 (7-value lifecycle) before starting.**
`model_versions`, `model_evaluation_metrics` · **partial unique for one active version** · bundle export in safetensors with a manifest carrying `tenant_id` and a digest · `CandidateIndex` port + in-process adapter; the `indexing_embeddings` stage builds and uploads it · registration sets `registered`, then `eligible` or `rejected` against the metric floor · `GET /v1/model-versions`, `/summary`, `/{id}` with the **three-way comparison** and the `actions` block · `:archive` with rollback-target protection.
**Done when:** a corrupted bundle is refused at load and a foreign-tenant manifest is refused.

### Phase 11 — Serving
🛑 **CONFIRM D3 (Compose vs k3s) before starting.**
`model_deployments`, `deployment_revisions`, `serving_replicas`, `model_activation_history` · `ServingDriver` port + Compose adapter · `reconciler` with a leader lock, desired→actual convergence, replica reporting, `ready ≥ 1` floor · `inference` pinned by `GRAPHREC_TENANT_ID`, local Ed25519 verification, bundle load with manifest and digest verification · the four-stage funnel with deterministic ordering and a versioned policy · fallback lanes · `:activate` and `:rollback` with **load-before-swap** and previous-version retention · `POST /v1/recommendations`, `/session`, `/feedback/*` · `GET /v1/deployment*`, `/metrics/summary`, `/service-status/errors`.
**Done when:** a failed activation leaves the previous version serving; **P95 < 300 ms under load (NR-NF-04)**; `ready ≥ 1` holds for every active tenant.

### Phase 12 — Audit and platform
`audit_logs`, `security_events` with append-only grants · audit writes on every ER-F-11 action · `GET /v1/audit-logs` tenant-scoped and redacted · platform permission dependency · all 13 `/v1/platform/*` endpoints including the **three-section composed tenant detail** · `GET /v1/platform/status` with `measurement_gaps`.
**Done when:** tenant audit never reveals another tenant, and a partially-permitted platform user sees withheld sections rather than a `403`.

### Phase 13 — Console: foundations
🛑 **CONFIRM the design system (§10.7) before starting.**
Vite + TS scaffold · `tokens.css` and both themes · the 19 primitives · `enums.ts` from `gen-enums` · `types.gen.ts` from OpenAPI · the API client with refresh-and-retry · token store · the four layout shells · gates 1–4 as loaders · error boundaries rendering `/403`, `/404`, `/error` · public routes (`/register`, `/login`, `/recover*`, `/invite/accept`, `/admin/login`) · `/account/tenant-status`.
**Done when:** a user can register, sign in, and be correctly gated — against the real backend.

### Phase 14 — Console: tenant routes
`/home` (from `GET /v1/onboarding`) · `/credentials` with the one-time secret modal · `/integration` · `/account` · `/users*` · `/products*` · `/events/submit` · `/submissions/:id` with live polling · `/training*` with the nine-stage rail · `/models*` with the three-way comparison · `/usage` · `/service-status` · `/audit`.
**Done when:** all 30 tenant routes render real data and every gate-5 control is disabled from the server's `actions`/`can_*` fields with the server's reason.

### Phase 15 — Console: platform routes and end-to-end
All 8 `/admin/*` routes including the composed tenant detail · sidebar filtered by held permissions · `/admin` → first permitted route · the three per-role workflow tests · full a11y pass.
**Done when:** **all 36 routes are backed by real endpoints** and the three workflow tests pass against a live stack.

### Phase 16 — Hardening and deployment
Per-node Compose + systemd (+ k3s profile if D3 selected it) · CI/CD with ordered deploys (N1 migrations first → N3 inference → N2 trainer) and smoke tests between · firewall, private networking, secret management · backups + **a rehearsed restore drill** · dashboards and alerts · publish OpenAPI and verify it matches the `/integration` page · runbooks · failure drills, load test, security scan · walk the `BACKEND_PLAN.md §24` checklist.

### Dependency graph

```
1 Foundation
└─ 2 Identity+Tenancy+RLS ──┬─ 3 Credentials ── 5 Catalog ──┐
                            └─ 4 Job system ────────────────┼─ 6 Ingestion ─ 7 Metering
1 ─ 8 DGSR offline ─────────────────────────────────────────┘        │
                                            4,6,8 ─ 9 Training jobs ─┘
                                                    9 ─ 10 Registry ─ 11 Serving
                                                              2–11 ─ 12 Audit+Platform
                                    2,12 ─ 13 Console foundations ─ 14 ─ 15 ─ 16 Hardening
```

**Phase 8 runs in parallel with 3–7** — it depends only on Phase 1 and touches no database. On a small team that parallelism is the difference between a comfortable schedule and a tight one. **Phase 13 can start as soon as Phase 2 ships**, against the partial API.

---

## 12. Testing requirements

| Layer | Scope | Gate |
|---|---|---|
| Unit | Eligibility predicate · last-admin rule · archive protection · quota arithmetic · retry classifier · graph construction · ranking metrics | Every PR |
| Integration | Repositories · job claim/lease/retry · storage client · migrations up **and down** | Every PR |
| API | Every endpoint: happy path, each error class, envelope shape, pagination, preconditions | Every PR |
| **Authorization matrix** | **Every (role × endpoint) and (permission × endpoint) pair**, allow and deny | Every PR |
| **Isolation** | Cross-tenant access, exhaustively | **Required merge gate** |
| Database | RLS policies · `FORCE` · constraints · partial uniques · immutable-ledger grants | Every PR |
| Contract | Enum parity · route coverage · error-copy parity · OpenAPI ↔ `types.gen.ts` | Every PR |
| ML | End-to-end on a fixture, deterministic seed · metric floors · **no temporal leakage** | Nightly |
| Inference | Latency budget · cold load · each fallback lane · determinism | Nightly |
| Frontend | Guard allow/deny · gate-4 → `/404` · one workflow per role · a11y | Every PR |
| Load | Sustained target RPS, **P95 < 300 ms** | Pre-release |
| Failure drills | Kill Postgres / Redis / storage mid-flight · expire a lease · corrupt a bundle | Pre-release |

### The isolation suite — write this in Phase 2 and never let it go red

```python
@pytest.mark.isolation
class TestTenantIsolation:
    def test_foreign_resource_returns_404_not_403(self, tenant_a, tenant_b_version): ...
    def test_rls_blocks_raw_query_without_context(self, db, tenant_b_product): ...
    def test_rls_with_check_blocks_foreign_insert(self, db): ...
    def test_cannot_cancel_foreign_training_job(self, ...): ...
    def test_cannot_activate_foreign_model_version(self, ...): ...
    def test_presigned_url_scoped_to_own_prefix(self, ...): ...
    def test_recommendations_never_return_foreign_products(self, ...): ...
    def test_inference_refuses_bundle_with_mismatched_tenant(self, ...): ...
    def test_redis_keys_are_tenant_prefixed(self, ...): ...
    def test_platform_token_cannot_reach_tenant_routes(self, ...): ...
    def test_tenant_token_cannot_reach_platform_routes(self, ...): ...
    def test_gate4_precedes_gate5(self, tenant_a, tenant_b_ineligible_version):
        """Foreign AND ineligible must yield 404, never 409 'not eligible'."""
    def test_usage_events_reject_update_and_delete(self, db): ...
    def test_audit_logs_reject_update_and_delete(self, db): ...
```

**Enforce coverage mechanically:** a CI check compares the set of tables carrying `tenant_id` against the tables referenced by isolation tests. **A new tenant-owned table without a matching isolation test fails the build.**

### Contract tests against the prototype

Because the prototype is the specification, automate three checks:

1. **Enum parity** — extract `GROUPS`, `JOB_STAGES`, `SCOPES`, `PERMS` from the `.dc.html` and assert the backend enums and `enums.ts` contain exactly those values.
2. **Route coverage** — extract the 36 `ROUTES` entries and assert each maps to an implemented frontend route **and** at least one backend endpoint.
3. **Error-copy parity** — assert the catalogue contains the prototype's approved strings.

---

## 13. Hard constraints

1. **Tenant identity comes only from the verified credential.** Never from a path, query or body parameter. No `/t/:tenantId/…` shape anywhere. (NR-NF-02)
2. **No tenant identifier in any tenant route path** — frontend or backend. Only `/admin/tenants/:tenantId` names a tenant, under platform scope.
3. **Foreign resource → `404`, never `403`.** `/404` never names the resource type.
4. **Gate 4 runs before gate 5**, always, with a test proving it.
5. **RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK`** on every tenant-owned table. Runtime role is non-owner, non-superuser.
6. **`usage_events` and `audit_logs` get no `UPDATE`/`DELETE` grant. `api_keys` gets no `DELETE`.**
7. **The credential secret is returned exactly twice in a key's life** — at creation and at rotation — and is never retrievable afterwards.
8. **Guards are real route guards, not hidden buttons.** The backend is the authority; the frontend enforces the same rules so the UI never offers an action that will be rejected.
9. **Gate 5 disables controls in place with a server-supplied reason. It never navigates.**
10. **Every destructive action gets a confirmation dialog**; those specified with a reason require one (≥ 4 characters).
11. **A duplicate event, batch, sync, training request or feedback submission is a success**, not an error. (NR-NF-05, ER-F-04)
12. **A failed activation never interrupts serving.** Load and verify before swapping. (ER-F-06)
13. **An unavailable measurement is reported as a status, never as a zero.** (UC-30)
14. **`model_version` and `strategy` appear in every recommendation response.** (ER-F-05)
15. **Recommendation ordering is deterministic** for identical inputs. (ER-NF-06)
16. **Quota is checked inside the creating transaction, before acceptance.** (ER-F-09)
17. **No `pickle` anywhere in the ingest path or across the worker→inference boundary.** safetensors only.
18. **No secrets, raw event payloads, passwords, tokens or foreign tenant identifiers in any log line or error body.** (NR-NF-06)
19. **Never `localStorage` for tokens.**
20. **Every colour, spacing and font in the console goes through a CSS custom property.** The design system is undecided.
21. **Both light and dark themes fully token-defined.** Every interactive element keyboard-reachable with a visible focus state; dialogs trap focus.
22. **Every user-facing bound is a named setting**, never a literal in code — 5,000 products, 5,000 events, 1,000 sequences, 15-minute cooldown, embedding dim 128, and every rate limit.

---

## 14. Do NOT build

From `FRONTEND_BUILD_PROMPT.md §9` and `Design system decision pending/ROUTES.md`:

**No console UI for:** recommendation requests, results or feedback (server-to-server only — their only trace is the fallback rate and recent errors on `/service-status`) · **the customer entity, anywhere** · snapshot construction, graph building, DGSR training internals, bundle export or index building beyond stage names · candidate retrieval, eligibility filtering, scoring, re-ranking · idempotency and duplicate detection beyond *"duplicate confirmed"* · retry policy or dead-letter handling · audit record *writing* · a submission index route.

**Nothing from SRS §1.3 Out of Scope:** real payment processing, multi-region operation, unlimited tenant scaling, enterprise disaster recovery, enterprise-grade HA, arbitrary tenant-supplied model code. **So: no billing, no invoicing, no plan checkout, no region selector.** Plans are assigned by a Platform Administrator (UC-28) and appear read-only to tenants.

**No commercial-PaaS conventions without an SRS hook:** webhooks, sandbox vs production environments, SDK downloads, a live API playground, per-request recommendation debugging, latency dashboards beyond the specified ones, alerting UI, MFA/SSO, active-session management, support desk, public status page, data export.

**No tenant-side plan selection.** §2.1's Business Owner is a stakeholder, not an actor.

---

## 15. Reporting

At the end of **every phase**, produce a short report:

1. **What was built** — modules, endpoints, tables, routes.
2. **What was verified** — which tests were added and which gates now pass.
3. **What was not done, and why** — omissions, shortcuts, TODOs left in place. Be specific.
4. **Decisions taken** — anything you resolved that this prompt left open. Record each as an ADR in `docs/adr/`.
5. **New conflicts found** — if a source document contradicts another and this prompt does not cover it, **stop and ask**. Do not guess.

At the CONFIRM gates, **halt and ask explicitly**, naming the decision, the recommendation and what changes if it is overridden.

### Keep the documents current

When a decision changes, update `BACKEND_PLAN.md` and this prompt in the same commit as the code. An architecture document that has drifted from the code is worse than none, because people trust it.

---

## 16. Definition of done for the whole system

- All 36 console routes render real data from real endpoints, with all five gates enforced on both sides.
- A tenant can complete the SRS §3.5 user story end to end: register → configure users → create a credential → synchronize a catalog → submit events → request training → review quality → activate a version → serve recommendations → monitor usage and status.
- A Platform Administrator can complete UC-27 through UC-31, with per-permission gating including the composed tenant detail.
- A tenant application can complete the machine-facing loop: sync catalog → submit events → request recommendations → submit feedback.
- The isolation suite and authorization matrix pass and are required merge gates.
- P95 recommendation latency < 300 ms under demonstration load (NR-NF-04).
- A failed activation demonstrably leaves the previous version serving (ER-F-06).
- Backups run and a restore drill has been executed and verified.
- OpenAPI is published and matches what the `/integration` page documents.
- Every item in `BACKEND_PLAN.md §24` is checked.
- The four SRS defects in `BACKEND_PLAN.md §7.2` have been reported to the supervisor.

---

## Appendix — Start here

```
1. Read BACKEND_PLAN.md end to end.
2. Open "Design system decision pending/GraphRec Console.dc.html".
   Read L620-660 (constants, routes) and L662-751 (the seed store) closely.
   Skim the pg_* functions; read pg_integration (L1163-1193) carefully —
   it is the API contract the console already documents to tenants.
3. Read docs/FRONTEND_BUILD_PROMPT.md §2b, §4, §5, §7, §9, §11.
4. Skim the SRS: §3.1-3.3 (requirement tables), §4.5 (UC-01…UC-31), §5.2 (entities).
5. Ask the D1 question. Do not write code until it is answered.
6. Then Phase 1.
```

**If you take one thing from this prompt:** the prototype is not a mockup to be approximated. It is a specification whose every enum value, disabled-button reason and error string is a requirement. Build the backend so the console works without changing a single one of them.
