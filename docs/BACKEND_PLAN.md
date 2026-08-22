# GraphRec — Backend Architecture & Implementation Plan

**Status:** Analysis and architecture of record. No implementation started.
**Basis:** `SYSTEM_DESIGN.md`, `API.md`, `ROUTES.md`, `docs/GraphRec_Ultimate_Architecture.md`, `docs/PROJECT_OVERVIEW.md`, `docs/FRONTEND_BUILD_PROMPT.md`, `docs/BSSE1415_SPL3_mid.docx` (the SRS), `Design system decision pending/GraphRec Console.dc.html` (the frontend prototype), `.env`, `.env.example`, `alembic.ini`.

**Evidence labels used throughout this document:**

| Mark | Meaning |
|---|---|
| **[C]** | **Confirmed** — traced to a named file, section or line in this workspace |
| **[I]** | **Inferred** — follows necessarily from confirmed material, but is not written anywhere |
| **[R]** | **Recommended** — my design choice; alternatives existed and are named |
| **[!]** | **Conflict or gap** — two sources disagree, or a required decision has no source |

---

## 1. Executive Summary

GraphRec is a multi-tenant recommendation platform-as-a-service. Independent e-commerce businesses ("tenants") register, provision users and API credentials, synchronize a product catalog, stream customer-interaction events, request tenant-specific DGSR model training, review model quality, activate or roll back a model version, and consume real-time Top-N recommendations server-to-server. **[C — SRS §1.1, §2]**

Three findings dominate this analysis and drive every recommendation below.

**Finding 1 — There is no code in this workspace. Not backend, not frontend.**
`git log` reports *"your current branch 'main' does not have any commits yet"*; every file is untracked. `alembic.ini` exists and points at `script_location = migrations`, but no `migrations/` directory exists. `.env` and `.env.example` carry settings (`JWT_SIGNING_SECRET`, `API_KEY_HMAC_PEPPER`, `MAX_ACTIVE_API_KEYS_PER_TENANT`) that only make sense against a running application. `docs/PROJECT_OVERVIEW.md` describes `apps/api/`, `graphrec_core/`, eight Alembic migrations and "57 tests" — **none of which are present**. `docs/FRONTEND_BUILD_PROMPT.md §2b` explains why: its endpoint table is *"Paths recovered from a prior implementation of this system."* **[C]**

The practical consequence: `PROJECT_OVERVIEW.md` is a record of a deleted or relocated prior build, not a description of this workspace. It must be read as historical evidence of API shape, not as current state. **[I]**

**Finding 2 — The "existing frontend" is a single-file design prototype, not a React application.**
`Design system decision pending/GraphRec Console.dc.html` is 1,860 lines: a hash router (`#/home`, `#/models/v-7`), 36 addressable routes, 4 layout shells, a five-gate authorization model, ~30 `pg_<routeId>` page functions, and an in-memory `seed()` store. `support.js` is the generated design-canvas runtime (`// GENERATED from dc-runtime/src/*.ts`), not application code. There is **no API client, no fetch call, no network layer anywhere**. `Design system decision pending/ROUTES.md` states it plainly: *"every screen runs without a server."* **[C]**

So "preserve compatibility with the existing frontend" cannot mean "match an existing HTTP client." It means something more specific and more useful: **the prototype is an executable specification of the console's routes, roles, gates, state enumerations, action preconditions and data shapes, and the backend must satisfy all of them.** That is the contract this plan honours. **[I]**

**Finding 3 — Three architecture documents in this workspace describe three mutually incompatible systems.**

| Document | Resource model | Queue | Orchestration | Token | Field naming |
|---|---|---|---|---|---|
| `API.md` | AWS Personalize (dataset groups, solutions, campaigns) | — | 2 hosts | EdDSA | `camelCase` |
| `SYSTEM_DESIGN.md` | AWS Personalize | Postgres `SKIP LOCKED` | Compose + systemd, 3 VPS | EdDSA | `camelCase` |
| `GraphRec_Ultimate_Architecture.md` | SRS-native (products, events, training jobs, model versions, deployments) | RabbitMQ + Celery + outbox | k3s + per-tenant Deployment + HPA | not specified | `snake_case` |
| `PROJECT_OVERVIEW.md` | SRS-native | RabbitMQ + Celery | Kubernetes | HS256 | `snake_case` |
| **The frontend prototype** | **SRS-native** | — | shows replica counts | — | **`snake_case`** |

The frontend and the SRS speak one vocabulary; `API.md` and `SYSTEM_DESIGN.md` speak another. **`API.md` has no "products", no "events", no "training jobs", no "model versions", no "usage types", no "plans", no "tenant users", no "submissions" — none of the nouns the console is built from.** It cannot serve this frontend. **[C, !]**

**The core recommendation of this plan:** adopt the **SRS-native resource model** as the API contract, because it is the only one that the existing frontend, the SRS use cases and the ER model all agree on; adopt **`SYSTEM_DESIGN.md`'s operational simplifications** (Postgres-as-queue, Compose-first, no separate vector service for MVP) because they materially reduce what a small team must operate and nothing in the SRS requires the heavier alternatives; and keep **`GraphRec_Ultimate_Architecture.md`'s per-tenant serving and autoscaling shape**, because `XR-F-08` and the frontend's `/service-status` and `/admin/status` screens require desired-vs-ready replica counts that no other design produces. Section 8 argues this in full. `API.md` is treated as a **rejected alternative that should be retired or explicitly rescoped**; Section 7 raises it as the single largest open question. **[R, !]**

**Shape of the recommended backend:** a Python 3.12 / FastAPI **modular monolith control plane**, a **CPU job worker**, a **GPU training worker**, a **deployment reconciler**, and a **per-tenant inference process** — five deployable units over one PostgreSQL (shared schema, `tenant_id`, forced RLS), one Redis, and one S3-compatible object store. Roughly 27 database tables, ~70 HTTP endpoints, 13 delivery phases.

---

## 2. Workspace / File Analysis

### 2.1 Complete inventory

| Path | Size | What it actually is | Authority for |
|---|---:|---|---|
| `docs/BSSE1415_SPL3_mid.docx` | 4.8 MB | **The SRS.** Actors, NR/ER/XR requirements, UC-01–UC-31, activity diagrams, 16 logical entities (§5.2), Qdrant contract (§6.3) | **Requirements. Highest authority.** |
| `Design system decision pending/GraphRec Console.dc.html` | 162 KB | **The frontend.** Hash-routed prototype, 36 routes, 5 gates, `seed()` mock store | **Console behaviour, enums, data shapes.** |
| `Design system decision pending/ROUTES.md` | 7.4 KB | Prototype route/role/gate map, notes for the React build | Gate semantics, dialog inventory |
| `ROUTES.md` (root) | 15 KB | Route tree with SRS traceability tiers (†/‡), *"Beyond the SRS"* defect analysis | **SRS gap analysis. Read this first.** |
| `docs/FRONTEND_BUILD_PROMPT.md` | 40 KB | Build brief for the React app; **§2b endpoint table recovered from a prior implementation** | **Endpoint paths and naming.** |
| `docs/GraphRec_Ultimate_Architecture.md` | 153 KB | Full architecture: ER diagram (§23), 27-table design (§24), DDL (§25), RLS (§26), API spec (§27), quotas (§20), 12-week plan (§36) | **Data model, quotas, RLS.** |
| `SYSTEM_DESIGN.md` | 100 KB | 3-VPS architecture of record; 50 sections; ADRs with rejected alternatives | **Operational design, trade-off rationale.** |
| `API.md` | 43 KB | AWS Personalize–shaped API reference | **Conflicting.** See §7. |
| `docs/PROJECT_OVERVIEW.md` | 21 KB | Describes a prior implementation not present here | Historical API shape only |
| `docs/Dynamic_Graph_Neural_Networks_for_Sequential_Recommendation.pdf` | 1.3 MB | The DGSR source paper | Model design |
| `diagrams/` | 13 files | 7 activity + 6 use-case diagrams (`.drawio` + PNG) | Flow confirmation |
| `alembic.ini` | 621 B | Alembic config; `script_location = migrations`, owner-role URL | Migration tooling **[C]** |
| `.env` / `.env.example` | 1.2 / 1.3 KB | Runtime settings; `.env.example` adds Qdrant block | Config surface **[C]** |
| `.dockerignore` | 57 B | Excludes `.git .env .venv __pycache__ *.pyc frontend docs diagrams` | **Implies `frontend/` was a sibling directory [I]** |
| `.gitignore` | 1.8 KB | Python/Node/OS/IDE ignores | — |
| `.claude/settings.local.json` | 72 B | `{"permissions":{"allow":["Bash(python3 *)"]}}` | — |
| `Design system decision pending/_ds/modernist-…/` | 5 files | Bound "Modernist" design system: `styles.css`, `_ds_manifest.json`, `_adherence.oxlintrc.json` | Visual tokens (frontend only) |
| `.git/` | — | **Initialized, zero commits, nothing staged** | **[C]** |

### 2.2 What is present that implies a prior build

- `alembic.ini` with `sqlalchemy.url = postgresql+psycopg://graphrec_owner:local@localhost:5432/graphrec` — a **separate owner role** for migrations, distinct from the runtime role. This is the RLS-bypass separation `SYSTEM_DESIGN.md §15` requires. **[C]**
- `.dockerignore` excluding `frontend` — a `frontend/` directory once sat beside the backend at repo root. **[C, I]**
- `.env` keys naming concrete features that no document invents: `API_KEY_HASH_VERSION`, `MAX_API_KEY_GRACE_SECONDS=86400`, `MAX_ACTIVE_API_KEYS_PER_TENANT=25`, `AUDIT_HASH_SECRET`. These are implementation fingerprints. **[C]**
- `.env.example` (newer than `.env` by mtime) adds `QDRANT_URL`, `QDRANT_COLLECTION_PREFIX`, `QDRANT_EMBEDDING_DIM=128`, `QDRANT_TOP_K=100` — a vector store was being introduced. `QDRANT_EMBEDDING_DIM=128` matches the frontend's `/models/:versionId` panel, which displays `Embedding dimension 128`. **[C]**

### 2.3 TODOs, placeholders and mock data found

| Location | Placeholder |
|---|---|
| `GraphRec Console.dc.html` `seed()` L662–751 | **Entire application state is mock**: 1 tenant, 4 users, 5 credentials, 8 products, 3 submissions, 4 jobs, 7 model versions, 6 usage rows, 1 deployment, 4 tenants, 3 plans, 12 audit rows, 5 failures |
| `GraphRec Console.dc.html` L773 | `setInterval(()=>this.advance(),2200)` — a **simulated poller** that walks `job-2292` through `JOB_STAGES` |
| `pg_productNew` footnote | *"Try identifier SKU-4471 for a conflict, or QUOTA to see the quota rejection banner"* |
| `pg_productSync` / `pg_events` footnotes | *"Paste … the word OVERSIZE, to see the rejection path"*, *"Enter event identifier ev-33810 to see duplicate confirmation"* |
| `pg_integration` L1168 | Hardcoded base URL `https://api.graphrec.example` |
| Folder name | `Design system decision pending` — the design system is **not final** |
| `ROUTES.md` §"Left unresolved" | Customer data lifecycle **flagged rather than designed** |
| `PROJECT_OVERVIEW.md` §14 | Seven unchecked roadmap boxes: Celery, RustFS, DGSR training, bundle export, K8s controller, inference funnel, feedback loop |

Every one of these is a place where the frontend fakes a backend response. **Each is a backend endpoint that must exist.**

---

## 3. Existing Frontend Analysis

### 3.1 Architecture

Hash router. `ROUTES` is a flat array of `[pattern, routeId, layout, access]`; `match(path)` does segment-wise matching with `:param` capture; `resolve(path, ctx)` runs gates 1–4 before any page function executes; each route renders through one `pg_<routeId>(params, me)` function returning a declarative page descriptor (`crumbs, kicker, title, badge, subtitle, actions, stats, filters, table, dl, panels, rail, form, footnote`) that a shared renderer draws. **[C — L638–659, L789–830, L1011]**

`Design system decision pending/ROUTES.md` §"For the React build" states these map 1:1 onto nested React Router routes, with gates 1–3 in layout loaders, gate 4 in detail-route loaders, gate 5 in page components. **[C]**

### 3.2 The five authorization gates — the load-bearing contract

| # | Gate | Blocks on | Result | Backend obligation |
|---|---|---|---|---|
| 1 | Identity | No session; user status `invited`/`locked`/`disabled` | → `/login` | `401`; only `active` users authenticate |
| 2 | Tenant state | Tenant status ≠ `active` | → `/account/tenant-status`, nav suppressed | `403 tenant_not_active` on every endpoint except auth + `GET /v1/tenant` |
| 3 | Role / permission | Role or named permission not held | `/403`, terminal | `403 insufficient_role` / `insufficient_permission` |
| 4 | Ownership | Resource belongs to another tenant | **`/404`, never `/403`** | RLS returns zero rows → `404` |
| 5 | Resource state | Lifecycle forbids the action | Control disabled **in place** + inline reason, no navigation | `409` if attempted anyway; **a preconditions endpoint so the UI can disable correctly** |

`FRONTEND_BUILD_PROMPT.md §4` and root `ROUTES.md` both stress: **gate 4 must run before gate 5**, or probing with a foreign version id returns *"not eligible"* instead of *"not found"*, leaking existence. **[C]**

Gate 5 is the one with a non-obvious backend cost. The prototype computes `eligibility()`, `canActivate`, `canRollback`, `canArchive`, `isLast` (last active administrator) and `lastAdmin` **client-side from the full store**. A real client cannot. Section 12 therefore specifies **preconditions in every read response** (`can_activate`, `blocked_reason`, …) so the UI disables controls with a stated reason without a second round trip. **[I, R]**

### 3.3 Route inventory — 36 routes, 4 layouts, 3 redirects

**Public — `PublicLayout`:** `/register`, `/login`, `/recover`, `/recover/confirm`, `/invite/accept` †, `/admin/login` †
**Gate-2 — `StateGateLayout`:** `/account/tenant-status`
**Tenant shared — `TenantLayout` (Admin · Dev):** `/home`, `/credentials`, `/integration` ‡, `/account` ‡
**Tenant — Administrator only:** `/users` †, `/users/:userId` †, `/audit` ‡, `/training`, `/training/:jobId`, `/models`, `/models/:versionId`, `/usage`, `/service-status`
**Tenant — Developer only:** `/products`, `/products/new`, `/products/sync`, `/products/:productId`, `/events/submit`, `/submissions/:submissionId`
**Platform — `PlatformLayout`:** `/admin/tenants`, `/admin/tenants/:tenantId`, `/admin/plans`, `/admin/plans/:planId`, `/admin/usage`, `/admin/status`, `/admin/audit`
**Errors:** `/403`, `/404`, `/error`
**Redirects:** `/` → `/home` | `/admin` | `/login`; `/admin` → first permitted platform route; `/products` as Admin → `/403`

† = required beyond the SRS · ‡ = platform completeness. **[C — root `ROUTES.md`, `dc.html` L638–659]**

**The two tenant roles barely overlap.** They share only sign-in and credentials. The Tenant Administrator has **no** catalog or event access; the Tenant Developer has **no** training, model, usage or service access. `FRONTEND_BUILD_PROMPT.md §4` calls this *"intentional and comes straight from the use-case diagrams."* **[C]**

### 3.4 Enumerations the backend must reproduce exactly

Read from `GROUPS`, `JOB_STAGES`, `SCOPES`, `PERMS` at `dc.html` L622–636. **These are the frontend's badge vocabulary; any value the backend emits outside these sets renders as an untoned `neu` badge.** **[C]**

```
job (12):     queued · waiting_for_resources · preparing_data · building_graph ·
              training · evaluating · indexing_embeddings · registering ·
              cancelling · cancelled · failed · succeeded
JOB_STAGES(9, ordered, drives the stage rail):
              queued → waiting_for_resources → preparing_data → building_graph →
              training → evaluating → indexing_embeddings → registering → succeeded
model (7):    registered · eligible · active · retired · rejected · archived · failed_deployment
deploy (6):   stopped · pending · progressing · degraded · rolling_back · available
tenant (5):   pending · active · suspended · deleting · deleted
user (4):     invited · active · locked · disabled
outcome (4):  succeeded · failed · denied · cancelled
sev (4):      info · warning · error · critical
availability (product): in_stock · low_stock · out_of_stock
event_type:   view · add_to_cart · purchase · remove_from_cart
submission kind: "product sync" · "event batch"
submission status: processing · succeeded · failed
usage_type (6): events · recommendations · training · products · storage · service_capacity
usage measurement: measured · "measurement delayed"
audit actor:  tenant_user · tenant_application · system_process · platform_administrator
audit action: credential · training · activation · rollback · quota · tenant · access · security
failure area: serving · ingestion · training · activation · capacity
credential state (derived): usable · expired · revoked
PERMS (5):    platform permission · plan-management permission ·
              authorized platform scope · monitoring access · audit permission
SCOPES (5):   catalog write & synchronization · event submission (single and batch) ·
              recommendation requests · recommendation feedback · submission result read
```

**Note `indexing_embeddings` as a distinct training stage.** It is the only surface trace of a vector-index build step, and it aligns with SRS §6.3's Qdrant contract and `.env.example`'s `QDRANT_*` block. See §7 Q4. **[C, I]**

### 3.5 Data shapes the frontend renders

From `seed()`, L662–751. Field names below are the **prototype's** names; §12 maps each to the API field name.

| Entity | Prototype fields |
|---|---|
| tenant | `code, name, status, plan, created` |
| user | `id, name, email, role, status, created, last` |
| credential | `id, name, prefix, scopes[], expires, revoked, created, last` |
| product | `id (external), title, cat, brand, price, active, avail, updated, eligible, why` |
| submission | `id, kind, status, received, accepted, updated, skipped, failed, at, ref, errors[{ref, reason}]` |
| training job | `id, state, type, requested, completed, by, reason, version, stageAt, progress` |
| model version | `id, n, type, status, created, job, recall, hr, ndcg, cov, digest, snap, eligible, failNote` |
| usage row | `type, qty, limit, rem, reset, status` |
| deployment | `state, version, desired, ready, transition, errors, fallback, latency` |
| plan | `id, name, events, recs, training, products, storage, open, tenants[]` |
| audit | `at, actor, action, res, outcome, ref, tenant` |
| failure | `at, sev, area, ref, summary, tenant` |

**`product.eligible` and `product.why` are derived, not stored** — the prototype sets `why` to `"Out of stock — excluded from serving"` or `"Inactive — excluded from serving"`. The backend must compute and return both. **[C, I]**

**`model_version.n` is a per-tenant sequential integer** (`v-1` … `v-7`, rendered as `v7`), separate from the opaque `id`. **[C]**

**`job.stageAt` persists the stage index at which a failed or cancelled job stopped** — the rail renders `'Stopped at '+JOB_STAGES[j.stageAt]`. The backend must store the terminal stage, not just the terminal status. **[C — L1707]**

### 3.6 The API contract the frontend already documents

The `/integration` page (`pg_integration`, L1163–1193) is not decoration — it is a **literal, in-product API reference with request and response bodies**. Everything it prints is binding. **[C]**

```jsonc
// POST /v1/products:bulk-upsert
{ "sync_id": "req-9d21",
  "products": [ { "external_id": "SKU-4471", "title": "Brass hinge, 75mm",
                  "category": "Hardware", "brand": "Northgate", "price": "8.40",
                  "active": true, "availability": "in_stock" } ] }
// 202 Accepted
{ "submission_id": "sub-8841", "status": "processing",
  "counts": { "accepted": 0, "updated": 0, "skipped": 0, "failed": 0 } }

// POST /v1/events
{ "event_id": "ev-33810", "customer_id": "cus-9931",
  "external_product_id": "SKU-6002", "event_type": "purchase",
  "occurred_at": "2026-08-14T09:41:02Z", "value": "129.00",
  "context": { "surface": "product_page" } }
// 200 OK · duplicate confirmed
{ "event_id": "ev-33810", "status": "duplicate_confirmed" }

// POST /v1/events/batches
{ "batch_id": "batch-4471", "events": [ /* bounded collection */ ] }

// GET /v1/events/batches/{batch_id}
{ "submission_id": "sub-9002", "kind": "event_batch", "status": "processing",
  "counts": { "received": 5000, "accepted": 4870, "skipped": 118, "failed": 12 },
  "errors": [ { "ref": "ev-33810", "reason": "occurred_at is in the future" } ] }

// POST /v1/recommendations
{ "customer_id": "cus-9931", "session_id": "ses-2211",
  "top_n": 10, "context": { "surface": "cart" } }

// POST /v1/feedback/impressions
{ "request_id": "rec-77120",
  "impressions": [ { "external_product_id": "SKU-6002", "position": 1 } ] }

// Error body — every failure
{ "error": { "class": "conflict",
             "reason": "a product with identifier SKU-4471 already exists",
             "reference": "err-3f81-7a20c" } }
```

Plus, rendered as a definition list: base URL, `Authorization: Bearer <credential secret>`, `Content-Type: application/json`, and **`Idempotency: External identifiers are the idempotency key`** — not a header, the business identifier itself. **[C — L1168]**

And an error vocabulary table:

| Class | HTTP | Meaning |
|---|---|---|
| `validation` | 422 | Supplied information cannot be accepted |
| `conflict` | 409 | State or uniqueness prevents the operation |
| `limit` | 429 | A plan or quota limit is exhausted |
| `unavailable` | 503 | Serving is degraded; a fallback may apply |

**Naming is `snake_case` throughout.** **[C]**

### 3.7 Endpoint inventory recovered from the prior implementation

`FRONTEND_BUILD_PROMPT.md §2b`, described as *"authoritative for shape and naming"*: **[C]**

| Endpoint | Frontend route |
|---|---|
| `POST /login` · `POST /setup-password` | `/login` · `/invite/accept` † |
| `GET/POST /api-keys` · `GET/DELETE /api-keys/{id}` · `POST /api-keys/{id}/rotate` | `/credentials` |
| `GET /v1/products` · `GET/PUT/PATCH /v1/products/{external_id}` | `/products` · `/products/:productId` |
| `POST /v1/products:bulk-upsert` | `/products/sync` |
| `POST /v1/products/{external_id}:disable` | Disable dialog |
| `POST /v1/events` · `POST /v1/events/batches` | `/events/submit` |
| `GET /v1/events/batches` · `GET /v1/events/batches/{batch_id}` | `/submissions/:submissionId` |
| `POST /v1/training-jobs` · `GET /v1/training-jobs` | `/training` |
| `GET /v1/model-versions` · `GET /v1/model-versions/{version_id}` | `/models` · `/models/:versionId` |
| `POST /v1/model-versions/{version_id}:activate` | Activate dialog |
| `POST /v1/models/{model_id}:rollback` | Roll-back dialog |
| `POST /v1/model-versions/{version_id}:archive` | Archive dialog |
| `GET /v1/datasets/snapshots/{snapshot_id}` | Snapshot panel on `/training/:jobId` |
| `GET /v1/deployment` · `/replicas` · `/autoscaling` · `/v1/metrics/summary` | `/service-status` |
| `GET /usage` · `GET /subscription` | `/usage` |
| `GET /tenants` · `GET /tenants/{id}` · `POST /tenants/{id}/status` | `/admin/tenants*` |
| `GET /plans` · `POST /tenants/{id}/quotas` | `/admin/plans*` · tenant detail |
| `GET /status` · `GET /failures` · `GET /audit` | `/admin/status` · `/admin/audit` |
| `POST /v1/recommendations` · `/session` · `/v1/feedback/*` | **none — server-to-server only** |

The same section names the **gaps it knows about**: `GET /v1/training-jobs/{job_id}` and `:cancel`; a unified submission read covering product syncs; tenant user CRUD and invitation; platform authentication with a permission-bearing identity; tenant-scoped audit read. **[C]**

**Note the versioning inconsistency in this recovered inventory: `POST /login`, `GET /api-keys`, `GET /tenants`, `GET /plans`, `GET /status`, `GET /failures`, `GET /audit` carry no `/v1` prefix while everything else does.** See §7 Q6. **[C, !]**

### 3.8 What the frontend deliberately does not do

`FRONTEND_BUILD_PROMPT.md §9` and `Design system decision pending/ROUTES.md` §"Not built, deliberately": no UI for recommendation requests, results or feedback; **no customer entity anywhere**; no snapshot/graph/training internals beyond stage names; no idempotency, autoscaling, retry or audit-writing surfaces; no submission index route. **[C]**

**This is a boundary, not an omission.** The recommendation and feedback path is entirely machine-facing, which frees it from console constraints and lets it live on a separate process — the basis for the control-plane / data-plane split in §8.

---

## 4. Requirements Summary

### 4.1 Actors

| Actor | Human | Uses console | Authenticates with |
|---|---|---|---|
| Tenant Administrator | Yes | Yes | Email + password → access token |
| Tenant Developer | Yes | Yes | Email + password → access token |
| Platform Administrator | Yes | Yes, **separate realm** | Email + password → platform token |
| Tenant E-Commerce Application | No | **No** | API credential secret |
| E-Commerce Customer | Yes | **No** — never contacts GraphRec | — |

**[C — SRS §2.2 Table 4, `FRONTEND_BUILD_PROMPT.md §3`]**

### 4.2 Functional requirements (SRS Tables 5, 7, 9)

**Normal (NR-F-01 … NR-F-16):** register tenant + initial administrator; authenticate with role-appropriate access; create/rotate/inspect/revoke API credentials; add/update/list/disable products; bounded product synchronization with accepted and rejected counts; single and batch event submission with a tenant-local event identifier; request tenant-specific training; display training state/progress/failure/result; display model versions with status, creation time and quality summary; activate an eligible version; roll back to an allowed historical version; Top-N recommendation for an identified customer; recommendation from anonymous session context; impression/click/conversion feedback; display usage, plan limits, remaining quota where calculable and reset period; display active-model and service status.

**Expected (ER-F-01 … ER-F-12):** every training dataset from one tenant's validated data only; tenant-specific DGSR parameters and artifacts; evaluation by next-item accuracy, ranking quality, coverage and diversity; duplicate detection by idempotency identifier for products, events, training and feedback; **return serving model version and strategy with each recommendation**; **previously active model stays available when activation fails**; rollback targets validated before the active version changes; record accepted events, recommendation requests, training activity, stored products and artifact usage; enforce plan and tenant limits **before** accepting bounded operations; tenant-safe fallback when personalization is unavailable and fallback is permitted; audit history for credential changes, activation, rollback, quota changes and administrative actions; expose model/training/recommendation/usage/service status according to authorization.

**Exciting (XR-F-01 … XR-F-10):** blend recent session events with persistent history; scheduled periodic retraining; event-count-triggered retraining eligibility; bounded diversity/category/brand/freshness/seasonality ordering rules; rollback to an eligible retained version; plan-based limits for events, recommendations, training, retained versions and serving capacity; usage trends by period and type; **adjust serving capacity within configured limits when measured demand changes**; cold-start via popularity/category/content/session; **compare a new version against baseline and active-version quality before activation**.

**[C]**

### 4.3 Non-functional requirements

| ID | Requirement | Verifiable as |
|---|---|---|
| NR-NF-01 | No tenant reads or changes another tenant's resources | Isolation test suite, CI gate |
| NR-NF-02 | Tenant identity from authenticated credentials, never a public request field | No `tenant_id` in any tenant path or body |
| NR-NF-03 | Clear success, validation, conflict, limit, unavailability responses | Error-class contract (§17) |
| NR-NF-04 | **P95 recommendation < 300 ms** at demonstration load | Load test |
| NR-NF-05 | Repeated submission of the same tenant event identifier has **one durable effect** | `UNIQUE (tenant_id, external_event_id)` |
| NR-NF-06 | Traceable error reference, no credentials or foreign tenant data | `error.reference` on every failure |
| NR-NF-07 | Straightforward server-to-server integration with documented requests/responses | `/integration` page + OpenAPI |
| NR-NF-08 | At least one ready recommendation capability per active tenant | Deployment reconciler + `ready ≥ 1` |
| ER-NF-01 | Accepted async work survives via durable state and controlled reprocessing | Job table + lease recovery |
| ER-NF-02 | Tenant ownership enforced consistently across identities, data, models, recommendations, usage | Composite `(tenant_id, id)` FKs |
| ER-NF-03 | Model identity, version, integrity, compatibility validated before ready | Manifest + digest verification |
| ER-NF-04 | Terminal failure reasons recorded and visible to authorized users | `failure_reason` sanitized |
| ER-NF-05 | Retry transient failures only, bounded; never retry deterministic invalid requests | Retry classifier |
| ER-NF-06 | **Stable ordering** for identical model, catalog, context and policy | Deterministic tie-break by product id |
| ER-NF-07 | One tenant's workload cannot consume unbounded shared capacity | Quotas + fair-share dispatch |
| ER-NF-08 | Modular design separating administration, long-running processing, training, serving, data, monitoring | Module boundaries (§10) |
| ER-NF-09 | Metrics and status sufficient to explain request/training/model/capacity/quota outcomes | Observability (§18) |
| XR-NF-01 | Capacity adjustment preserves tenant and active-version consistency | Reconciler invariants |
| XR-NF-02 | Diversity and freshness adjustments bounded and **versioned** | `ordering_policy` version in bundle |
| XR-NF-03 | Scheduled/triggered retraining obeys cooldown, quota, one-active-training | Admission checks |

**[C]**

### 4.4 Constraints and assumptions

| ID | Statement | Architectural consequence |
|---|---|---|
| CON-01 | DGSR remains the primary learned approach | One model family; popularity baseline is a floor, not a peer |
| CON-02 | Shared logical data model with tenant ownership and enforced tenant access control | Shared schema + `tenant_id` + RLS |
| CON-03 | **At most three small processing nodes** | No orchestrator control plane worth its overhead; no HA |
| CON-04 | Recommendations synchronous; preparation and training separate | `202` + job resource for all long work |
| CON-05 | Limited-capacity educational system, **not production-ready HA** | State it; do not paper over it |
| ASM-01 | Starts with 2 tenants, **max 4 simultaneously active** | Per-tenant serving processes are affordable |
| ASM-02 | Educational-scale catalogs and event volumes | In-process retrieval viable |
| ASM-03 | **One resource-intensive training job at a time across the platform** | Global training concurrency = 1 |
| ASM-04 | Every active tenant retains ≥ 1 ready service instance | Warm replica minimum |
| ASM-05 | Quality evaluated offline; clicks and conversions are informational and **never auto-activate** | No online learning loop |

**[C]**

### 4.5 Business rules extracted from the frontend

Rules the SRS implies but only the prototype states operationally:

| Rule | Source |
|---|---|
| `(tenant_id, email)` unique → duplicate email is a **conflict**, not a validation error | `dlgInvite` L1235; SRS §5.2.3 |
| **The last active administrator cannot be demoted or disabled** | `pg_user` L1243; root `ROUTES.md` — *"Derived safety rule, not in the SRS"* **[!]** |
| Global training concurrency 1; *"Job X is already running"* | `eligibility()` L1646; ASM-03 |
| **15-minute cooldown between training requests** | `pg_training` stats L1666 — a stat card. Not in the SRS. **[!]** |
| Training requires ≥ 1,000 eligible interaction sequences | `job-2288` failure reason L697 **[C]** |
| Only an `eligible` version may be activated | `canActivate` L1746 |
| Rollback requires a `retired` target and a reason | `canRollback`, `dlgRollback` L1747, L1792 |
| Archive allowed for `registered`/`rejected`/`retired`, **except the immediately-preceding retired version**, which is *"Retained as the rollback target for the active version"* | `canArchive` L1748–1749 **[C]** |
| Product sync bounded to 5,000 products; event batch bounded to 5,000 events | L1357, L1370, L1612, L1627 |
| Revoked credentials cannot be rotated or revoked again | L1118–1119 |
| Credential must carry ≥ 1 scope — *"A credential with no scope cannot authorize anything"* | L1137 |
| A **closed plan** keeps assigned tenants but accepts no new assignments | `dlgAssignPlan` L1454 |
| Plan limits **cannot be negative**; zero withholds a usage type entirely | `submit` L1634–1635 |
| Reason **required** (≥ 4 chars) for: disable product, cancel training, roll back, change tenant status | L1342, L1717, L1792, L1420 |
| An unavailable measurement is reported as a status, **never as a zero** | `pg_usage` footnote L1824; `pg_pStatus` gap panel |
| Product quota rejection names the numbers: *"50,000 of 50,000 products on plan GROWTH"* | L1603 |

---

## 5. Functional Requirements → Backend Mapping

| SRS req | Console route(s) | Backend module | Primary endpoint(s) | Entities |
|---|---|---|---|---|
| NR-F-01 | `/register` | tenancy | `POST /v1/tenants` | tenants, tenant_users, tenant_subscriptions |
| NR-F-02 | `/login`, `/admin/login` † | identity | `POST /v1/auth/login`, `POST /v1/platform/auth/login` | tenant_users, platform_users, refresh_sessions |
| — (UC-03) | `/recover`, `/recover/confirm` | identity | `POST /v1/auth/recovery`, `…:confirm` | recovery_tokens |
| — (gap †) | `/invite/accept` | identity | `POST /v1/invitations:accept` | invitations, tenant_users |
| NR-F-03 | `/credentials` | credentials | `GET/POST /v1/api-keys`, `…/{id}`, `…:rotate`, `DELETE` | api_keys |
| NR-F-04 | `/products`, `/products/new`, `/products/:id` | catalog | `GET/POST /v1/products`, `GET/PATCH /v1/products/{eid}`, `…:disable` | products, product_categories |
| NR-F-05 | `/products/sync` | catalog + ingestion | `POST /v1/products:bulk-upsert` | submissions, submission_errors |
| NR-F-06 | `/events/submit` | ingestion | `POST /v1/events`, `POST /v1/events/batches` | interaction_events, submissions, customers |
| — (UC-11) | `/submissions/:id` | ingestion | `GET /v1/submissions/{id}` | submissions, submission_errors |
| NR-F-07 | `/training` | training | `POST /v1/training-jobs`, `GET …/eligibility` | training_jobs, jobs |
| NR-F-08 | `/training/:jobId` | training | `GET /v1/training-jobs/{id}` | training_jobs, jobs, dataset_snapshots |
| — (UC-14) | cancel dialog | training | `POST /v1/training-jobs/{id}:cancel` | training_jobs, jobs, audit_logs |
| NR-F-09 | `/models` | registry | `GET /v1/model-versions`, `…/summary` | model_versions |
| — (UC-17, XR-F-10) | `/models/:versionId` | registry | `GET /v1/model-versions/{id}` | model_versions, model_evaluation_metrics |
| NR-F-10 / ER-F-06 | activate dialog | serving | `POST /v1/model-versions/{id}:activate` | model_deployments, deployment_revisions, activation_history |
| NR-F-11 / ER-F-07 | rollback dialog | serving | `POST /v1/models/{id}:rollback` | model_deployments, activation_history |
| — (UC-20) | archive dialog | registry | `POST /v1/model-versions/{id}:archive` | model_versions |
| NR-F-12 / XR-F-01 | **none** | inference | `POST /v1/recommendations` | recommendation_requests, recommendation_results |
| NR-F-13 / XR-F-09 | **none** | inference | `POST /v1/recommendations/session` | recommendation_requests |
| NR-F-14 | **none** | feedback | `POST /v1/feedback/{impressions,clicks,conversions}` | recommendation_impressions, recommendation_feedback |
| NR-F-15 / XR-F-07 | `/usage` | metering | `GET /v1/usage`, `GET /v1/usage/trends`, `GET /v1/subscription` | usage_events, monthly_usage_aggregates, quotas |
| NR-F-16 / UC-26 | `/service-status` | serving | `GET /v1/deployment`, `…/replicas`, `…/autoscaling`, `GET /v1/metrics/summary` | model_deployments, serving_replicas |
| ER-F-11 | `/audit` ‡ | audit | `GET /v1/audit-logs` | audit_logs |
| UC-27 | `/admin/tenants*` | platform | `GET /v1/platform/tenants`, `…/{id}`, `…:status` | tenants, audit_logs |
| UC-28 / XR-F-06 | `/admin/plans*` | platform | `GET/POST /v1/platform/plans`, `PATCH`, `…:close`, `POST …/quota-overrides` | pricing_plans, quota_overrides |
| UC-29 | `/admin/usage` | platform | `GET /v1/platform/usage` | monthly_usage_aggregates |
| UC-30 | `/admin/status` | platform | `GET /v1/platform/status` | serving_replicas, jobs, metrics |
| UC-31 | `/admin/audit` | platform | `GET /v1/platform/audit-logs`, `GET /v1/platform/failures` | audit_logs, security_events |
| — (‡) | `/account` | identity | `GET/PATCH /v1/me`, `POST /v1/me/password` | tenant_users |
| — (‡) | `/integration` | credentials | `GET /v1/api-keys?state=usable`, `GET /v1/scopes` | api_keys |
| §3.5 checklist | `/home` | tenancy | `GET /v1/onboarding` | products, submissions, training_jobs, model_deployments |
| Gate 2 | `/account/tenant-status` | tenancy | `GET /v1/tenant` | tenants |

**Every one of the 36 routes is covered.** The rows with no SRS id are the four `†` gaps and three `‡` completions that root `ROUTES.md` argues for; §7 treats them as SRS defects that the backend must nonetheless resolve. **[C, I]**

---

## 6. Non-Functional Requirements — Design Response

| Concern | Target | Mechanism |
|---|---|---|
| **Recommendation latency** | P95 < 300 ms (NR-NF-04); internal budget < 150 ms | Warm per-tenant process; resident embeddings; local token verification; async post-response work |
| **Tenant isolation** | Absolute (NR-NF-01/02, ER-NF-02) | Four independent layers — §16 |
| **Async correctness** | Every accepted job terminal or bounded-retried (ER-NF-01, NR-F-07) | Postgres job table, leases, expiry recovery, retry classifier |
| **Determinism** | Identical inputs → identical order (ER-NF-06) | Stable sort with product-id tie-break; versioned `ordering_policy` |
| **Idempotency** | One durable effect per identifier (NR-NF-05, ER-F-04) | Business-key uniqueness, not a header — §17 |
| **Fair capacity** | No tenant starves another (ER-NF-07) | Per-tenant concurrency quota + fair-share dispatch ordering |
| **Failure transparency** | Terminal reasons visible, sanitized (ER-NF-04, NR-NF-06) | `failure_reason` + `error.reference` correlation id |
| **Availability** | ≥ 1 ready instance per active tenant (NR-NF-08, ASM-04) | Reconciler floor of 1; fallback lane; last-known-good cache |
| **Operability** | Team of 2–4, no SRE (SYSTEM_DESIGN NFR-6) | Five processes, three stores, Compose-first |
| **Honest HA posture** | None claimed (CON-05) | Documented single points of failure; tested restore |

---

## 7. Assumptions and Open Questions

### 7.1 Conflicts found between sources — all require a decision

**Q1 — Which resource model is the API? `[!] Blocking. Decide before any code.`**

`API.md` defines Dataset Groups, Schemas, Datasets, Uploads, Import Jobs, Solutions, Solution Versions and Campaigns, with `camelCase` fields, cursor pagination, `Idempotency-Key` headers and roles `OWNER/ADMIN/DEVELOPER/VIEWER`. `SYSTEM_DESIGN.md §2` calls that contract *"fixed."*

The frontend implements **none of it**. It has no dataset group, no schema, no solution, no campaign screen; its roles are `tenant administrator` / `tenant developer` / `platform administrator`; its fields are `snake_case`; its `/integration` page prints a different error envelope.

The SRS agrees with the frontend, not with `API.md`: §5.2 enumerates Pricing Plan, Tenant, Tenant User, API Credential, Customer, Product, Interaction Event, Training Job, Dataset Snapshot, Model Version, Model Deployment, Recommendation Request/Result/Feedback, Usage Record, Audit Record. **No solutions. No campaigns.**

> **Recommendation [R]:** Build the **SRS-native contract**. Retire `API.md`, or explicitly rescope it as a *future* Personalize-compatible façade over the same core (a translation layer, not a second data model). Do not attempt to serve both from one schema — the two model model-lifecycle differently (`Campaign` binds a version and is separately named; `Model Deployment` is one-per-tenant and unnamed, per SRS §5.2.11 *"tenant_id is unique, allowing zero or one current deployment per Tenant"*), and reconciling them would create two authorities over which model is live.

**Q2 — Job queue: PostgreSQL or RabbitMQ + Celery? `[!]`**
`SYSTEM_DESIGN.md D-3/§23` chooses Postgres `SELECT … FOR UPDATE SKIP LOCKED` and argues it eliminates the outbox pattern by making enqueue transactional with resource creation. `GraphRec_Ultimate_Architecture.md §4` chooses RabbitMQ + Celery **plus** a transactional outbox **plus** a standalone publisher — three moving parts to solve the problem the other design defines away. `PROJECT_OVERVIEW.md` also says RabbitMQ.
> **Recommendation [R]: PostgreSQL `SKIP LOCKED`.** Volume is tens of jobs per day (ASM-03: one at a time). Job state is *already* an API resource the console polls at `/training/:jobId` and `/submissions/:id`, so it must live in the database regardless — a broker would store it twice. This removes one stateful service, one publisher process and the entire outbox table. Revisit only above ~1,000 messages/second.

**Q3 — Orchestration: Docker Compose or k3s? `[!]`**
`SYSTEM_DESIGN.md D-9` rejects Kubernetes (control plane costs 1–2 GB and a core per node on three nodes). `GraphRec_Ultimate_Architecture.md §4/§30` requires k3s with one Deployment + one HPA per tenant, because `XR-F-08` demands demand-driven capacity adjustment and the console's `/service-status` renders **desired vs ready replicas** and `/admin/status` renders **"Serving replicas 7 / 7"**.
> **Recommendation [R]: a `ServingDriver` port with two adapters.** `compose` for development and the default MVP; `k3s` for the scaling demonstration. Both report `desired` / `ready` / per-replica state into `serving_replicas`, so the console is identical either way and `XR-F-08` is demonstrable without making Kubernetes a prerequisite for `docker compose up`. This is the reconciliation; neither document proposed it.

**Q4 — Vector store: Qdrant or in-process? `[!]`**
SRS §6.3 specifies a **Qdrant Vector Store Contract** — collections named `graphrec__{tenant_id}__{version_id}`, mandatory `tenant_id` payload filters, collection deleted on archive. `.env.example` carries `QDRANT_URL`, `QDRANT_COLLECTION_PREFIX`, `QDRANT_EMBEDDING_DIM=128`, `QDRANT_TOP_K=100`. The frontend has an `indexing_embeddings` training stage. But `GraphRec_Ultimate_Architecture.md §4` says *"Exact vectorized top-K plus bounded precomputed sources; ANN is future"*, its §39 stack table omits Qdrant entirely, and `SYSTEM_DESIGN.md D-5` rejects vector databases outright.
> **Recommendation [R]:** Define a `CandidateIndex` port. Ship the **in-process exact top-K** adapter for MVP (a 50,000 × 128 float32 matrix is 25 MB; ASM-02 bounds catalogs to educational scale). Keep the `indexing_embeddings` stage — it builds and uploads the index artifact either way. Add the **Qdrant adapter** when the SRS §6.3 contract must be demonstrated, honouring the exact collection naming and payload-filter rules. Retain `QDRANT_*` in `.env.example` as the adapter's config. **This satisfies the SRS contract without making a fourth stateful service a day-one dependency.**

**Q5 — Token signing: HS256 or EdDSA? `[!]`**
`.env` and `PROJECT_OVERVIEW.md §9` say HS256 with a shared `JWT_SIGNING_SECRET`. `SYSTEM_DESIGN.md D-11` and `API.md §3.5` say EdDSA (Ed25519) with a JWKS endpoint.
> **Recommendation [R]: EdDSA.** Per-tenant inference processes must verify tokens **locally**, without a call back to the control plane, or the fast path acquires a control-plane dependency on every request. A symmetric secret would have to be distributed to every inference process, making each one able to *mint* tokens. Replace `JWT_SIGNING_SECRET` with a keypair and publish `GET /v1/.well-known/jwks.json`.

**Q6 — Path versioning is inconsistent in the recovered inventory. `[!]`**
`FRONTEND_BUILD_PROMPT.md §2b` lists `POST /login`, `GET /api-keys`, `GET /tenants`, `GET /plans`, `GET /status`, `GET /failures`, `GET /audit` **without** `/v1`, while catalog, events, training, models and deployment endpoints all carry it.
> **Recommendation [R]:** Normalize everything under `/v1`. Additionally place platform-realm endpoints under `/v1/platform/*` — `GET /tenants` and `GET /audit` are platform-scoped while `GET /v1/audit-logs` is tenant-scoped, and two same-named resources in different realms is the kind of ambiguity that produces an authorization bug. Flagged as a deliberate deviation from the recovered inventory.

**Q7 — `MAX_REQUEST_BODY_BYTES=16384` contradicts bounded bulk operations. `[!]`**
`.env` caps request bodies at **16 KB**. The frontend bounds a product sync to **5,000 products** and an event batch to **5,000 events**. 5,000 products at ~120 bytes each is ~600 KB — 37× the cap.
> **Recommendation [R]:** Per-endpoint body limits. Keep 16 KB for auth and small writes; set ~2 MB for `POST /v1/products:bulk-upsert` and `POST /v1/events/batches`; return `413` with `error.class = "validation"` above it. Note the frontend already renders an oversize rejection path (*"Paste more than 5,000 products, or the word OVERSIZE"*), so `413` has a designed destination.

**Q8 — Model version lifecycle vocabularies differ across all four documents. `[!]`**

| Frontend (`GROUPS.model`) | `SYSTEM_DESIGN §26` / `API.md §18` | `Ultimate §24` |
|---|---|---|
| `registered` | `REGISTERED` | registered |
| `eligible` | `APPROVED` | approved |
| `active` | `ACTIVE` | active |
| `retired` | `ROLLED_BACK` | superseded |
| `rejected` | `REJECTED` | rejected |
| `archived` | `ARCHIVED` | archived |
| `failed_deployment` | `FAILED_DEPLOYMENT` | failed_deployment |
| — | `TRAINING`, `EVALUATED`, `DEPLOYING`, `FAILED` | — |

> **Recommendation [R]:** **The frontend's seven values are the API's `status`.** They are what the badge renderer tones. Keep `TRAINING`/`EVALUATED`/`FAILED` **inside the training job**, where the console already shows them as job states — a version simply does not exist until registration. Model `DEPLOYING` as `model_deployments.state = 'progressing'`, which the frontend's `deploy` group already has. This removes the overlap entirely rather than mapping around it.

**Q9 — Product `PUT` versus `POST` for creation. `[!]`**
`FRONTEND_BUILD_PROMPT.md §2b` lists `GET/PUT/PATCH /v1/products/{external_id}`; `Ultimate §27` lists `PUT` (*"naturally idempotent"*) and `PATCH`. Neither lists a `POST /v1/products`. But the console's `/products/new` is a create form whose conflict path is *"A product with identifier SKU-4471 already exists"* — a `409`, which a `PUT` upsert would never produce.
> **Recommendation [R]:** Support both. `POST /v1/products` = create-only, `409` on duplicate (serves `/products/new`). `PUT /v1/products/{external_id}` = idempotent upsert (serves integrations). `PATCH` = partial update (serves `/products/:productId`). All three are already implied; making it explicit resolves the conflict.

**Q10 — Pagination style. `[!]`**
`API.md §6` mandates cursor pagination and explicitly forbids offsets. Every console table renders a count of the form `"8 of 12"` (`count: list.length+' of '+s.products.length`), which needs a total.
> **Recommendation [R]:** `limit`/`offset` **with `total`** for console list endpoints — tenant-scoped, bounded, small. Cursor pagination for high-volume reads (`interaction_events`, `audit_logs`, `recommendation_requests`). Document the split rather than forcing one style onto both.

**Q11 — Training quota semantics. `[!]`**
Frontend seed: `training` usage is `6 / 8 jobs`, reset monthly. `Ultimate §20` plan table: Free 1, Basic 4, Pro 12 per month, concurrent 1. Frontend plans: STARTER `4 / month`, GROWTH `8 / month`, SCALE `20 / month`. **Plan names and numbers disagree between the two.**
> **Recommendation [R]:** Use the frontend's plan codes and limits (`STARTER` / `GROWTH` / `SCALE`) — they are what the console renders and what `/admin/plans` seeds. Treat `Ultimate §20`'s Free/Basic/Pro table as superseded. Plans are database rows, so this is data, not schema.

**Q12 — `.env.example` is newer than `.env` and diverges.** `.env.example` adds the `QDRANT_*` block; `.env` lacks it. Neither has `RABBITMQ_URL`, `CELERY_BROKER_URL`, `REDIS_URL`, `S3_ENDPOINT` or any object-storage setting, despite four documents requiring object storage. **The config surface is incomplete for every architecture proposed.** **[C, !]** → §22 defines the full set.

### 7.2 Gaps the SRS cannot resolve — the four `†` routes

Root `ROUTES.md` §"Beyond the SRS" makes an argument worth repeating verbatim in substance: **the specified system cannot be operated at all without four routes it does not specify, and 14 of the SRS's own 29 routes are unreachable as a result.** **[C]**

1. **`/users`, `/users/:userId` — tenant user management.** `NR-F-01` creates *"a tenant and initial administrator account"* — an administrator only. No use case, requirement or diagram models creating a second user. Yet §2.1 makes *"manages tenant users"* an explicit Tenant Administrator responsibility, §3.5 has the administrator *"configure authorized users and assign suitable integration permissions"* as step two of the project's own user story, and §5.2.3 defines a `role` enumeration containing `tenant developer` and a `status` enumeration containing `invited` — both meaningless without a provisioning flow. **Without it, all six Developer routes are permanently unreachable.**
2. **`/invite/accept`.** `status: invited` can never become `active` without a public route where the invited person sets their own credential.
3. **`/admin/login` and a platform identity entity.** UC-27…UC-31 each presuppose a platform permission, and §5.2.16 models `platform_administrator` as an `actor_type`. But §5.2.3 Tenant User is the ER model's only identity entity and its `role` enumeration is closed to administrator and developer — **so the platform operator has no entity to exist as, and the five named permissions have nothing to attach to.** Without it, all 8 `/admin/*` routes are unreachable.
4. Consequently a **platform-identity entity holding the five permissions**, in **a separate authentication realm** that resolves no tenant scope.

> **Backend decision [R]:** Add `platform_users` and `platform_user_permissions` (§11). Add `invitations`. Add tenant-user management endpoints. **Report all four to the supervisor as SRS defects** — an SRS that cannot provision two of its own three actors is incomplete independent of any frontend.

### 7.3 Explicitly unresolved — needs a human decision

- **Customer data lifecycle.** SRS §5.2.5 enumerates customer status `active · anonymized · deleted` and notes *"anonymization may preserve non-identifying aggregate behavior where permitted"* — but **no use case exposes customers to any human actor**, and the same section stresses that direct personal data is minimized. A `/customers` browser would contradict that minimization; a bulk-anonymization action has no natural home. Root `ROUTES.md` flags it rather than designing it. → The backend **must** store customers (events reference them; `(tenant_id, external_customer_id)` is unique per §5.2.5), and should expose an **unadvertised admin-only anonymization endpoint** for demonstration, but **no console route**. Confirm with the supervisor.
- **The 15-minute training cooldown** appears only on a frontend stat card. Confirm it is a real rule; if so it belongs in `pricing_plans.service_limits`.
- **The last-active-administrator rule** is explicitly *"Derived safety rule, not in the SRS."* It is correct and should be enforced server-side, but it is an addition.
- **Design system is not final** (`Design system decision pending/`). No backend impact; noted because it gates the React build.
- **Data-plane hostname.** `API.md` splits `api.graphrec.io` / `rec.graphrec.io`; the frontend prints one base URL `https://api.graphrec.example`. Decide whether recommendations get their own hostname (§8 recommends yes, with the console's `/integration` page updated to print both).

### 7.4 Assumptions this plan makes

| # | Assumption | If wrong |
|---|---|---|
| A1 | The React app will be built from the prototype, honouring its routes and enums | Endpoint shapes stay valid; only the client changes |
| A2 | ≤ 4 simultaneously active tenants (ASM-01) | Per-tenant serving processes stop being affordable above ~30 |
| A3 | Catalogs ≤ ~250 K products (frontend `SCALE` plan) | In-process retrieval must become Qdrant |
| A4 | Single region, one PostgreSQL, no HA (CON-03, CON-05) | Out of scope per SRS §1.3 |
| A5 | Email delivery exists for invitations and recovery | Otherwise tokens must be surfaced by an admin CLI — flag it |
| A6 | Off-site backup storage is available and not counted against the node budget | `SYSTEM_DESIGN` A-6 |

---

## 8. Recommended Backend Architecture

### 8.1 The shape, in one paragraph

A **modular-monolith control plane** (FastAPI) owning every state transition, plus four specialised processes that exist only because their *resource profile* differs: a **CPU job worker** (ingestion, exports, housekeeping), a **GPU training worker** (concurrency 1), a **deployment reconciler** (drives serving capacity toward desired state), and a **per-tenant inference process** (warm, latency-critical). One PostgreSQL is the system of record *and* the job queue. One Redis holds cache, counters, semaphores and locks — nothing authoritative. One S3-compatible object store holds snapshots, checkpoints and model bundles.

### 8.2 Why these five processes and not more or fewer

`ER-NF-08` requires separating *"administration, long-running processing, training, recommendation serving, data management, and monitoring."* That is a **logical** separation requirement, not a deployment one. `SYSTEM_DESIGN.md §10` puts the principle well: split processes only for resource reasons. Applying it:

| Process | Justified by | What breaks without it |
|---|---|---|
| `control-api` | — (the baseline) | Everything |
| `job-worker` (CPU) | Runs for minutes, streams multi-MB payloads, must not block request threads | A 5,000-row sync blocks the API event loop; `NR-F-05` counts never arrive |
| `training-worker` (GPU) | Needs CUDA, tens of GB, runs for hours, crashes in ways that must not take down the API | ASM-03's one-job-at-a-time cannot be enforced; a training OOM kills the console |
| `deployment-reconciler` | Slow control loop with external side effects; needs a leader lock | `XR-F-08` capacity adjustment and `NR-NF-08` ready-instance floor have no owner |
| `inference` (per tenant) | Must hold weights resident and answer in ms; SRS §6.4 pins it via `GRAPHREC_TENANT_ID` | `NR-NF-04` P95 < 300 ms is unreachable; tenant model isolation becomes a code convention rather than a process boundary |

**Auth, tenancy, catalog, training metadata, registry, metering and audit stay in one process.** They are transactionally coupled — accepting a product sync writes `submissions`, `jobs`, `usage_events` and `audit_logs` in one transaction. Splitting them into services would convert local calls into network calls and introduce distributed transactions to solve a problem nobody has.

### 8.3 Control plane / data plane split

`FRONTEND_BUILD_PROMPT.md §9` establishes that recommendations and feedback have **no console surface at all**. That frees the fast path from every console constraint.

| Plane | Process | Endpoints | Auth |
|---|---|---|---|
| **Control** | `control-api` | Everything the console calls, plus catalog and event ingestion | Access token **or** API credential |
| **Data** | `inference` (per tenant) | `POST /v1/recommendations`, `/recommendations/session`, `/feedback/*` | API credential only |

The data plane verifies credentials **locally** — Ed25519 public key for tokens, and a Redis-cached credential verifier for API keys — so a control-plane outage degrades recommendations rather than stopping them. This is why Q5 recommends asymmetric signing.

**Catalog and event ingestion stay on the control plane**, unlike `API.md`'s split, because `POST /v1/events` writes durable rows and creates submissions — it is a write path with transactional obligations, not a latency-critical read. The frontend's `/events/submit` and `/products/sync` screens call it directly.

### 8.4 Technology stack

| Layer | Choice | Source / rationale |
|---|---|---|
| Language | **Python 3.12** | `Ultimate §39`; same toolchain as PyTorch |
| API | **FastAPI + Pydantic v2 + Uvicorn** | All four architecture docs agree |
| ORM | **SQLAlchemy 2.0** | Explicit session control needed for `SET LOCAL` per transaction |
| Migrations | **Alembic** | **`alembic.ini` already present [C]** |
| Database | **PostgreSQL 16+** | RLS, `SKIP LOCKED`, JSONB, partitioning — all load-bearing |
| Job queue | **PostgreSQL `SKIP LOCKED`** | §7 Q2 |
| Cache / locks / counters | **Redis 7** | Rate limits, semaphores, session context, campaign cache |
| Object storage | **S3-compatible (MinIO or RustFS)** | `SYSTEM_DESIGN D-4` = MinIO; `Ultimate §39` = RustFS. Both S3 API → **one client, endpoint is config [R]** |
| ML | **PyTorch 2.x + PyTorch Geometric** | CON-01 (DGSR); `Ultimate §14` |
| Artifacts | **safetensors + JSON/Parquet manifests** | Never `pickle` across a trust boundary |
| Candidate index | **In-process exact top-K**, Qdrant adapter behind a port | §7 Q4 |
| Password hashing | **Argon2id** | `SYSTEM_DESIGN §32` |
| Tokens | **JWT, EdDSA (Ed25519)**, JWKS published | §7 Q5 |
| API credentials | **HMAC-SHA-256 with server pepper**, versioned | **`.env`: `API_KEY_HMAC_PEPPER`, `API_KEY_HASH_VERSION` [C]** |
| Reverse proxy | **Caddy** | Automatic ACME |
| Containers | **Docker + Compose**; k3s adapter optional | §7 Q3 |
| Metrics / logs | **Prometheus + Grafana**; Loki optional | `SYSTEM_DESIGN §37`, `Ultimate §21` |
| Testing | **pytest + httpx + testcontainers + Locust** | `SYSTEM_DESIGN §48` |
| Lint / types | **Ruff + mypy** | `Ultimate §39` |

### 8.5 System architecture

```mermaid
flowchart TB
    subgraph clients["Clients"]
        CON["Operator console<br/>36 routes · 3 realms"]
        APP["Tenant e-commerce application<br/>server-to-server"]
    end

    subgraph cp["CONTROL PLANE"]
        CADDY["Caddy · TLS"]
        API["control-api — FastAPI modular monolith"]
        subgraph MODS["Domain modules"]
            M1["identity"]; M2["tenancy"]; M3["credentials"]
            M4["catalog"]; M5["ingestion"]; M6["training"]
            M7["registry"]; M8["serving"]; M9["metering"]
            M10["audit"]; M11["platform"]
        end
        JW["job-worker (CPU) ×2"]
        REC["deployment-reconciler<br/>leader-locked"]
    end

    subgraph ml["ML PLANE"]
        TW["training-worker (GPU)<br/>concurrency 1"]
    end

    subgraph dp["DATA PLANE"]
        CADDY3["Caddy · TLS"]
        INF_A["inference · tenant A<br/>GRAPHREC_TENANT_ID"]
        INF_B["inference · tenant B"]
    end

    PG[("PostgreSQL<br/>system of record + job queue")]
    RD[("Redis<br/>cache · locks · counters")]
    OBJ[("Object store<br/>snapshots · bundles")]

    CON -->|HTTPS| CADDY --> API --- MODS
    APP -->|catalog · events| CADDY
    APP -->|recommendations · feedback| CADDY3 --> INF_A & INF_B

    API --> PG & RD
    API -->|presign| OBJ
    JW -->|claim jobs| PG
    JW --> OBJ
    REC -->|desired vs ready| PG
    REC -->|ServingDriver: compose | k3s| dp
    TW -->|claim · heartbeat · progress| PG
    TW -->|snapshots in · bundles out| OBJ
    INF_A -->|load bundle| OBJ
    INF_A -->|eligibility · binding| PG
    INF_A -->|session · counters| RD
```

**Read it as three lanes.** The control plane owns truth — every state transition is a Postgres write. The ML plane owns compute and holds no authoritative state, so it can vanish without data loss (`SYSTEM_DESIGN` C-5). The data plane owns speed — warm processes, local artifact reads, no synchronous control-plane dependency.

### 8.6 Cross-cutting decisions

| Decision | Choice | Rejected | Why |
|---|---|---|---|
| D-1 Application shape | Modular monolith + 4 specialised processes | Microservices; single process | Domain modules are transactionally coupled; only GPU and warm-serving have distinct resource profiles |
| D-2 Tenancy | Shared schema, `tenant_id`, forced RLS | Schema-per-tenant; DB-per-tenant | CON-02 mandates a shared model; RLS closes the correctness gap |
| D-3 Queue | Postgres `SKIP LOCKED` | RabbitMQ+Celery+outbox | §7 Q2 |
| D-4 Object storage | S3 API behind one client | Local FS; NFS | Cross-process access without a new failure mode |
| D-5 Retrieval | In-process exact top-K; Qdrant adapter | Qdrant day-one; pgvector | §7 Q4 |
| D-6 Distributed compute | Plain PyTorch + PyG | Ray | One GPU, concurrency 1 (ASM-03) |
| D-7 Model registry | Postgres tables | MLflow Registry | SRS §5.2.10/§5.2.11 *is* the registry; a second lifecycle authority is a bug source |
| D-8 Serving topology | Per-tenant process, pluggable driver | Shared multi-model pool | SRS §6.4 pins the pod per tenant; ASM-01 makes it affordable |
| D-9 Token scheme | EdDSA + JWKS | HS256 | §7 Q5 |
| D-10 Rec routing | Client → data plane directly | Client → control → data | Survives control-plane outage; removes a hop from the only latency-critical path |
| D-11 Field naming | `snake_case` | `camelCase` | Frontend `/integration` page, SRS §5.2, `Ultimate §27` |
| D-12 Idempotency | **Business identifiers** | `Idempotency-Key` header only | `/integration`: *"External identifiers are the idempotency key"*; NR-NF-05 |

---

## 9. System Architecture Description

### 9.1 Node allocation (three nodes, per CON-03)

| Node | Runs | Sized by |
|---|---|---|
| **N1 — Control** | Caddy, `control-api`, `job-worker` ×2, `deployment-reconciler`, PostgreSQL, Redis, Prometheus, Grafana | RAM for Postgres; CPU for API |
| **N2 — Training** | `training-worker`, GPU, exporters. **No state, no public port** | VRAM ≥ 12 GB; disk for checkpoints |
| **N3 — Serving + storage** | Caddy, `inference` ×N (one per active tenant), object store, exporters | RAM for resident models; disk for artifacts |

**Public surface is two ports:** `443` on N1 (console + control API + ingestion) and `443` on N3 (recommendations + feedback). Everything else binds to the private interface only. **N2 is the only node that can disappear without user-visible breakage beyond "training is unavailable"** — satisfying `SYSTEM_DESIGN` C-5.

A single-node Compose profile must also work for development; `docker compose up` starts one of each with `inference` in a shared-process mode.

### 9.2 Request lifecycle — a console read

`GET /v1/model-versions` → Caddy → `control-api` → auth dependency verifies the Ed25519 signature, loads the principal, checks user status `active` (gate 1) and tenant status `active` (gate 2), checks role `tenant administrator` (gate 3) → opens a transaction and issues `SET LOCAL app.tenant_id = '<from token claim>'` → repository query, RLS-scoped → response envelope with pagination and per-row preconditions → `X-Request-Id` echoed on the way out.

### 9.3 Request lifecycle — a recommendation

Caddy (N3) → `inference` → verify credential locally → Redis token bucket → resolve deployment binding from process memory → build user representation (long-term from resident embeddings; short-term from Redis session + request `recent_events`) → candidate retrieval from up to four sources → eligibility filter against a cached active-catalog bitmap → batched DGSR scoring → deterministic ordering with bounded diversity and freshness → respond with `items`, `model_version`, `strategy`, `fallback_applied`. **After** the response: append to session, increment usage counter, write `recommendation_requests` and `recommendation_results` asynchronously.

### 9.4 Failure posture

Per CON-05 this is stated, not hidden.

| Failure | Impact | Recovery |
|---|---|---|
| N1 down | All console and ingestion operations fail; training halts (workers cannot claim). **Recommendations continue degraded** on cached bindings and eligibility bitmaps, then fall to the popularity lane | Restart; expired leases requeue automatically |
| N2 down | Training only. Everything else unaffected | Leases expire → jobs requeue → resume from checkpoint |
| N3 down | **All recommendations fail.** Uploads fail; training cannot read snapshots or write bundles | Restart; inference reloads bundles from local storage |
| Postgres crash | Control ops fail; inference degrades to cache | `restart: always`; WAL replay |
| Redis crash | Cold cache, lost sessions, reset rate limits. **No data loss by design** | Restart |
| Object store failure | No uploads, no model loads, training blocked at I/O | Restart; restore from off-site |
| Training crash | One job | Lease expiry → requeue → resume from last epoch checkpoint |
| Activation failure | **None** — previous version keeps serving (ER-F-06) | `deployment_revisions` records why; version → `failed_deployment` |
| Disk exhaustion | Writes fail; Postgres may halt | Alert at 80%; lifecycle rules purge uploads (30 d) and checkpoints (on success) |

**Disk exhaustion is the most likely real outage**, because checkpoints and raw uploads accumulate silently. Lifecycle rules are the primary defence, not housekeeping.

---

## 10. Backend Module Breakdown

Eleven modules inside `control-api`. Boundaries are enforced in code — separate packages, **no cross-module imports except through a published interface**.

| Module | Owns | Key invariants | Console routes served |
|---|---|---|---|
| **identity** | `tenant_users`, `platform_users`, `refresh_sessions`, `invitations`, `recovery_tokens`, tokens, RBAC | Only `active` users authenticate. Last active administrator protected. Refresh tokens rotate; reuse revokes the chain. Platform realm resolves **no** tenant scope | `/login`, `/admin/login`, `/recover*`, `/invite/accept`, `/account`, `/users*` |
| **tenancy** | `tenants`, `tenant_subscriptions`, `tenant_resource_quotas`, `quota_overrides` | Tenant must be `active` for every non-auth endpoint. Exactly one current subscription. Deletion is a lifecycle, not a `DELETE` | `/register`, `/account/tenant-status`, `/home` |
| **credentials** | `api_keys`, scope catalog | Secret shown **once**. Stored as HMAC only. ≥ 1 scope required. Revoked keys are terminal. `MAX_ACTIVE_API_KEYS_PER_TENANT`. A key can never hold a scope its creating role lacks | `/credentials`, `/integration` |
| **catalog** | `products`, `product_categories` | `(tenant_id, external_product_id)` unique. Price non-negative. **Eligibility is derived, never stored as truth.** Disable requires a reason | `/products*` |
| **ingestion** | `interaction_events`, `customers`, `submissions`, `submission_errors` | `(tenant_id, external_event_id)` unique → duplicate is a **success**. Bounded batches. Partial success is normal. Errors never echo payloads | `/events/submit`, `/products/sync`, `/submissions/:id` |
| **training** | `training_jobs`, `dataset_snapshots`, `training_metrics` | ≤ 1 non-terminal job per tenant; global concurrency 1. Quota and data sufficiency checked **at enqueue**. Terminal stage recorded. Cancellation cooperative | `/training*` |
| **registry** | `model_versions`, `model_evaluation_metrics` | Immutable after registration except lifecycle status. Per-tenant `version_number` monotonic. Only `eligible` activates. Rollback target must be `retired`. The immediately-preceding retired version cannot be archived | `/models*` |
| **serving** | `model_deployments`, `deployment_revisions`, `serving_replicas`, `model_activation_history` | **Zero or one deployment per tenant.** Failed activation never replaces the active version. Capacity non-negative. Desired ≥ 1 for active tenants | `/service-status`, activate/rollback dialogs |
| **metering** | `usage_events`, `monthly_usage_aggregates`, quota evaluation | `usage_events` **INSERT-only** — no `UPDATE`/`DELETE` grant. Quantities non-negative. Unavailable measurement reported as a status, never zero | `/usage` |
| **audit** | `audit_logs`, `security_events` | Append-only. Never contains secrets, raw payloads, or another tenant's data in tenant-facing views | `/audit`, `/admin/audit` |
| **platform** | Cross-tenant reads, tenant status transitions, plan management | Every endpoint gated on a **named permission**. Tenant is a *filter*, never a scope. Reason required for status changes. Aggregate quantities only — never event payloads | `/admin/*` |

**Shared kernel** (imported by all, importing none): DB session + tenant context, error types, pagination, the job client, the storage client, the clock, config, structured logging.

**Separate applications** sharing that kernel: `job-worker`, `training-worker`, `deployment-reconciler`, `inference`.

---

## 11. Database Architecture and ERD

### 11.1 Conventions

- **Primary keys** — UUIDv7. Time-ordered for index locality; not guessable. `SYSTEM_DESIGN §16`.
- **Tenant column** — every tenant-owned table carries `tenant_id uuid NOT NULL`, even when derivable through a parent, so RLS is direct.
- **Foreign keys** — composite `(tenant_id, id)` where the child is tenant-owned. A cross-tenant reference becomes **structurally impossible**, not merely policy-prevented.
- **Timestamps** — `created_at`, `updated_at` as `timestamptz`. Never naive.
- **Soft delete** — `deleted_at timestamptz NULL` on user-visible resources only. Jobs, audit and usage rows are never soft-deleted.
- **Uniqueness** — always tenant-scoped: `UNIQUE (tenant_id, name)`.
- **Enums** — PostgreSQL `ENUM` types matching the frontend's `GROUPS` values exactly (§3.4).
- **RLS** — `ENABLE` + **`FORCE`** on every tenant table; runtime role is a non-superuser, non-owner.

### 11.2 Entity relationship diagram

```mermaid
erDiagram
    PRICING_PLANS ||--o{ TENANT_SUBSCRIPTIONS : defines
    TENANTS ||--|| TENANT_SUBSCRIPTIONS : holds
    TENANTS ||--|| TENANT_RESOURCE_QUOTAS : limited_by
    TENANTS ||--o{ QUOTA_OVERRIDES : granted
    TENANTS ||--o{ TENANT_USERS : employs
    TENANTS ||--o{ INVITATIONS : issues
    TENANT_USERS ||--o{ REFRESH_SESSIONS : holds
    TENANTS ||--o{ API_KEYS : owns

    PLATFORM_USERS ||--o{ PLATFORM_USER_PERMISSIONS : holds

    TENANTS ||--o{ PRODUCTS : owns
    TENANTS ||--o{ PRODUCT_CATEGORIES : owns
    TENANTS ||--o{ CUSTOMERS : owns
    CUSTOMERS ||--o{ INTERACTION_EVENTS : performs
    PRODUCTS  ||--o{ INTERACTION_EVENTS : receives
    TENANTS ||--o{ SUBMISSIONS : submits
    SUBMISSIONS ||--o{ SUBMISSION_ERRORS : reports

    TENANTS ||--o{ JOBS : queues
    JOBS ||--o| TRAINING_JOBS : executes
    JOBS ||--o| SUBMISSIONS : executes
    TRAINING_JOBS ||--|| DATASET_SNAPSHOTS : produces
    TRAINING_JOBS ||--o{ TRAINING_METRICS : records
    TRAINING_JOBS ||--o| MODEL_VERSIONS : registers

    TENANTS ||--o{ MODELS : owns
    MODELS ||--o{ MODEL_VERSIONS : versions
    MODEL_VERSIONS ||--o{ MODEL_EVALUATION_METRICS : measures
    TENANTS ||--o| MODEL_DEPLOYMENTS : serves_via
    MODEL_DEPLOYMENTS ||--o{ DEPLOYMENT_REVISIONS : transitions
    MODEL_DEPLOYMENTS ||--o{ SERVING_REPLICAS : runs
    MODEL_VERSIONS ||--o{ MODEL_ACTIVATION_HISTORY : activated

    TENANTS ||--o{ RECOMMENDATION_REQUESTS : serves
    RECOMMENDATION_REQUESTS ||--o{ RECOMMENDATION_RESULTS : returns
    RECOMMENDATION_RESULTS ||--o{ RECOMMENDATION_FEEDBACK : receives

    TENANTS ||--o{ USAGE_EVENTS : meters
    TENANTS ||--o{ MONTHLY_USAGE_AGGREGATES : summarizes
    TENANTS ||--o{ AUDIT_LOGS : records
    SECURITY_EVENTS }o--o| TENANTS : may_reference
    TENANTS ||--o{ IDEMPOTENCY_KEYS : scopes
```

### 11.3 Table catalogue

Global tables (no `tenant_id`, no RLS): `pricing_plans`, `platform_users`, `platform_user_permissions`, `scopes`, `alembic_version`.

**Identity & tenancy**

| Table | Notable columns | Constraints & indexes |
|---|---|---|
| `tenants` | `id`, `tenant_code UK`, `tenant_name`, `status` (`pending·active·suspended·deleting·deleted`), `settings jsonb`, `created_at`, `updated_at`, `deleted_at` | `UNIQUE(tenant_code)`; `UNIQUE(lower(tenant_name))` — the console treats a duplicate business name as a **conflict** (`dc.html` L1582) |
| `tenant_users` | `id`, `tenant_id`, `email citext`, `display_name`, `credential_digest` (Argon2id), `role` (`tenant administrator·tenant developer`), `status` (`invited·active·locked·disabled`), `last_authenticated_at` | `UNIQUE(tenant_id, email)` — SRS §5.2.3; `INDEX(tenant_id, status)`; partial index for counting active administrators |
| `platform_users` | `id`, `email citext UK`, `display_name`, `credential_digest`, `status` | **Fills SRS gap †.** Separate realm; no `tenant_id` |
| `platform_user_permissions` | `platform_user_id`, `permission` (5 values) | Composite PK |
| `invitations` | `id`, `tenant_id`, `email`, `role`, `token_digest`, `expires_at`, `accepted_at`, `superseded_at` | `UNIQUE(tenant_id, email) WHERE accepted_at IS NULL`; resend supersedes — *"The earlier link stops working"* (L1247) |
| `refresh_sessions` | `id`, `tenant_id NULL`, `user_id`, `realm`, `token_digest`, `chain_id`, `expires_at`, `revoked_at` | Rotation: consuming a used token revokes the whole `chain_id` |
| `recovery_tokens` | `id`, `subject_id`, `realm`, `token_digest`, `expires_at`, `consumed_at` | Non-disclosing lookups |
| `api_keys` | `id`, `tenant_id`, `name`, `visible_prefix UK`, `key_hash`, `predecessor_hash`, `hash_version`, `scopes jsonb`, `expires_at`, `revoked_at`, `grace_expires_at`, `last_used_at` | `UNIQUE(tenant_id, name)`, `UNIQUE(visible_prefix)` — SRS §5.2.4; `INDEX(key_hash)`; **no `DELETE` grant** |
| `pricing_plans` | `id`, `plan_code UK`, `plan_name`, `description`, `event_limit`, `recommendation_limit`, `training_limit`, `service_limits jsonb`, `is_active` | Limits `>= 0` (SRS §5.2.1). `is_active = false` ⇒ *closed to new assignments* |
| `tenant_subscriptions` | `id`, `tenant_id`, `plan_id`, `period_start`, `period_end`, `status` | Partial `UNIQUE(tenant_id) WHERE status='current'` |
| `tenant_resource_quotas` | `tenant_id PK`, per-type limit columns | Non-negative checks |
| `quota_overrides` | `id`, `tenant_id`, `usage_type`, `override_limit`, `effective_from`, `effective_to`, `approved_by` | **Overrides take precedence over the plan while active** (`pg_pTenant` L1430) |

**Catalog & interactions**

| Table | Notable columns | Constraints & indexes |
|---|---|---|
| `products` | `id`, `tenant_id`, `external_product_id`, `title`, `category_id`, `brand`, `price numeric(12,2)`, `is_active`, `availability` (`in_stock·low_stock·out_of_stock`), `attributes jsonb`, `updated_at`, `deleted_at`, `disabled_reason` | `UNIQUE(tenant_id, external_product_id)`; `price >= 0`; partial `INDEX(tenant_id) WHERE is_active AND availability<>'out_of_stock'` — the **eligibility index**, read on the hot path |
| `product_categories` | `id`, `tenant_id`, `external_category_id`, `name` | `UNIQUE(tenant_id, external_category_id)` |
| `customers` | `id`, `tenant_id`, `external_customer_id`, `attributes jsonb`, `status` (`active·anonymized·deleted`) | `UNIQUE(tenant_id, external_customer_id)`. **No console route — see §7.3** |
| `interaction_events` | `id`, `tenant_id`, `external_event_id`, `customer_id`, `product_id`, `event_type`, `value numeric`, `occurred_at`, `received_at`, `context jsonb`, `submission_id` | **`UNIQUE(tenant_id, external_event_id)` — this is NR-NF-05**; `INDEX(tenant_id, customer_id, occurred_at DESC)` (sequence retrieval); BRIN `(tenant_id, occurred_at)` (snapshot scans). Append-only |
| `submissions` | `id`, `tenant_id`, `kind` (`product_sync·event_batch`), `external_ref` (`sync_id`/`batch_id`), `status` (`processing·succeeded·failed`), `received`, `accepted`, `updated`, `skipped`, `failed`, `submitted_at`, `completed_at`, `job_id` | `UNIQUE(tenant_id, kind, external_ref)` — **the idempotency key is the business identifier**. **Unifies product syncs and event batches into one resource, closing the gap `FRONTEND_BUILD_PROMPT §2b` names** |
| `submission_errors` | `id`, `tenant_id`, `submission_id`, `item_ref`, `reason` | Capped per submission (≤ 100 retained); never echoes payloads |

**Jobs, training, registry, serving**

| Table | Notable columns | Constraints & indexes |
|---|---|---|
| `jobs` | `id`, `tenant_id`, `job_type`, `status`, `priority`, `attempt`, `max_attempts`, `run_after`, `lease_owner`, `lease_expires_at`, `cancel_requested_at`, `payload jsonb`, `progress jsonb`, `failure_reason`, timestamps | Partial `INDEX(status, job_type, run_after) WHERE status IN ('queued','running')` — the claim query stays tiny regardless of history; `INDEX(tenant_id, created_at DESC)` |
| `training_jobs` | `id`, `tenant_id`, `job_id`, `model_id`, `snapshot_id`, `state` (12 values), `stage_index`, `progress_text`, `requested_by`, `request_ref`, `interaction_window_days`, `max_epochs`, `cancel_reason`, `failure_reason`, `model_version_id`, `requested_at`, `completed_at` | **Partial `UNIQUE(tenant_id) WHERE state NOT IN (terminal)`** — enforces ≤ 1 active job per tenant at the schema level; `UNIQUE(tenant_id, request_ref)` — idempotency |
| `dataset_snapshots` | `id`, `tenant_id`, `training_job_id UK`, `cutoff_at`, `window_days`, `uri`, `checksum`, `sequence_count`, `product_count`, `event_count` | `UNIQUE(training_job_id)` — SRS §5.2.9; counts `>= 0` |
| `training_metrics` | `id`, `tenant_id`, `training_job_id`, `epoch`, `metric_name`, `value` | `UNIQUE(training_job_id, epoch, metric_name)` |
| `models` | `id`, `tenant_id`, `name`, `model_type` (`DGSR`), `default_config jsonb` | `UNIQUE(tenant_id, name)` |
| `model_versions` | `id`, `tenant_id`, `model_id`, `version_number int`, `status` (7 values), `training_job_id`, `snapshot_id`, `artifact_uri`, `artifact_digest`, `feature_contract jsonb`, `embedding_dim`, `metrics jsonb`, `failure_note`, `created_at`, `archived_at` | `UNIQUE(tenant_id, model_id, version_number)`; **partial `UNIQUE(tenant_id) WHERE status='active'`** — one active version per tenant; immutable after registration except status |
| `model_evaluation_metrics` | `id`, `tenant_id`, `model_version_id`, `split`, `metric_name`, `value` | `UNIQUE(model_version_id, split, metric_name)` |
| `model_deployments` | `id`, `tenant_id UK`, `model_id`, `desired_version_id`, `active_version_id`, `state` (6 values), `desired_replicas`, `ready_replicas`, `last_transition_at`, `epoch bigint` | **`UNIQUE(tenant_id)` — SRS §5.2.11 zero-or-one per tenant**; replicas `>= 0`; `epoch` bumped on every desired change so inference can poll for drift |
| `deployment_revisions` | `id`, `tenant_id`, `deployment_id`, `revision int`, `from_version_id`, `to_version_id`, `status`, `reason`, `failure_reason`, `started_at`, `completed_at` | `UNIQUE(deployment_id, revision)`. **The rollback and failed-activation history** |
| `serving_replicas` | `id`, `tenant_id`, `deployment_id`, `replica_ref UK`, `version_id`, `status`, `ready`, `started_at`, `ended_at` | Drives `desired vs ready` on `/service-status` and `/admin/status` |
| `model_activation_history` | `id`, `tenant_id`, `model_id`, `from_version_id`, `to_version_id`, `actor_id`, `actor_type`, `reason`, `occurred_at` | Immutable |

**Recommendations, metering, audit, operations**

| Table | Notable columns | Constraints & indexes |
|---|---|---|
| `recommendation_requests` | `id`, `tenant_id`, `external_request_id`, `customer_id NULL`, `session_hash NULL`, `model_version_id`, `strategy`, `fallback_applied`, `requested_count`, `latency_ms`, `status`, `requested_at` | `UNIQUE(tenant_id, external_request_id)` — SRS §5.2.12; `CHECK(customer_id IS NOT NULL OR session_hash IS NOT NULL)`; short retention |
| `recommendation_results` | `tenant_id`, `request_id`, `rank_position`, `product_id`, `model_score`, `final_score`, `candidate_source` | PK `(request_id, rank_position)`; `UNIQUE(request_id, product_id)` — a product appears once per request |
| `recommendation_impressions` | `id`, `tenant_id`, `external_event_id`, `request_id`, `product_id`, `position`, `occurred_at` | `UNIQUE(tenant_id, external_event_id)` |
| `recommendation_feedback` | `id`, `tenant_id`, `external_feedback_id`, `impression_id`/`request_id`, `product_id`, `feedback_type`, `value`, `occurred_at` | `UNIQUE(tenant_id, external_feedback_id)` — SRS §5.2.14 |
| `usage_events` | `id`, `tenant_id`, `usage_type` (6 values), `quantity numeric`, `source_ref`, `idempotency_key`, `occurred_at` | `UNIQUE(tenant_id, idempotency_key)`; `quantity >= 0`; **`GRANT SELECT, INSERT` only — never `UPDATE`/`DELETE`** |
| `monthly_usage_aggregates` | `tenant_id`, `period_start date`, `usage_type`, `quantity`, `measurement_status` | PK `(tenant_id, period_start, usage_type)` — SRS §5.2.15. **`measurement_status` is what lets the console say "measurement delayed" instead of showing a zero** |
| `audit_logs` | `id`, `tenant_id NULL`, `actor_type` (4 values), `actor_id`, `action` (8 values), `resource_type`, `resource_ref`, `outcome` (4 values), `correlation_ref`, `details jsonb`, `occurred_at` | `INDEX(tenant_id, occurred_at DESC)`, `INDEX(action, occurred_at DESC)`. Append-only; no `UPDATE`/`DELETE` grant |
| `security_events` | `id`, `tenant_id NULL`, `severity` (4 values), `area` (5 values), `summary`, `reference`, `occurred_at` | Serves `/admin/audit` → Failures tab; tenant identity redacted in that view |
| `idempotency_keys` | `id`, `tenant_id`, `key`, `operation`, `request_hash`, `response_ref`, `expires_at` | `UNIQUE(tenant_id, key, operation)`; 24 h TTL. Backs the optional `Idempotency-Key` header |

**27 core tables.** Deliberately deferred from `Ultimate §24`: `outbox_events` and `distributed_locks` (obsolete once the queue is in Postgres — §7 Q2), `task_records`/`task_attempts` (subsumed by `jobs`), `event_processing_failures` (subsumed by `submission_errors`), `roles`/`tenant_user_roles` (the SRS fixes exactly two tenant roles; a junction table models a flexibility the SRS forbids). **Each omission is a simplification, not an oversight.**

### 11.4 Row-Level Security

```sql
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON products
  USING      (tenant_id = current_setting('app.tenant_id')::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

`FORCE` is essential, not decorative — table owners bypass RLS otherwise. The application connects as `graphrec_app`, a non-superuser non-owner; migrations run as `graphrec_owner`, which `alembic.ini` **already configures** **[C]**. Every request opens a transaction and issues `SET LOCAL app.tenant_id = …` **from the verified token claim, never from a request field** (NR-NF-02). `SET LOCAL` scopes to the transaction, so a pooled connection cannot leak context between requests.

`WITH CHECK` matters as much as `USING`: without it a tenant could *insert* a row bearing another tenant's id.

**Platform-realm reads** use a distinct role with a policy admitting rows where `current_setting('app.platform_scope', true) = 'on'`, set only after a platform permission check. **Platform sessions never set `app.tenant_id`** — tenant is a filter in the query, never an ambient scope. This is what makes `/admin/tenants` correct by construction.

### 11.5 Migration strategy

Alembic, one revision per phase, **both directions tested in CI**. Ordering mirrors §21: identity and tenancy first, because retrofitting `tenant_id` and RLS across a populated schema is the most expensive possible mistake (`SYSTEM_DESIGN §49`). Migrations must be **backward-compatible for one release** so a rollback does not strand the schema: additive first, backfill second, constraint third, drop in a later release. A one-shot `migrate` service runs `alembic upgrade head` before the API starts.

**Partitioning:** do **not** partition `interaction_events` initially (`Ultimate §24` argues this convincingly — correct RLS, constraints and indexes matter more, and partitioning complicates uniqueness and retention). Add monthly range partitioning only when a load test demonstrates a problem. BRIN on `(tenant_id, occurred_at)` carries the snapshot scans until then.

---

## 12. Complete API Specification

### 12.1 Global conventions

| Aspect | Rule |
|---|---|
| Base | `/v1` on both planes. Trailing slashes rejected |
| Naming | **`snake_case`** — frontend `/integration`, SRS §5.2 |
| Content type | `application/json; charset=utf-8` |
| Timestamps | RFC 3339, UTC, explicit offset |
| Identifiers | UUIDv7 for platform ids; tenant-supplied external ids are opaque strings |
| Tenant scope | **Never** a path, query or body parameter on tenant routes (NR-NF-02) |
| Unknown request fields | `422` — silent acceptance hides client bugs |
| Correlation | `X-Request-Id` on **every** response; echoed as `error.reference` on failure |
| Pagination | `limit`/`offset` + `total` for console lists; cursor for high-volume reads (§7 Q10) |
| Filtering | Exact match (`?status=active`), repeated keys for OR, `?created_after=`/`?created_before=`. Unsupported keys → `422` |
| Actions | Colon suffix for non-CRUD verbs: `:activate`, `:rotate`, `:disable`, `:cancel`, `:rollback`, `:archive`, `:bulk-upsert`, `:status`, `:close`, `:accept`, `:confirm` — **matching the recovered inventory** |
| Async | `202` + a job or submission resource. Poll no faster than every 2 s (the prototype polls at 2 s) |

**Standard envelopes.**

```jsonc
// list
{ "items": [ … ], "pagination": { "limit": 25, "offset": 0, "total": 12, "has_more": false } }

// error — superset of the frontend's {class, reason, reference}
{ "error": { "class": "conflict",              // validation·conflict·limit·unavailable·auth·not_found·internal
             "code":  "product_already_exists", // machine-readable specific cause
             "reason": "a product with identifier SKU-4471 already exists",
             "reference": "err-3f81-7a20c",
             "field_errors": [ { "field": "external_product_id", "reason": "Already exists in this tenant." } ],
             "retryable": false, "retry_after_seconds": null } }
```

The frontend reads `class`, `reason` and `reference` and ignores the rest, so **existing rendering works unchanged** while `code` gives clients something stable to branch on and `field_errors` drives the per-field messages the prototype already shows (`err(…, {id:'Already exists in this tenant.'})`, L1604).

**Status codes:** `200` ok · `201` created · `202` accepted (async) · `204` no body · `400` malformed · `401` unauthenticated · `403` role/permission/tenant-state · `404` missing **or foreign** · `409` state or uniqueness conflict · `413` payload too large · `422` validation · `429` rate or quota · `500` internal · `503` unavailable.

**`404` for foreign resources is deliberate.** A `403` confirms the resource exists — itself a cross-tenant leak. Gate 4 must run before gate 5 for the same reason (§3.2).

### 12.2 Authentication and public

| Method | Path | Auth | Role | Purpose |
|---|---|---|---|---|
| POST | `/v1/tenants` | — | — | Register tenant + initial administrator |
| POST | `/v1/auth/login` | — | — | Tenant realm sign-in |
| POST | `/v1/auth/refresh` | refresh token | — | Rotate; reuse revokes the chain |
| POST | `/v1/auth/logout` | token | any | Revoke chain; denylist `jti` |
| GET | `/v1/auth/me` | token | any | Identity, role, permissions, tenant |
| POST | `/v1/auth/recovery` | — | — | Step 1 — non-disclosing |
| POST | `/v1/auth/recovery:confirm` | — | — | Step 2 — proof + new credential |
| POST | `/v1/invitations:accept` | — | — | `invited → active` **†** |
| POST | `/v1/platform/auth/login` | — | — | **Platform realm — resolves no tenant †** |
| GET | `/v1/platform/auth/me` | platform token | — | Held permissions (drives sidebar + `/admin` redirect) |
| GET | `/v1/.well-known/jwks.json` | — | — | Ed25519 public keys |
| GET | `/healthz` · `/readyz` | — | — | Liveness · readiness |

**`POST /v1/tenants`** — serves `/register`.
Request `{ tenant_name, admin_email, admin_display_name, password }`. Validation: `tenant_name` required and unique case-insensitively; `admin_email` must contain `@`; password confirmation is client-side (the prototype checks `pw !== pw2` at L1584). Response `201 { tenant_id, tenant_code, status: "pending", admin_user_id }`.
Errors: `409 conflict / tenant_name_taken` — *"A tenant account named 'Kelder Tools' already exists…"* (L1582, verbatim from the prototype); `422` field errors; `429` (`REGISTRATION_RATE_LIMIT=5` **[C]**).
Audit: `action=tenant, outcome=succeeded`. Entities: `tenants`, `tenant_users`, `tenant_subscriptions`, `tenant_resource_quotas`.

**`POST /v1/auth/login`** — serves `/login`.
Request `{ email, password }`. Response `200 { access_token, refresh_token, token_type: "Bearer", expires_in: 900, tenant_id, role, must_change_password }`. `expires_in` from `ACCESS_TOKEN_TTL_SECONDS=900` **[C]**.
Errors: **`401` is identical whether the email exists or not** — the prototype's copy is *"The credentials supplied are not valid, or the account cannot sign in"* (L1572), deliberately covering both cases; `403` when status is `locked`/`disabled`; `429` (`LOGIN_RATE_LIMIT=8` per 60 s **[C]**).
Audit: `LOGIN` / `LOGIN_FAILED`, actor `tenant_user`.

**Token claims** — `iss`, `sub` (user or key id), `tid` (**the only authoritative tenant source**; absent in the platform realm), `realm` (`tenant`|`platform`), `role`, `perms[]` (platform only), `scp[]` (API keys only), `typ` (`user`|`apikey`), `jti`, `iat`, `exp`. Signed **EdDSA (Ed25519)**.

### 12.3 Tenant — shared

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/v1/tenant` | any | Current tenant — **the only endpoint reachable when gate 2 blocks** |
| GET | `/v1/onboarding` | any | `/home` launcher + §3.5 checklist state |
| GET · PATCH | `/v1/me` | any | Own display name |
| POST | `/v1/me/password` | any | Change own credential |
| GET · POST | `/v1/api-keys` | Admin · Dev | List · create |
| GET · DELETE | `/v1/api-keys/{key_id}` | Admin · Dev | Describe · revoke |
| POST | `/v1/api-keys/{key_id}:rotate` | Admin · Dev | New secret, old valid for a grace period |
| GET | `/v1/scopes` | any | Scope catalog for the create/rotate dialogs |

**`GET /v1/tenant`** → `{ tenant_id, tenant_code, tenant_name, status, plan_code, plan_name, created_at, last_transition_at }`. Must answer with `200` even when `status ≠ active`, or `/account/tenant-status` cannot render.

**`GET /v1/onboarding`** — **new endpoint; no prior inventory has it.** The prototype computes the checklist client-side from the whole store (`hasProducts`, `hasEvents`, `okJob`, `act`, L1088). A real client cannot fetch four collections to render one card.
Response `{ checklist: [ { step: "register|configure_users|create_credential|synchronize_catalog|submit_events|request_training|review_quality|activate|serve|monitor", done: bool, route: "/users" } ], dismissed: bool, services: [ { key, label, route, permitted: bool } ] }`. Steps mirror SRS §3.5's ordered user story exactly. `PATCH /v1/onboarding { dismissed: true }` persists dismissal per user.

**`POST /v1/api-keys`** — serves the create dialog.
Request `{ name, scopes: [...], expires_in_days: 90|180|365 }`. Validation: `name` required — *"Give the credential a name so it can be told apart in this list"* (L1136); **`scopes` must be non-empty** — *"A credential with no scope cannot authorize anything"* (L1137); `name ≤ MAX_API_KEY_NAME_LENGTH=100`; `≤ MAX_API_KEY_SCOPES=12` **[C]**.
Response `201 { key_id, name, visible_prefix: "gr_live_7Kq4", secret: "gr_live_7Kq4.<...>", scopes, expires_at, created_at }` — **`secret` appears here and at rotation only, and is never retrievable again** (NR-F-03, SRS §5.2.4). The prototype's prefix format is `gr_live_` + 4 chars, secret = `prefix + "." + random` (L1138–1140).
Errors: `409 duplicate credential name`; `429 limit / max_active_keys` at `MAX_ACTIVE_API_KEYS_PER_TENANT=25` **[C]**; `403` if a scope exceeds the creating role's own capability.
Audit: `credential`. Entity: `api_keys`.

**`POST /v1/api-keys/{key_id}:rotate`** — `{ scopes[], grace_period_seconds }` ≤ `MAX_API_KEY_GRACE_SECONDS=86400` **[C]**. During the grace window `predecessor_hash` still verifies. `409` if already revoked — *"Revoked credentials cannot be rotated"* (L1118).

**`DELETE /v1/api-keys/{key_id}`** — immediate, irreversible, `204`. Repeated revoke is safe. The row is **retained** (no `DELETE` grant); `revoked_at` is set.

**`GET /v1/api-keys`** → per row `{ key_id, name, visible_prefix, scopes[], state: "usable|expired|revoked", expires_at, revoked_at, last_used_at, can_rotate, can_revoke, blocked_reason }`. **`state` is derived server-side** — the prototype derives it client-side at L1107 (`revoked ? 'revoked' : expires < today ? 'expired' : 'usable'`), which a real client should not do because it depends on server time. `can_rotate` / `can_revoke` / `blocked_reason` are the gate-5 preconditions.

### 12.4 Tenant — Administrator: users

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/users` | List — filter `?role=`, `?status=`, `?q=` |
| POST | `/v1/users` | Invite **†** |
| GET | `/v1/users/{user_id}` | Detail + capability matrix |
| PATCH | `/v1/users/{user_id}` | Change `role` or `status` |
| POST | `/v1/users/{user_id}:resend-invitation` | Supersede the prior invitation |

**`POST /v1/users`** — `{ email, display_name, role }`.
**Duplicate email is `409 conflict`, not `422`** — the prototype is explicit: *"Email is unique per tenant, so this is a conflict rather than a validation error"* (L1235). Backed by `UNIQUE(tenant_id, email)`, SRS §5.2.3.
`role` restricted to exactly `tenant administrator` | `tenant developer` — SRS §5.2.3: *"A user cannot receive a role outside the permitted tenant role set."*
Response `201 { user_id, status: "invited" }`. **The invitation token is delivered out of band and never returned** (see assumption A5). Audit: `access`.

**`PATCH /v1/users/{user_id}`** — `{ role? , status? , reason? }`.
**The last-active-administrator rule** — `409 conflict / last_active_administrator`, reason *"The last active administrator cannot be demoted or disabled."* Enforced server-side inside the transaction with a `SELECT … FOR UPDATE` count of active administrators, because two concurrent demotions would otherwise both pass a naive check. **[C for the rule (L1244), R for the locking]**
Status transitions: `invited→active` (via invite accept only), `active↔locked`, `active↔disabled`. `409` on any other pair.

**`GET /v1/users/{user_id}`** returns `is_last_active_administrator: bool` and per-action `{ allowed, blocked_reason }` so the detail page disables in place (gate 5) rather than discovering the rule on submit.

### 12.5 Tenant — Developer: catalog

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/products` | List — `?category=`, `?availability=`, `?q=`, `?eligible=` |
| POST | `/v1/products` | Create — **`409` on duplicate** (§7 Q9) |
| PUT | `/v1/products/{external_id}` | Idempotent upsert |
| GET · PATCH | `/v1/products/{external_id}` | Describe · partial update |
| POST | `/v1/products/{external_id}:disable` | Disable with a **required reason** |
| POST | `/v1/products:bulk-upsert` | Bounded synchronization → `202` + submission |
| GET | `/v1/products/categories` | Category list for the filter |

**Product representation** — field names map the prototype's abbreviations to the documented contract:

```jsonc
{ "external_product_id": "SKU-5121",       // prototype: id
  "title": "Oak shelf board 1800",
  "category": "Timber",                     // prototype: cat
  "brand": "Fenwick",
  "price": "31.50",                         // string — decimal, never a float
  "active": true,
  "availability": "out_of_stock",           // prototype: avail
  "eligible": false,                        // DERIVED
  "ineligible_reason": "Out of stock — excluded from serving",   // prototype: why
  "updated_at": "2026-08-11T16:20:00Z",
  "can_disable": true, "blocked_reason": null }
```

**`eligible` and `ineligible_reason` are computed, never stored:** `eligible = active AND availability <> 'out_of_stock' AND deleted_at IS NULL`. The two reason strings are exactly the prototype's (L683, L686). Serving must apply the identical predicate — **one shared function, called by both the API and the inference eligibility filter**, so `/products` can never claim a product is served when serving excludes it.

**`POST /v1/products`** — `422` when `external_product_id` or `title` missing; `409 product_already_exists` with `field_errors[0].reason = "Already exists in this tenant."` (L1604); `429 limit / product_quota_exhausted` with the counts named — the prototype's copy is *"This tenant holds 50,000 of 50,000 products on plan GROWTH"* (L1603), so the response must carry `{ used, limit, plan_code }`.

**`POST /v1/products:bulk-upsert`** — serves `/products/sync`.
Request `{ sync_id, mode: "upsert" | "upsert_and_disable_missing", products: [ … ] }` — `mode` comes from the form's Mode selector (L1357). **Bounded to 5,000 products**; above it `413`, `error.class = "validation"`, reason *"A synchronization is bounded to 5,000 products. Split the collection and submit it in parts."* (L1612).
`sync_id` is **required** — *"so a repeated submission is not applied twice"* (L1611) — and is the idempotency key: replaying returns the original submission.
Response `202 { submission_id, status: "processing", counts: { accepted: 0, updated: 0, skipped: 0, failed: 0 } }` — exactly the `/integration` page's documented shape.
**Partial success is normal**: individual invalid items become `submission_errors`; the accepted remainder is not discarded (L1353).
Entities: `products`, `submissions`, `submission_errors`, `jobs`, `usage_events`.

**`POST /v1/products/{external_id}:disable`** — `{ reason }`, **required, ≥ 4 characters** (L1342). Sets `is_active=false`, `disabled_reason`, and the derived `eligible` flips to `false`. *"A disabled product stops being returned by serving immediately"* — so the inference eligibility bitmap must be invalidated, not merely expired. Audit: `access`.

### 12.6 Tenant — Developer: events and submissions

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/events` | Single event |
| POST | `/v1/events/batches` | Bounded batch → `202` |
| GET | `/v1/submissions/{submission_id}` | **Unified** read — product syncs *and* event batches |
| GET | `/v1/events/batches/{batch_id}` | **Alias** kept for the recovered inventory |

**`POST /v1/events`** — the `/integration` page's documented body:
`{ event_id, customer_id, external_product_id, event_type, occurred_at, value?, context? }`.
`event_type` ∈ `view · add_to_cart · purchase · remove_from_cart` (L1369). `occurred_at` bounded — not more than 24 h future, not more than 90 d past **[R, from `API.md §21`; the prototype only shows the future rejection: *"occurred_at is in the future"*, L691]**.
Response `200 { event_id, status: "accepted" | "duplicate_confirmed" }`.
**A duplicate is a success outcome, not an error** — stated twice (`/integration` L1175, `pg_events` footnote L1375) and required by NR-NF-05 and ER-F-04. Backed by `UNIQUE(tenant_id, external_event_id)` with `ON CONFLICT DO NOTHING`.
`422` for unknown `external_product_id` or unsupported type; `429` for event quota.

**`POST /v1/events/batches`** — `{ batch_id, events: [ … ] }`, **bounded to 5,000**; above it `413` with *"A batch is bounded to 5,000 events. Split the collection and submit it in parts."* (L1627). `batch_id` required and idempotent. `202 { submission_id, batch_id, status: "processing", counts: { received } }`.

**`GET /v1/submissions/{submission_id}`** — **this endpoint closes the gap `FRONTEND_BUILD_PROMPT §2b` explicitly names** (*"A unified submission read covering product-sync results, not just event batches"*). One resource, discriminated by `kind`:

```jsonc
{ "submission_id": "sub-9002", "kind": "event_batch",     // or "product_sync"
  "status": "processing",                                  // processing·succeeded·failed
  "external_ref": "batch-4471",
  "counts": { "received": 5000, "accepted": 4870, "updated": 0, "skipped": 118, "failed": 12 },
  "stage": "applying",                                     // received·validating·applying·completed
  "percent": 100,
  "submitted_at": "2026-08-14T09:52:00Z", "completed_at": null,
  "errors": [ { "ref": "ev-33810", "reason": "occurred_at is in the future" } ] }
```

`updated` is meaningful for `product_sync` only; the console labels that column *"Updated"* for syncs and *"Duplicates"* for batches (L1389). The four-stage rail (`received → validating → applying → completed`) comes from L1381. **Errors identify the offending item and a safe reason; raw payloads are never echoed back** (L1391, NR-NF-06). There is deliberately **no index route** — the resource is reached from the submission that produced it.

### 12.7 Tenant — Administrator: training

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/training-jobs` | List — `?state=` |
| POST | `/v1/training-jobs` | Request training → `202` |
| GET | `/v1/training-jobs/eligibility` | **Gate-5 preconditions for the Start button** |
| GET | `/v1/training-jobs/{job_id}` | Status, stage rail, terminal result |
| POST | `/v1/training-jobs/{job_id}:cancel` | Cancel with a **required reason** |
| GET | `/v1/training-jobs/{job_id}/metrics` | Per-epoch training curve |
| GET | `/v1/datasets/snapshots/{snapshot_id}` | Snapshot panel |

**`GET /v1/training-jobs/eligibility`** — **new endpoint.** The prototype's `eligibility()` (L1643) reads the whole job list and the usage table to decide whether *"Start training"* is enabled and what reason to show. A real client must be told.
```jsonc
{ "eligible": false,
  "reason": "Job job-2292 is already running. Global training concurrency is 1.",
  "concurrency": { "limit": 1, "scope": "platform" },
  "interaction_data": { "sequences": 4182400, "required": 1000, "sufficient": true },
  "quota": { "used": 6, "limit": 8, "remaining": 2, "resets_at": "2026-09-01T00:00:00Z" },
  "cooldown": { "active": false, "seconds_remaining": 0, "window_seconds": 900 } }
```
Every field maps to a stat card on `/training` (L1666). The three blocking reasons are, in the prototype's own words: an already-running job, an exhausted quota (*"It resets on 2026-09-01"*), and — per the cooldown card — a 15-minute window. **[C for the first two, ! for cooldown — see §7.3]**

**`POST /v1/training-jobs`** — `{ model_type: "DGSR", interaction_window_days: 30|90|180, max_epochs: 10|20|40, request_ref }`.
`request_ref` **required** — *"so a repeated request is not applied twice"* (L1681) — and unique per tenant.
Response `202 { job_id, state: "queued", stage_index: 0, progress: "waiting to start" }`.
Errors, all checked **inside the creating transaction** so rejection is immediate and synchronous rather than discovered after a `202` (`SYSTEM_DESIGN §31`): `409 active_job_exists`; `409 cooldown_active`; `429 training_quota_exhausted`; `422 insufficient_data` (*"Dataset snapshot held fewer than 1,000 eligible interaction sequences"* — L697).
Entities: `training_jobs`, `jobs`, `usage_events`, `audit_logs`.

**`GET /v1/training-jobs/{job_id}`**:
```jsonc
{ "job_id": "job-2292", "state": "training", "model_type": "DGSR",
  "stage_index": 4, "stages": [ "queued", "…", "succeeded" ],   // JOB_STAGES, ordered
  "progress": "epoch 6 of 20",
  "requested_at": "…", "completed_at": null,
  "requested_by": { "user_id": "u-1", "display_name": "Dana Whitfield" },
  "failure_reason": null, "cancel_reason": null,
  "error_reference": null,
  "model_version": null,
  "snapshot": { "snapshot_id": "snap-7892", "window_days": 90,
                "sequence_count": 182410, "product_count": 48210 },
  "can_cancel": true, "blocked_reason": null }
```
`stage_index` **persists for terminal jobs** so the rail can render *"Stopped at building_graph"* (L1707). `can_cancel` is true only in the eight active states (L1688). A failed job carries `error_reference` for support correlation (L1697).

**`POST /v1/training-jobs/{job_id}:cancel`** — `{ reason }` required, ≥ 4 chars (L1717). Moves `queued|running → cancelling`; the worker checks the flag at the next stage boundary and transitions to `cancelled`. `409` on a terminal job. Audit: `training`, outcome `cancelled`.

### 12.8 Tenant — Administrator: model registry

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/model-versions` | List — `?status=` |
| GET | `/v1/model-versions/summary` | **Header counts for `/models`** |
| GET | `/v1/model-versions/{version_id}` | Detail + baseline/active comparison |
| POST | `/v1/model-versions/{version_id}:activate` | Activate → `202` |
| POST | `/v1/models/{model_id}:rollback` | Roll back → `202` |
| POST | `/v1/model-versions/{version_id}:archive` | Archive |

**`GET /v1/model-versions/summary`** → `{ active: 1, desired: 1, eligible: 1, retired: 1, failed_deployment: 1 }` — the five stat cards at L1737. Computable client-side only if the whole list is loaded; a summary endpoint keeps `/models` correct under pagination.

**`GET /v1/model-versions/{version_id}`** — the `/models/:versionId` page needs a **three-way comparison** (this version, baseline, active version) across four measures, which is `XR-F-10` and `UC-17`:
```jsonc
{ "version_id": "v-7", "version_number": 7, "model_type": "DGSR", "status": "active",
  "created_at": "…", "training_job_id": "job-2291",
  "metrics":  { "recall_at_10": 0.218, "hit_rate_at_10": 0.341, "ndcg_at_10": 0.187, "coverage": 0.62 },
  "baseline": { "recall_at_10": 0.150, "hit_rate_at_10": 0.260, "ndcg_at_10": 0.130, "coverage": 0.44 },
  "active_comparison": { "version_number": 7, "recall_at_10": 0.218, … },
  "artifact": { "digest": "sha256:4f21c8…9ad3", "snapshot_id": "snap-7741",
                "feature_contract": "sequence · product · category · brand",
                "embedding_dim": 128 },
  "eligible": true, "failure_note": null,
  "actions": { "activate":  { "allowed": false, "reason": "This version is already active." },
               "rollback":  { "allowed": true,  "reason": null },
               "archive":   { "allowed": false, "reason": "An active version cannot be archived." } } }
```
**`baseline` is the platform's popularity ranker** (L1752), so every training run must also evaluate the popularity baseline on the same split — otherwise the comparison column has nothing in it. The `actions` block is gate 5 in wire form; its reason strings are the prototype's, verbatim (L1749, L1768–1770).

**`POST /v1/model-versions/{version_id}:activate`** — `{ reason? }`. `202`, deployment state → `progressing`.
Preconditions: version `status = eligible` (`409 invalid_state`), owned by the caller's tenant (`404`), tenant `active`.
**Failure semantics are the critical part (ER-F-06):** the inference process loads and verifies the bundle **before** any pointer swap. On success the previous active version → `retired`, the new one → `active`. On failure the new version → `failed_deployment`, **the previous one keeps serving**, and `deployment_revisions` records the reason. The prototype's `v-4` carries exactly this history: *"Activation failed on 2026-07-29 15:52 — embedding index rejected the feature contract. Version 6 remained active."* (L704).
Entities: `model_deployments`, `deployment_revisions`, `model_activation_history`, `model_versions`, `audit_logs` (`action=activation`).

**`POST /v1/models/{model_id}:rollback`** — `{ target_version_id, reason }`, reason required (L1792). Target must be `retired` (`409 invalid_target`). **The target is validated before the active version changes** (ER-F-07) — *"If the target fails validation, version N remains active"* (L1787). Audit: `rollback`.

**`POST /v1/model-versions/{version_id}:archive`** — `{ reason }`. Allowed for `registered`, `rejected`, `retired` — **except the retired version immediately preceding the active one**, which is *"Retained as the rollback target for the active version"* (L1749). `409` with that reason otherwise. Archiving deletes the artifact bytes after retention but **keeps the row and its metrics** — history stays queryable. If the Qdrant adapter is in use, archiving deletes the collection (SRS §6.3).

### 12.9 Tenant — Administrator: usage and service status

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/subscription` | Plan and entitlements |
| GET | `/v1/usage` | Six usage types vs effective limits |
| GET | `/v1/usage/trends` | `?periods=3` — the trend panel |
| GET | `/v1/deployment` | Deployment state and active version |
| GET | `/v1/deployment/replicas` | Desired vs ready, per-replica |
| GET | `/v1/deployment/autoscaling` | Min/max/target and recent actions |
| GET | `/v1/metrics/summary` | Availability, latency, fallback rate |
| GET | `/v1/service-status/errors` | Recent serving errors, redacted |
| GET | `/v1/audit-logs` | **Tenant-scoped** audit ‡ |

**`GET /v1/usage`** → one row per type, all six:
```jsonc
{ "period": { "start": "2026-08-01", "end": "2026-09-01", "label": "monthly · resets 2026-09-01" },
  "items": [
    { "usage_type": "events", "measured": 4182400, "effective_limit": 6000000,
      "remaining": 1817600, "reset": "monthly · resets 2026-09-01",
      "measurement_status": "measured", "limit_source": "plan" },
    { "usage_type": "service_capacity", "measured": null, "effective_limit": 3,
      "remaining": null, "reset": "continuous",
      "measurement_status": "measurement delayed", "limit_source": "plan" } ] }
```
**`measured: null` with `measurement_status: "measurement delayed"` is the contract that makes NR-F-15's *"where calculable"* honest.** The console renders it as a status and *"not calculable"*, never as a zero (L715, footnote L1824). Returning `0` here would be a defect, not a rounding choice.
`limit_source` is `plan` or `override`, because `quota_overrides` take precedence while active (L1430).

**`GET /v1/deployment`** → `{ state, active_version: {version_id, version_number}, desired_replicas, ready_replicas, last_transition_at, recent_error_count_24h, fallback_rate, latency_p95_ms, measurement_freshness_seconds }`. Every field is a stat on `/service-status` (L1832–1840). `state` ∈ the 6-value `deploy` enum.

**`GET /v1/metrics/summary`** → `{ availability_24h: 0.9994, latency_p95_ms: 41, fallback_rate: 0.007, requests_24h, errors_24h }`. Sourced from Prometheus, cached ~15 s. If Prometheus is unreachable, return `measurement_status: "unavailable"` rather than zeros — same discipline as usage.

**`GET /v1/service-status/errors`** → `[{ occurred_at, class, reason, reference }]`, **error classes only. Request payloads and recommendation results are never rendered here** (L1842) — this is the only trace the console has of the serving path, and it must stay redacted.

**`GET /v1/audit-logs`** — tenant-scoped, read-only, redacted. Filters `?action=`, `?occurred_after=`. Columns `occurred_at, actor_type, action, resource_ref, outcome` (L1288). **Never exposes credential secrets, raw event payloads, or any hint of another tenant** — SRS §5.2.16 requires this for tenant-facing views specifically.

### 12.10 Platform realm

All under `/v1/platform/*`, all requiring a **platform token** and a **named permission** (§7 Q6). **These endpoints never set `app.tenant_id`** — tenant is a filter, never a scope.

| Method | Path | Permission |
|---|---|---|
| GET | `/v1/platform/tenants` | `platform permission` |
| GET | `/v1/platform/tenants/{tenant_id}` | `platform permission` (route); **sections gated separately** |
| POST | `/v1/platform/tenants/{tenant_id}:status` | `platform permission` |
| GET | `/v1/platform/tenants/{tenant_id}/usage` | `authorized platform scope` |
| POST | `/v1/platform/tenants/{tenant_id}:assign-plan` | `plan-management permission` |
| POST | `/v1/platform/tenants/{tenant_id}/quota-overrides` | `plan-management permission` |
| GET · POST | `/v1/platform/plans` | `plan-management permission` |
| GET · PATCH | `/v1/platform/plans/{plan_id}` | `plan-management permission` |
| POST | `/v1/platform/plans/{plan_id}:close` | `plan-management permission` |
| GET | `/v1/platform/usage` | `authorized platform scope` |
| GET | `/v1/platform/status` | `monitoring access` |
| GET | `/v1/platform/failures` | `audit permission` |
| GET | `/v1/platform/audit-logs` | `audit permission` |

**`GET /v1/platform/tenants/{tenant_id}` composes three permissions.** The route is gated on `platform permission`; the **plan** section requires `plan-management permission` and the **usage** section requires `authorized platform scope`. A holder of only `platform permission` gets `200` with those sections marked withheld — **not a whole-route `403`** (L1436, L1441, `FRONTEND_BUILD_PROMPT §4`):
```jsonc
{ "tenant": { … },
  "sections": {
    "status": { "granted": true,  "data": { … } },
    "plan":   { "granted": false, "reason": "This section requires the plan-management permission." },
    "usage":  { "granted": false, "reason": "This section requires the authorized platform scope." } } }
```
This is an unusual response shape and it is deliberate: modelling it any other way forces the client to make three calls and guess which `403`s are fatal.

**`POST /v1/platform/tenants/{tenant_id}:status`** — `{ status, reason }`, reason required (L1420). Transitions among `pending·active·suspended·deleting·deleted`. **A suspended, deleting or deleted tenant loses access to every tenant screen and its serving traffic stops** (L1417) — so the reconciler must scale that tenant's serving to zero, and gate 2 begins returning `403` immediately. Audit: `tenant`.

**`POST /v1/platform/tenants/{id}:assign-plan`** — `409` when the target plan is closed: *"Plan SCALE is closed to new assignments. Reopen the plan or choose another."* (L1454). Re-assigning a tenant to the plan it already holds is permitted even when closed.

**`PATCH /v1/platform/plans/{plan_id}`** — `422` on negative limits: *"A negative limit conflicts with the quota model. Enter zero to withhold a usage type entirely."* (L1635). SRS §5.2.1 requires non-negative.

**`POST /v1/platform/plans/{plan_id}:close`** — sets `is_active=false`. Reversible.

**`GET /v1/platform/usage`** — cross-tenant, `?tenant=`, `?usage_type=`, `?period=`. **Aggregate quantities only; private event payloads are excluded from every platform view** (L1438, UC-29). A tenant outside the holder's scope is **rejected, not shown as an empty row** (L1524).

**`GET /v1/platform/status`** — `{ serving_availability, training_queue: {running, waiting, concurrency}, replicas: {ready, desired}, ingestion_lag, failures_24h, active_tenants, workload_by_tenant: [...], failure_summary: [...], measurement_gaps: [...] }`. **`measurement_gaps` is required, not optional** — UC-30's alternative outcome is *"Measurement gaps are identified rather than hidden"*, and the console renders a gap as the literal string `gap` in warn colour (L1531, L1537).

**`GET /v1/platform/failures`** — `?severity=`, `?occurred_after=`. Tenant identity **redacted** unless opened from a tenant context (L1550).

### 12.11 Data plane

| Method | Path | Auth | Scope |
|---|---|---|---|
| POST | `/v1/recommendations` | API credential | `recommendation requests` |
| POST | `/v1/recommendations/session` | API credential | `recommendation requests` |
| POST | `/v1/feedback/impressions` | API credential | `recommendation feedback` |
| POST | `/v1/feedback/clicks` | API credential | `recommendation feedback` |
| POST | `/v1/feedback/conversions` | API credential | `recommendation feedback` |
| GET | `/healthz` · `/readyz` | — | — |

**`POST /v1/recommendations`** — the `/integration` page documents the request body; the response is specified here.
```jsonc
// request
{ "request_id": "rec-77120",            // idempotency key for metering (Ultimate §27)
  "customer_id": "cus-9931",            // one of customer_id or session_id required
  "session_id": "ses-2211",
  "top_n": 10,
  "context": { "surface": "cart" },
  "recent_events": [ { "external_product_id": "SKU-1180", "event_type": "view",
                       "occurred_at": "2026-08-14T09:28:41Z" } ],   // ≤ 50, applied without retraining
  "exclude_product_ids": [ "SKU-9002" ],                            // ≤ 200
  "allow_fallback": true }

// 200
{ "request_id": "rec-77120",
  "model_version": { "version_id": "v-7", "version_number": 7 },   // ER-F-05
  "strategy": "personalized",            // personalized·session·cold_start·fallback
  "fallback_applied": false,
  "items": [ { "external_product_id": "SKU-7712", "rank": 1, "score": 0.8814,
               "candidate_source": "graph" } ],
  "latency_ms": 41 }
```
**`model_version` and `strategy` are mandatory in every response** — ER-F-05 requires it, and without them a tenant cannot attribute a metrics change to a deployment.
Errors: `400` neither `customer_id` nor `session_id`; `403` scope missing; `422` `top_n` out of range or malformed `recent_events`; `429` rate or monthly quota; **`503 unavailable / model_not_ready`** only when no model is loadable **and** `allow_fallback` is false — otherwise the popularity lane answers with `strategy: "fallback"` (ER-F-10).
Ordering is **deterministic** (ER-NF-06): stable sort, ties broken by product id, bounded diversity and freshness from a **versioned** `ordering_policy` shipped in the bundle (XR-NF-02).

**`POST /v1/feedback/impressions`** — the `/integration` page's shape: `{ request_id, impressions: [ { external_product_id, position } ] }`. Each carries an `event_id` for idempotency; a repeat is a `duplicate_confirmed` success. Feedback is **informational only and never auto-activates a model** (ASM-05).

### 12.12 Endpoint count

**~70 endpoints:** 12 auth/public · 8 tenant-shared · 5 users · 7 catalog · 4 events/submissions · 7 training · 6 registry · 9 usage/status/audit · 13 platform · 5 data plane · 2 health.


---

## 13. Authentication & Authorization Design

### 13.1 Two realms, deliberately separate

Root `ROUTES.md` establishes the requirement: *"a platform operator is not a tenant user and resolves no tenant scope."* The SRS's ER model has no entity for one (§7.2). So:

| Realm | Identity table | Token `realm` | Carries | Login |
|---|---|---|---|---|
| **Tenant** | `tenant_users` | `tenant` | `tid`, `role` | `POST /v1/auth/login` |
| **Platform** | `platform_users` **†** | `platform` | `perms[]`, **no `tid`** | `POST /v1/platform/auth/login` |

A tenant token presented to `/v1/platform/*` is `403`. A platform token presented to a tenant route is `403`. **This is checked before any handler runs**, so no platform endpoint can accidentally inherit tenant scope and no tenant endpoint can be reached with platform permissions.

### 13.2 Credential types

| Type | For | Lifetime | Storage | Header |
|---|---|---|---|---|
| Access token | Console users | 900 s **[C `.env`]** | Not stored (`jti` denylist in Redis on logout) | `Authorization: Bearer <jwt>` |
| Refresh token | Console users | 604800 s **[C `.env`]** | `token_digest` in `refresh_sessions` | Body of `/v1/auth/refresh` |
| API credential | Tenant applications | Until revoked or expired | **HMAC-SHA-256 with a server pepper** | `Authorization: Bearer <secret>` |
| Invitation / recovery token | One-time flows | Short | `token_digest` | Body |

**Passwords:** Argon2id. **API credentials:** random secret, stored **only** as `HMAC-SHA-256(pepper, secret)` with `API_KEY_HASH_VERSION` recorded so the pepper can be rotated **[C `.env`]**; `visible_prefix` retained for identification; **the secret is displayed once, at creation and rotation, and never again** (NR-F-03, SRS §5.2.4, `/credentials` copy L1124).

**Refresh rotation:** every use issues a new refresh token and consumes the old one. Presenting a consumed token **revokes the entire chain** — this is how token theft is detected.

### 13.3 Authorization — three independent checks

**1. Role (tenant realm).** Exactly two roles, near-disjoint. The full matrix, from `FRONTEND_BUILD_PROMPT §4` and the prototype's own capability panel (L1258):

| Capability | Tenant Admin | Tenant Dev |
|---|:--:|:--:|
| Sign in, own account | ● | ● |
| Credential management | ● | ● |
| Tenant user management **†** | ● | ○ |
| Catalog write (add/update/disable/sync) | ○ | ● |
| Event submission | ○ | ● |
| Submission result read | ○ | ● |
| Training request & cancellation | ● | ○ |
| Model version read & lifecycle | ● | ○ |
| Usage, quota, model and service status | ● | ○ |
| Tenant audit read ‡ | ● | ○ |

**The Tenant Administrator having no catalog access is intentional** and comes straight from the use-case diagrams. `/products` requested by an administrator returns `403`, and the console redirects accordingly.

**2. Named permission (platform realm).** Five independently grantable permissions, each gating specific endpoints — not one blanket role:

| Permission | Grants |
|---|---|
| `platform permission` | Tenant accounts and status transitions |
| `plan-management permission` | Plan limits, tenant assignment, quota overrides |
| `authorized platform scope` | Cross-tenant usage summaries |
| `monitoring access` | Shared health, workload, capacity, failures |
| `audit permission` | Redacted failures and audit history |

`GET /v1/platform/auth/me` returns the held set, driving both the sidebar and the `/admin` redirect to the first permitted route.

**3. Scope (API credentials).** The five console-facing scopes, with machine names:

| Console label (`SCOPES`) | Machine name | Grants |
|---|---|---|
| catalog write & synchronization | `catalog:write` | `POST/PUT/PATCH /v1/products*`, `:bulk-upsert`, `:disable` |
| event submission (single and batch) | `events:write` | `POST /v1/events`, `/events/batches` |
| recommendation requests | `recommendations:read` | `POST /v1/recommendations*` |
| recommendation feedback | `feedback:write` | `POST /v1/feedback/*` |
| submission result read | `submissions:read` | `GET /v1/submissions/{id}` |

`GET /v1/scopes` returns `[{ name, label, description }]` so the create/rotate dialogs render the human labels the prototype uses while the wire carries stable machine names. **A credential can never hold a scope its creating role lacks** — a developer cannot mint a training-capable key.

### 13.4 The dependency chain — gates 1–4 in code

Every protected endpoint resolves one `Principal` through a single FastAPI dependency, executed in this order:

1. Parse `Authorization`; verify Ed25519 signature or HMAC-verify the API credential. Failure → `401 auth / unauthenticated`.
2. Check `jti` denylist (Redis). Failure → `401`.
3. Load the subject; **`status` must be `active`**. `invited`/`locked`/`disabled` → `401` (**gate 1**).
4. For the tenant realm: load the tenant; **`status` must be `active`** → else `403 auth / tenant_not_active` (**gate 2**). *Exempt:* `/v1/auth/*` and `GET /v1/tenant`, which `/account/tenant-status` needs.
5. Check role / permission / scope for the route → `403` (**gate 3**).
6. Open the transaction and `SET LOCAL app.tenant_id = <tid claim>` (tenant realm) or `SET LOCAL app.platform_scope = 'on'` (platform realm).
7. Query. RLS returns zero rows for foreign resources → the repository raises `NotFound` → `404` (**gate 4**).

**Gate 5 is not in this chain** — it lives in the handler as a precondition check and, more importantly, is *published* in every read response so the console can disable controls in place with a stated reason.

**Rate limiting** sits ahead of step 1 for unauthenticated endpoints (keyed by IP) and after step 3 for authenticated ones (keyed by tenant). `LOGIN_RATE_LIMIT=8/60s`, `REGISTRATION_RATE_LIMIT=5/60s`, `API_KEY_RATE_LIMIT=10/60s`, `USAGE_RATE_LIMIT=30/60s`, `SUBSCRIPTION_RATE_LIMIT=30/60s` — **all five already exist in `.env` [C]**.

---

## 14. Frontend → Backend Integration Map

Format: `Route → what it renders → API call(s) → module → entities`.

### Public

| Route | Renders | API | Module | Entities |
|---|---|---|---|---|
| `/register` | Business name, admin email, password ×2 | `POST /v1/tenants` | tenancy | tenants, tenant_users, subscriptions, quotas |
| `/login` | Email + password; resolves role → `/home` | `POST /v1/auth/login` | identity | tenant_users, refresh_sessions, audit_logs |
| `/recover` | Account identifier | `POST /v1/auth/recovery` | identity | recovery_tokens |
| `/recover/confirm` | Proof + new credential | `POST /v1/auth/recovery:confirm` | identity | recovery_tokens, tenant_users |
| `/invite/accept` † | Token + new credential | `POST /v1/invitations:accept` | identity | invitations, tenant_users |
| `/admin/login` † | Platform sign-in | `POST /v1/platform/auth/login` | identity | platform_users, permissions |

### Tenant — shared

| Route | Renders | API | Module | Entities |
|---|---|---|---|---|
| `/account/tenant-status` | Lifecycle position | `GET /v1/tenant` | tenancy | tenants |
| `/home` | Role-filtered launcher + 10-step checklist | `GET /v1/onboarding`, `PATCH /v1/onboarding` | tenancy | products, submissions, training_jobs, model_deployments |
| `/credentials` | Table: name, prefix, scopes, expires, revoked, last used, state; create/rotate/revoke dialogs; **one-time secret modal** | `GET/POST /v1/api-keys`, `GET /v1/scopes`, `POST …:rotate`, `DELETE …` | credentials | api_keys, audit_logs |
| `/integration` ‡ | Static contract + **this tenant's usable credentials and their scopes** | `GET /v1/api-keys?state=usable` | credentials | api_keys |
| `/account` ‡ | Display name, password change, read-only role/tenant/status/last-auth | `GET/PATCH /v1/me`, `POST /v1/me/password` | identity | tenant_users |

### Tenant — Administrator

| Route | Renders | API | Module | Entities |
|---|---|---|---|---|
| `/users` † | Table + role/status filters; invite dialog; last-admin footnote | `GET /v1/users`, `POST /v1/users` | identity | tenant_users, invitations |
| `/users/:userId` † | Detail, capability matrix, role/lock/disable/resend actions | `GET /v1/users/{id}`, `PATCH …`, `POST …:resend-invitation` | identity | tenant_users, invitations, audit_logs |
| `/training` | 5 stat cards, eligibility, job table, start dialog | `GET /v1/training-jobs`, `GET …/eligibility`, `POST /v1/training-jobs` | training | training_jobs, jobs, usage_events |
| `/training/:jobId` | 9-stage rail, **polled at 2 s**, snapshot panel, quality panel, cancel | `GET /v1/training-jobs/{id}`, `POST …:cancel`, `GET /v1/datasets/snapshots/{id}` | training | training_jobs, jobs, dataset_snapshots, model_versions |
| `/models` | 5 counts, status filter, quality summary column | `GET /v1/model-versions`, `GET …/summary` | registry | model_versions |
| `/models/:versionId` | Baseline/active comparison, artifact panel, activate/rollback/archive | `GET /v1/model-versions/{id}`, `POST …:activate`, `POST /v1/models/{id}:rollback`, `POST …:archive` | registry + serving | model_versions, deployments, revisions, activation_history |
| `/usage` | 6 usage rows + trend panel | `GET /v1/usage`, `GET /v1/usage/trends`, `GET /v1/subscription` | metering | usage_events, monthly_aggregates, quotas, plans |
| `/service-status` | 6 stats, deployment DL, redacted recent errors | `GET /v1/deployment`, `…/replicas`, `…/autoscaling`, `GET /v1/metrics/summary`, `GET /v1/service-status/errors` | serving | deployments, serving_replicas |
| `/audit` ‡ | Tenant-scoped redacted history | `GET /v1/audit-logs` | audit | audit_logs |

### Tenant — Developer

| Route | Renders | API | Module | Entities |
|---|---|---|---|---|
| `/products` | Table with **Serving** column (`served`/`ineligible`); category/availability/search filters | `GET /v1/products`, `GET /v1/products/categories` | catalog | products, product_categories |
| `/products/new` | Create form; conflict + quota banners | `POST /v1/products` | catalog | products, usage_events |
| `/products/sync` | Two phases: submit → counts; links to `/submissions/:id` | `POST /v1/products:bulk-upsert` | catalog + ingestion | submissions, submission_errors, jobs |
| `/products/:productId` | Detail + update form; disable dialog with reason | `GET/PATCH /v1/products/{eid}`, `POST …:disable` | catalog | products, audit_logs |
| `/events/submit` | Single/batch modes; duplicate-confirmed result | `POST /v1/events`, `POST /v1/events/batches` | ingestion | interaction_events, customers, submissions |
| `/submissions/:submissionId` | 4-stage rail, 5 counts, error table, **polled at 2 s** | `GET /v1/submissions/{id}` | ingestion | submissions, submission_errors |

### Platform

| Route | Renders | API | Permission |
|---|---|---|---|
| `/admin/tenants` | Table + status/plan filters; change-status dialog | `GET /v1/platform/tenants`, `POST …:status` | `platform permission` |
| `/admin/tenants/:tenantId` | **Three separately-gated sections** | `GET /v1/platform/tenants/{id}`, `:assign-plan`, `/quota-overrides` | composes three |
| `/admin/plans` | Plan table + create dialog | `GET/POST /v1/platform/plans` | `plan-management` |
| `/admin/plans/:planId` | Limits form, assigned tenants, close action | `GET/PATCH /v1/platform/plans/{id}`, `:close` | `plan-management` |
| `/admin/usage` | Cross-tenant usage rows | `GET /v1/platform/usage` | `authorized platform scope` |
| `/admin/status` | 6 stats, workload, failure summary, **measurement gaps** | `GET /v1/platform/status` | `monitoring access` |
| `/admin/audit` | Two tabs: Failures / Audit records | `GET /v1/platform/failures`, `GET /v1/platform/audit-logs` | `audit permission` |

### Backend capability required by the frontend that has no route

| Frontend behaviour | Backend requirement |
|---|---|
| `advance()` polls every 2.2 s and walks a job through stages | Real job progress in `jobs.progress`, written per stage; polling contract of 2 s |
| `eligibility()` computes Start-training availability | `GET /v1/training-jobs/eligibility` |
| `canActivate` / `canRollback` / `canArchive` | `actions` precondition block in `GET /v1/model-versions/{id}` |
| `isLast` (last active administrator) | `is_last_active_administrator` + server-side enforcement |
| Credential `state` derived from `expires < today` | Server-derived `state` (server time is authoritative) |
| `product.eligible` / `why` | Server-derived `eligible` / `ineligible_reason` |
| `"8 of 12"` table counts | `pagination.total` |
| One-time secret modal | `secret` returned **once**, at create and rotate only |
| Onboarding checklist reflecting real state | `GET /v1/onboarding` |
| `/admin` → first permitted route | `GET /v1/platform/auth/me` returning `perms[]` |
| Gap rendered as `gap`, never `0` | `measurement_status` on usage and platform status |

---

## 15. External Integrations

| Integration | Purpose | Requirement | Failure mode |
|---|---|---|---|
| **Object storage (S3 API)** | Dataset snapshots, checkpoints, model bundles | ER-F-02, ER-NF-03 | No uploads, no model loads, training blocked at I/O; inference serves resident models |
| **Email / transactional delivery** | Invitations (†), account recovery | UC-03, invitation flow | **Assumption A5 — unconfirmed.** Without it, tokens need an admin CLI. **Flag** |
| **Prometheus** | `GET /v1/metrics/summary`, `/v1/platform/status` | ER-NF-09, UC-30 | Return `measurement_status: "unavailable"`, never zeros |
| **Container/orchestration driver** | `ServingDriver` — Compose or k3s | XR-F-08, NR-NF-08 | Reconciler reports `degraded`; existing replicas keep serving |
| **Qdrant** *(optional adapter)* | SRS §6.3 collection contract | SRS §6.3 | In-process retrieval is the fallback |
| **Off-site backup target** | Postgres WAL + artifact mirror | §22 | Backups stop; alert |

**No payment provider.** SRS §1.3 excludes real payment processing; plans are assigned by a Platform Administrator (UC-28), and the console has no checkout, no invoice and no plan selector. **[C]**

**No browser-side SDK.** ASM/A-7: tenants integrate server-to-server; no secret ever reaches a browser.

---

## 16. Security Architecture

### 16.1 Tenant isolation — four independent layers

`SYSTEM_DESIGN §15` states the principle: **a single forgotten `WHERE` clause must not be sufficient to leak.**

| Layer | Mechanism | Failure it prevents |
|---|---|---|
| **Query** | Repositories always filter by tenant | Ordinary bugs |
| **Database** | RLS `ENABLE` + `FORCE`, non-owner runtime role, `SET LOCAL app.tenant_id` from the **verified claim** | A missing `WHERE` leaks rows |
| **Schema** | Composite `(tenant_id, id)` foreign keys | A cross-tenant reference is *structurally* impossible |
| **Object storage** | Prefix `tenants/{tenant_id}/…`; presigned URLs scoped to one key, ≤ 15 min | Path traversal; URL sharing |
| **Cache** | Redis keys prefixed `t:{tenant_id}:`; **no `KEYS`/`SCAN` in application code** | Cache-key collision |
| **Jobs** | `jobs.tenant_id` under RLS; workers set tenant context before executing | A worker processing a foreign job |
| **Models** | Bundle manifest embeds `tenant_id`; inference **refuses to load** a bundle whose tenant ≠ the deployment's | Serving tenant B's model to tenant A |
| **Serving** | One process per tenant, pinned by `GRAPHREC_TENANT_ID` (SRS §6.4) | Cross-tenant model or cache bleed |
| **API** | Tenant derived from the token, **never** from a path or body (NR-NF-02) | Parameter tampering |
| **Logs** | `tenant_id` as a label; tenant-facing views filtered | Log-based leakage |

### 16.2 Attack → defence

| Attack | Defence | Residual |
|---|---|---|
| Passes another tenant's `version_id` | RLS returns zero rows → **`404`, indistinguishable from "does not exist"** | Low |
| Forges `tenant_id` in a body | Body value ignored; tenant comes from the signed token | Very low |
| Probes for existence via gate 5 | **Gate 4 runs before gate 5** — foreign id yields `404`, never *"not eligible"* | Low |
| Replays a presigned upload URL | 15-min expiry, single object key, tenant-prefixed path | Low |
| Uploads a malicious artifact | Format allowlist (CSV/JSONL/Parquet); **no `pickle.load` anywhere in ingest**; decompression cap; memory-capped worker; **safetensors only** across the worker→inference boundary | Low |
| Floods training to starve the GPU | Per-tenant concurrency quota + fair-share dispatch (`ORDER BY tenant_running_jobs ASC, priority DESC, created_at`) | Low |
| Leaked API credential | Hashed at rest, shown once, revocable, scoped, `last_used_at` monitored, rotation with grace | **Medium** — a valid key works until revoked |
| Member self-promotes to administrator | Role change requires administrator; **last active administrator protected**; enforced under row lock | Low |
| Stolen access token | 900 s expiry; `jti` denylist on logout | **Medium within the window** |
| Enumerates resource ids | UUIDv7; `404` on every non-owned resource | Low |
| Platform token used on a tenant route (or vice versa) | Realm checked before any handler | Low |

### 16.3 Controls

| Control | Implementation |
|---|---|
| Transport | TLS 1.3 on both public surfaces; automatic ACME |
| Passwords | Argon2id; `MAX_PASSWORD_LENGTH=1024` **[C]** |
| Credentials | HMAC-SHA-256 + pepper, versioned; shown once |
| Immutable ledgers | `GRANT SELECT, INSERT` only on `usage_events` and `audit_logs` — **no `UPDATE`/`DELETE` ever** |
| Credential table | `GRANT SELECT, INSERT, UPDATE` on `api_keys`; **`DELETE` withheld** so audit records cannot be purged |
| Request size | Per-endpoint limits (§7 Q7): 16 KB default, ~2 MB for bounded bulk |
| Rate limiting | Redis token bucket per tenant and per credential; shared across both planes |
| CORS | Restricted to configured console origins |
| Secrets | From root-owned `0400` files or a secret store; never in images or Compose literals |
| Internal network | Private interface or WireGuard; default-deny firewall; databases bound to private addresses only |
| Error hygiene | `failure_reason` sanitized — actionable, never stack traces, credentials or another tenant's data (NR-NF-06) |
| Audit | Every credential change, activation, rollback, quota change and administrative action (ER-F-11) |

### 16.4 Data protection

- **Customer identifiers are tenant-local pseudonyms** (`external_customer_id`); GraphRec stores no direct personal data beyond what a tenant chooses to send (SRS §5.2.5).
- **Session identifiers are hashed** before storage in `recommendation_requests.session_hash`.
- **Anonymization** sets `customers.status = 'anonymized'` and severs the event→customer linkage while preserving aggregate behaviour where policy permits (SRS §5.2.5). No console route — see §7.3.
- **Retention:** `recommendation_requests`/`results` short (30 d default); `interaction_events` per plan; `audit_logs` long; artifacts until archive + retention.

---

## 17. Error Handling & Validation Strategy

### 17.1 Error classes — the frontend's vocabulary is the contract

The `/integration` page publishes four classes to tenants. Three more exist for the console:

| `class` | HTTP | Meaning | Console handling |
|---|---|---|---|
| `validation` | 422, 413 | Supplied information cannot be accepted | Inline field errors + banner |
| `conflict` | 409 | State or uniqueness prevents the operation | Banner; **form stays filled** |
| `limit` | 429 | A plan or quota limit is exhausted | Warn-toned banner with numbers |
| `unavailable` | 503 | Serving degraded; a fallback may apply | Status message |
| `auth` | 401, 403 | Unauthenticated, insufficient role/permission/scope, tenant not active | Gate redirect |
| `not_found` | 404 | Missing **or foreign** | `/404`, never names the resource type |
| `internal` | 500 | Unhandled | `/error` with a traceable reference |

**Every failure carries `reference`.** It correlates to server logs without exposing anything sensitive, satisfying NR-NF-06, and the console renders it on `/error` and on failed job panels (`err-3e90-2288`, L1697).

### 17.2 Validation layers

1. **Transport** — body size (per-endpoint), content type, JSON parse → `400` / `413`.
2. **Schema** — Pydantic v2; **unknown fields rejected** → `422` with `field_errors`.
3. **Domain** — enum membership, ranges, decimal formats, timestamp windows, referenced-entity existence → `422`.
4. **Uniqueness** — `(tenant_id, external_*)` violations → **`409`, not `422`**. This distinction is stated explicitly by the prototype for user email (L1235) and product id (L1604).
5. **State** — lifecycle preconditions → `409` with the reason string the console already displays.
6. **Quota** — checked **inside the creating transaction, before acceptance** (ER-F-09, `SYSTEM_DESIGN §31`) → `429` naming the limit, current usage and reset time.

Rejecting at dequeue instead of enqueue would waste the queue delay and confuse a user who already saw a `202`. That is why quota is a transaction-time check, not a worker-time one.

### 17.3 Idempotency — business identifiers first

`/integration` states it plainly: **"External identifiers are the idempotency key."**

| Operation | Key | Repeat behaviour |
|---|---|---|
| `POST /v1/events` | `(tenant_id, event_id)` | `200 { status: "duplicate_confirmed" }` — **a success** |
| `POST /v1/events/batches` | `(tenant_id, batch_id)` | Returns the original submission |
| `POST /v1/products:bulk-upsert` | `(tenant_id, sync_id)` | Returns the original submission |
| `POST /v1/products` | `(tenant_id, external_product_id)` | `409` — creation is not idempotent by design (§7 Q9) |
| `PUT /v1/products/{eid}` | The path itself | Naturally idempotent |
| `POST /v1/training-jobs` | `(tenant_id, request_ref)` | Returns the original job |
| `POST /v1/feedback/*` | `(tenant_id, event_id)` | `duplicate_confirmed` |
| `POST /v1/recommendations` | `request_id` | **Metering deduplication only** — never a cached recommendation |

An optional `Idempotency-Key` header (24 h TTL, `idempotency_keys` table) covers operations with no natural business key; replays return the original response with `Idempotency-Replayed: true`, and the same key with a different body returns `409`.

**Why `request_id` on recommendations dedupes metering but not the response:** caching a recommendation would serve stale personalization and defeat the session pathway, which is the product's entire value (XR-F-01).

### 17.4 Retry classification (ER-NF-05)

| Class | Examples | Policy |
|---|---|---|
| **Transient** | Network, storage timeout, GPU busy, OOM, lock contention | Exponential backoff `run_after = now() + 2^attempt · 30s`, capped, `max_attempts` |
| **Deterministic** | Schema violation, insufficient data, missing reference, quota | **Straight to `failed`, no attempts consumed** |
| **Cancellation** | Operator request | `cancelling → cancelled` at the next stage boundary |

The `failed` row **is** the dead-letter queue — queryable through the API, visible on `/training/:jobId`. No separate DLQ infrastructure.

### 17.5 Copy fidelity

The prototype contains ~40 finished user-facing error and consequence strings. **They should be treated as approved product copy and returned by the backend as `error.reason`**, not paraphrased. Examples already cited: L1235 (duplicate email), L1454 (closed plan), L1572 (non-disclosing sign-in), L1582 (duplicate business name), L1603 (product quota with counts), L1612/L1627 (oversize bounds), L1635 (negative limits), L1646 (training concurrency), L1749 (retained rollback target). Building a shared error-copy catalogue keeps the console and any future SDK consistent.

---

## 18. Logging, Monitoring & Observability

### 18.1 Structured logging

JSON lines. **Every record carries `request_id`, and `tenant_id` where applicable.** Never: credential secrets, raw event payloads, passwords, tokens, another tenant's identifiers.

| Level | Used for |
|---|---|
| `INFO` | Request completion, job state transitions, deployment revisions |
| `WARNING` | Quota rejections, fallback served, lease expiry recovery, measurement gaps |
| `ERROR` | Unhandled exceptions, activation failures, terminal job failures |

Business-significant events go to `audit_logs` (durable, queryable, append-only), not only to log lines. **`security_events` is a separate table** because `/admin/audit`'s Failures tab is a distinct view with severity and area, redacted differently from the audit history.

### 18.2 Metrics

| Domain | Signals | Alert |
|---|---|---|
| Host | CPU, RAM, **disk**, network | Disk > 80%, RAM > 90% for 5 min |
| GPU | Utilisation, VRAM, temperature | VRAM > 95%, temp > 85 °C |
| API | Rate, P50/P95/P99, 4xx/5xx, auth failures | P95 > 500 ms, 5xx > 1%, auth-failure spike |
| Jobs | Queue depth, wait time, duration, failures, retries | Depth > 20, any job queued > 1 h, failure rate > 10% |
| Training | Loss curve, validation metrics, epoch time | Job > 4 h, loss `NaN` |
| **Inference** | **P50/P95/P99, RPS, model load time, cache hit rate, fallback rate** | **P95 > 300 ms (NR-NF-04)**, fallback > 5%, error > 1% |
| Serving capacity | Desired vs ready replicas per tenant | `ready < 1` for an active tenant (**NR-NF-08**) |
| Business | Recommendations and events per tenant, quota utilisation | Tenant at 90% of quota |

**Fallback rate is the single most informative metric.** It rises when models fail to load, Postgres is unreachable, or a tenant has no active version — a leading indicator for several distinct failures at once. The console surfaces it directly on `/service-status`.

### 18.3 Measurement gaps are first-class

UC-30's alternative outcome is *"Measurement gaps are identified rather than hidden."* The console renders a gap as the literal word `gap` in warn colour and lists the window and cause. So:

- `monthly_usage_aggregates.measurement_status` ∈ `measured | delayed | unavailable`.
- `GET /v1/metrics/summary` and `GET /v1/platform/status` return `measurement_status` alongside every value.
- **Returning `0` for an unmeasured quantity is a defect.** This is the one observability rule that is a product requirement rather than an operational preference.

### 18.4 Tracing

OpenTelemetry is **deliberately omitted for MVP**. Distributed tracing solves following a request across many services; here there are at most two hops. Structured logs with `request_id` give the same answer without a collector to operate. Revisit if the process count grows.

---

## 19. Testing Strategy

| Layer | Scope | Tooling | Gate |
|---|---|---|---|
| **Unit** | Domain rules — eligibility predicate, last-admin rule, archive protection, quota arithmetic, retry classifier, graph construction, ranking metrics | pytest | Every PR |
| **Integration** | Repositories, job claim/lease/retry, storage client, migrations up **and down** | pytest + testcontainers | Every PR |
| **API** | Every endpoint: happy path, each error class, envelope shape, pagination, preconditions | httpx | Every PR |
| **Authorization matrix** | **Every (role × endpoint) and (permission × endpoint) pair**, allow and deny | pytest, table-driven | Every PR |
| **Isolation** | Cross-tenant access, exhaustively | Dedicated suite | **Required merge gate** |
| **Database** | RLS policies, `FORCE`, constraints, partial uniques, immutable-ledger grants | pytest | Every PR |
| **ML pipeline** | End-to-end on a fixture dataset, deterministic seed | pytest, marked slow | Nightly |
| **Model quality** | Metric floors; **no temporal leakage across the split** | pytest | Nightly |
| **Inference** | Latency budget, cold load, each fallback lane, determinism | pytest + Locust | Nightly |
| **Load** | Sustained target RPS; P95 < 300 ms (NR-NF-04) | Locust | Pre-release |
| **Failure drills** | Kill Postgres / Redis / storage mid-flight; expire a lease; corrupt a bundle | Compose chaos scripts | Pre-release |
| **Security** | Token expiry, rate limits, upload safety, dependency and image scanning | pytest + bandit + scanners | Every PR |

### 19.1 The isolation suite — a required merge gate

This is the suite that must never be skipped. `NR-NF-01` and `ER-NF-02` are the two requirements a reviewer is least likely to catch by reading a diff.

```python
@pytest.mark.isolation
class TestTenantIsolation:
    def test_foreign_resource_returns_404_not_403(self, tenant_a, tenant_b_version): ...
    def test_rls_blocks_raw_query_without_context(self, db, tenant_b_product): ...
    def test_cannot_cancel_foreign_training_job(self, ...): ...
    def test_cannot_activate_foreign_model_version(self, ...): ...
    def test_presigned_url_scoped_to_own_prefix(self, ...): ...
    def test_recommendations_never_return_foreign_products(self, ...): ...
    def test_inference_refuses_bundle_with_mismatched_tenant(self, ...): ...
    def test_redis_keys_are_tenant_prefixed(self, ...): ...
    def test_platform_token_cannot_reach_tenant_routes(self, ...): ...
    def test_tenant_token_cannot_reach_platform_routes(self, ...): ...
    def test_gate4_precedes_gate5(self, tenant_a, tenant_b_ineligible_version):
        """Foreign + ineligible must yield 404, never 409 'not eligible'."""
    def test_usage_events_reject_update_and_delete(self, db): ...
    def test_audit_logs_reject_update_and_delete(self, db): ...
```

**Enforce coverage mechanically:** a CI check compares the set of tables carrying `tenant_id` against the tables referenced by isolation tests. **A new tenant-owned table without a corresponding isolation test fails the build.**

### 19.2 Contract tests against the prototype

Because the prototype *is* the specification, three checks are worth automating:

1. **Enum parity** — extract `GROUPS`, `JOB_STAGES`, `SCOPES`, `PERMS` from `GraphRec Console.dc.html` and assert the backend's enum types contain exactly those values. A drift here silently breaks every badge.
2. **Route coverage** — extract the 36 `ROUTES` entries and assert each maps to at least one implemented endpoint.
3. **Error-copy parity** — assert the shared error catalogue contains the prototype's approved strings for the cases §17.5 lists.

These are cheap to write and catch the exact class of regression this project is most exposed to.


---

## 20. Project / Codebase Structure

One shared library, five thin applications. Domain logic lives in `graphrec/domain/`; the apps wire transport to it. This is what makes the modular monolith genuinely modular — extracting `training` into its own service later means moving a package, not untangling a codebase.

```
graphrec/
├── apps/
│   ├── control_api/            FastAPI app — routers, dependencies, middleware, main
│   │   ├── main.py             app factory, router registration, exception handlers
│   │   ├── deps.py             principal resolution, gates 1–4, tenant context
│   │   ├── middleware.py       request id, body-size guard, rate limit, CORS
│   │   ├── errors.py           the one error envelope + copy catalogue
│   │   └── routers/            auth · tenants · users · api_keys · products ·
│   │                           events · submissions · training · model_versions ·
│   │                           deployment · usage · audit · platform · health
│   ├── job_worker/             CPU worker — claim loop + handlers
│   │   └── handlers/           product_sync · event_batch · usage_rollup · janitor
│   ├── training_worker/        GPU worker — nine pipeline stages
│   ├── reconciler/             deployment controller, leader-locked
│   └── inference/              per-tenant serving process
│       ├── main.py             pinned by GRAPHREC_TENANT_ID
│       ├── retrieval.py        candidate sources
│       ├── eligibility.py      SHARED predicate with catalog (see §12.5)
│       └── ranking.py          scoring + versioned ordering policy
│
├── graphrec/                   shared library, imported by every app
│   ├── domain/
│   │   ├── identity/           users, platform users, tokens, invitations, rbac
│   │   ├── tenancy/            tenants, subscriptions, quotas, overrides
│   │   ├── credentials/        api keys, scopes, hmac verification
│   │   ├── catalog/            products, categories, eligibility
│   │   ├── ingestion/          events, customers, submissions
│   │   ├── training/           jobs, snapshots, metrics
│   │   ├── registry/           model versions, evaluation
│   │   ├── serving/            deployments, revisions, replicas, activation
│   │   ├── metering/           usage events, aggregates, quota evaluation
│   │   ├── audit/              audit log, security events
│   │   └── platform/           cross-tenant reads, plan management
│   ├── db/
│   │   ├── models/             SQLAlchemy mappings
│   │   ├── session.py          engine, session factory
│   │   ├── tenant_context.py   SET LOCAL app.tenant_id — the RLS boundary
│   │   └── repositories/       tenant-scoped data access
│   ├── jobs/                   queue client, claim, lease, heartbeat, retry, fair share
│   ├── storage/                S3 client, bucket layout, presigning, manifests
│   ├── ml/
│   │   ├── features/           FeatureBuilder — shared by snapshot, eval and serving
│   │   ├── graph/              construction, bounded 2-hop sampling
│   │   ├── model/              DGSR modules, gated fusion, BPR loss
│   │   ├── train/              loop, negative sampling, checkpointing
│   │   ├── eval/               Recall@10, HR@10, NDCG@10, coverage, baseline
│   │   ├── index/              CandidateIndex port + in-process / qdrant adapters
│   │   └── bundle/             export, manifest, digest, verification
│   ├── serving_driver/         ServingDriver port + compose / k3s adapters
│   └── common/                 config, logging, errors, clock, types, ids
│
├── migrations/                 alembic — script_location already in alembic.ini
├── deploy/
│   ├── node1/ node2/ node3/    compose files, caddy config, env templates
│   ├── single/                 one-box development compose
│   ├── k3s/                    optional manifests for the scaling demonstration
│   └── systemd/
├── tests/
│   ├── unit/ integration/ api/ authz/ isolation/ db/ ml/ inference/ load/ contract/
├── scripts/                    backup · restore · seed · smoke · demo-account
└── docs/                       this plan · SRS · runbooks · ADRs · openapi.json
```

**`graphrec/ml/features/FeatureBuilder` is called by snapshot generation, evaluation replay and inference alike.** Every artifact records its feature-schema version, normalization statistics, vocabulary checksums and code SHA, and CI runs train/serve parity fixtures. This is how training-serving skew is prevented without operating a feature-store service (`Ultimate §4`).

**Two ports carry the deferred decisions from §7:** `CandidateIndex` (in-process ↔ Qdrant, Q4) and `ServingDriver` (Compose ↔ k3s, Q3). Both are one file each and one adapter each at MVP.

---

## 21. Development Phases and Implementation Roadmap

Thirteen phases. Each is independently useful and independently testable. **Phases 1–2 are non-negotiable prerequisites** — building catalog or training before tenant isolation exists means retrofitting `tenant_id` and RLS across a populated schema, the most expensive possible ordering mistake (`SYSTEM_DESIGN §49`).

### Phase 1 — Foundation
**Objective:** a healthy skeleton that starts with one command.
**Modules:** repo layout, config (Pydantic Settings), structured logging, error envelope, Compose (Postgres, Redis, object store, API), Alembic wiring, CI.
**Database:** `alembic_version`; the two roles (`graphrec_owner`, `graphrec_app`).
**Depends on:** nothing.
**Tests:** migration up **and down**; `/healthz`; `/readyz` degradation; lint and types clean.
**Done when:** `docker compose up` yields a healthy stack and CI is green on an empty app.

### Phase 2 — Identity, tenancy, RLS
**Objective:** a tenant can be created and its users authenticated, with isolation provable.
**Modules:** identity, tenancy. **†** platform realm, invitations.
**APIs:** `POST /v1/tenants`, `/v1/auth/*`, `/v1/invitations:accept`, `/v1/platform/auth/*`, `GET /v1/tenant`, `/v1/me`, `/v1/users*`.
**Database:** `tenants`, `tenant_users`, `platform_users`, `platform_user_permissions`, `invitations`, `refresh_sessions`, `recovery_tokens`, `pricing_plans`, `tenant_subscriptions`, `tenant_resource_quotas`, `quota_overrides`. **RLS policies with `FORCE` on every tenant table.**
**Depends on:** 1.
**Tests:** **isolation suite v1**; full authorization matrix; gate 1–4 ordering; refresh rotation and chain revocation; last-active-administrator under concurrency.
**Done when:** `/register`, `/login`, `/admin/login`, `/users*`, `/account`, `/account/tenant-status` are fully served, and a foreign resource returns `404`.

### Phase 3 — Credentials
**Objective:** an integration can authenticate.
**Modules:** credentials.
**APIs:** `/v1/api-keys*`, `GET /v1/scopes`.
**Database:** `api_keys`, `scopes`.
**Depends on:** 2.
**Tests:** create/list/rotate/revoke lifecycle; secret returned exactly once; HMAC verification; grace-period behaviour; `MAX_ACTIVE_API_KEYS_PER_TENANT`; scope-delegation refusal; cross-tenant blocking.
**Done when:** `/credentials` and `/integration` are fully served and an API credential authenticates a request.

### Phase 4 — Job system
**Objective:** durable async work with bounded retry.
**Modules:** `graphrec/jobs`, `job_worker`.
**APIs:** none directly (job state surfaces through owning resources).
**Database:** `jobs` with the partial claim index.
**Depends on:** 2.
**Tests:** concurrent claim with `SKIP LOCKED`; lease expiry → requeue; heartbeat renewal; retry classification (transient vs deterministic); fair-share ordering; cancellation at a stage boundary.
**Done when:** two workers claim disjoint jobs, a killed worker's job requeues automatically, and a deterministic failure consumes no attempts.

### Phase 5 — Catalog
**Objective:** a tenant can manage its catalog.
**Modules:** catalog.
**APIs:** `/v1/products*`, `:disable`, `/v1/products/categories`.
**Database:** `products`, `product_categories`.
**Depends on:** 3.
**Tests:** duplicate → `409` with field error; quota → `429` with counts; eligibility predicate (all four cases); disable requires reason; the shared eligibility function returns identical results to the serving path.
**Done when:** `/products`, `/products/new`, `/products/:productId` are fully served.

### Phase 6 — Ingestion
**Objective:** events and bulk syncs land durably and idempotently.
**Modules:** ingestion; `job_worker` handlers.
**APIs:** `POST /v1/events`, `/v1/events/batches`, `POST /v1/products:bulk-upsert`, `GET /v1/submissions/{id}`.
**Database:** `interaction_events`, `customers`, `submissions`, `submission_errors`.
**Depends on:** 4, 5.
**Tests:** duplicate event → `duplicate_confirmed`; oversize → `413`; partial success preserves the accepted remainder; timestamp-window rejection; streaming parse under a memory cap; errors never echo payloads; re-submitting the same `sync_id` returns the original submission.
**Done when:** `/events/submit`, `/products/sync`, `/submissions/:id` are fully served with a live progress rail.

### Phase 7 — Metering and quotas
**Objective:** limits are enforced before acceptance and usage is visible.
**Modules:** metering.
**APIs:** `GET /v1/usage`, `/v1/usage/trends`, `/v1/subscription`.
**Database:** `usage_events` (INSERT-only grant), `monthly_usage_aggregates`.
**Depends on:** 6.
**Tests:** ledger immutability (`UPDATE`/`DELETE` raise); Redis fast counter reconciles to the durable ledger; override precedence over plan limit; **`measurement_status` propagates instead of a zero**; quota rejection names limit, usage and reset.
**Done when:** `/usage` renders all six usage types including a delayed measurement.

### Phase 8 — DGSR offline
**Objective:** the model trains and evaluates correctly, in isolation.
**Modules:** `graphrec/ml` — features, graph, model, train, eval.
**APIs:** none.
**Database:** none.
**Depends on:** 1.
**Tests:** graph construction on a fixture; bounded 2-hop sampling; **temporal leave-last-out split with no leakage**; Recall@10 / HR@10 / NDCG@10 / coverage correctness against hand-computed values; popularity baseline; deterministic seed reproduces metrics.
**Done when:** a script trains on a fixture dataset and reports metrics above the popularity baseline.
> **Run this phase offline-first, before wiring it to jobs and storage.** Debugging a model and a distributed job system simultaneously is how ML projects stall (`SYSTEM_DESIGN §49`).

### Phase 9 — Training jobs
**Objective:** `/training` works end to end.
**Modules:** training; `training_worker`.
**APIs:** `/v1/training-jobs*`, `:cancel`, `/eligibility`, `/metrics`, `GET /v1/datasets/snapshots/{id}`.
**Database:** `training_jobs`, `dataset_snapshots`, `training_metrics`, `models`.
**Depends on:** 4, 6, 8.
**Tests:** all nine stages progress and persist; **`stage_index` survives failure and cancellation**; global concurrency 1 enforced by the partial unique index under concurrent requests; cooldown and quota rejection at enqueue; crash mid-training resumes from the last checkpoint; `request_ref` replay returns the original job.
**Done when:** `/training` and `/training/:jobId` are fully served with a live nine-stage rail.

### Phase 10 — Model registry
**Objective:** every succeeded job registers an immutable, verifiable version.
**Modules:** registry; `graphrec/ml/bundle`, `graphrec/ml/index`.
**APIs:** `GET /v1/model-versions*`, `/summary`, `:archive`.
**Database:** `model_versions`, `model_evaluation_metrics`.
**Depends on:** 9.
**Tests:** bundle export and digest verification; **corrupt bundle is detected at load**; manifest `tenant_id` mismatch is refused; version numbering monotonic per tenant; archive protection for the retained rollback target; baseline comparison populated.
**Done when:** `/models` and `/models/:versionId` are fully served with the three-way comparison.

### Phase 11 — Serving and deployment
**Objective:** recommendations are served, and activation is safe.
**Modules:** serving; `inference`; `reconciler`; `serving_driver`.
**APIs:** `:activate`, `:rollback`, `GET /v1/deployment*`, `/v1/metrics/summary`, `/v1/service-status/errors`, **`POST /v1/recommendations*`, `POST /v1/feedback/*`**.
**Database:** `model_deployments`, `deployment_revisions`, `serving_replicas`, `model_activation_history`, `recommendation_requests`, `recommendation_results`, `recommendation_impressions`, `recommendation_feedback`.
**Depends on:** 10.
**Tests:** **failed activation retains the previous active version (ER-F-06)**; rollback validates the target first (ER-F-07); deterministic ordering (ER-NF-06); each fallback lane; `model_version` and `strategy` in every response (ER-F-05); cross-tenant products never returned; **P95 < 300 ms under load (NR-NF-04)**; `ready ≥ 1` maintained for active tenants (NR-NF-08).
**Done when:** `/service-status` is fully served and a tenant application receives real recommendations.

### Phase 12 — Audit, platform realm, observability
**Objective:** the platform console works and the system explains itself.
**Modules:** audit, platform.
**APIs:** `GET /v1/audit-logs`, all `/v1/platform/*`.
**Database:** `audit_logs`, `security_events`.
**Depends on:** 2–11.
**Tests:** audit written for every credential, training, activation, rollback, quota and tenant action; **tenant-facing audit never reveals another tenant**; per-permission gating including the three-section composition on tenant detail; **measurement gaps reported as gaps**; ledger immutability.
**Done when:** all 8 `/admin/*` routes and `/audit` are fully served.

### Phase 13 — Hardening and deployment
**Objective:** operable and recoverable.
**Modules:** all.
**Work:** per-node Compose + systemd (and the k3s profile if Q3 selects it), CI/CD, firewall, secrets, backup **and a rehearsed restore**, dashboards and alerts, OpenAPI publication, runbooks.
**Depends on:** 1–12.
**Tests:** load test at target RPS; failure drills (kill each dependency mid-flight); **restore drill verified against row counts**; security scan; full isolation suite as a merge gate.
**Done when:** one-command deploy, a verified restore, and every §24 checklist item satisfied.

### 21.1 Dependency graph

```
1 Foundation
└─ 2 Identity+Tenancy+RLS ──┬─ 3 Credentials ── 5 Catalog ──┐
                            └─ 4 Job system ────────────────┼─ 6 Ingestion ─ 7 Metering
1 ─ 8 DGSR offline ─────────────────────────────────────────┘        │
                                            4,6,8 ─ 9 Training jobs ─┘
                                                    9 ─ 10 Registry ─ 11 Serving
                                                              2–11 ─ 12 Audit+Platform
                                                                     1–12 ─ 13 Hardening
```

**Phase 8 runs in parallel with 3–7** — it depends only on Phase 1 and needs no database. On a small team that parallelism is the difference between a comfortable schedule and a tight one.

---

## 22. Deployment & Infrastructure Plan

### 22.1 Topology

Three nodes (CON-03), or one for development. Per §9.1: N1 control, N2 training/GPU, N3 serving + object storage. **Two public ports total.** All inter-node traffic on a private interface or a WireGuard mesh; databases and object storage bound to private addresses only; default-deny firewall; SSH key-only.

### 22.2 Runtime

Docker Compose per node, each wrapped in a systemd unit for boot ordering and restart.

| Concern | Implementation |
|---|---|
| Startup ordering | `depends_on` with `condition: service_healthy` |
| Restart | `restart: unless-stopped`; systemd restarts the project on host boot |
| Health checks | `pg_isready`, `redis-cli ping`, `/healthz` on API and inference, storage liveness |
| Migrations | One-shot `migrate` service runs `alembic upgrade head` **before** the API starts |
| Backward compatibility | **Migrations must be safe for one release back**, so a rollback does not strand the schema |
| Images | Tagged by commit SHA; rollback = pin the previous tag |
| Secrets | Root-owned `0400` files as Docker secrets; rotation is file replace + restart |
| Per-tenant inference | Started by the reconciler through `ServingDriver`; pinned by `GRAPHREC_TENANT_ID` |

### 22.3 CI/CD

```
push → ruff + mypy → unit → integration (ephemeral postgres + storage)
     → API + authz matrix → ISOLATION SUITE (required gate)
     → main? → build images (api · worker · trainer · reconciler · inference)
     → push tagged by SHA
     → deploy N1 (migrations first) → smoke control API
     → deploy N3 (inference)        → smoke a recommendation
     → deploy N2 (trainer)          → notify
```

**Deployment order is not arbitrary.** N1 first because it owns migrations; N3 next because it is user-facing and must be verified before training resumes; N2 last because it tolerates delay best. Each node pulls only the images it runs, so the trainer's multi-gigabyte CUDA image never reaches N1 or N3.

**The isolation suite is a required merge gate.** A change that lets tenant A see tenant B's data must not be deployable, and that check belongs in CI rather than in review.

### 22.4 Configuration surface

`.env`/`.env.example` are **incomplete for every architecture proposed** (§7 Q12). The full set:

| Group | Keys |
|---|---|
| **Present, keep** | `POSTGRES_*`, `API_PORT`, `FRONTEND_PORT`, `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS`, `AUDIT_HASH_SECRET`, `API_KEY_HMAC_PEPPER`, `API_KEY_HASH_VERSION`, `MAX_ACTIVE_API_KEYS_PER_TENANT`, `MAX_API_KEY_NAME_LENGTH`, `MAX_API_KEY_SCOPES`, `MAX_API_KEY_GRACE_SECONDS`, `MAX_TENANT_NAME_LENGTH`, `MAX_PASSWORD_LENGTH`, `MAX_IDEMPOTENCY_KEY_LENGTH`, all five `*_RATE_LIMIT`/`*_RATE_WINDOW_SECONDS`, `DEMO_*` |
| **Replace** | `JWT_SIGNING_SECRET` → `JWT_PRIVATE_KEY_PATH`, `JWT_PUBLIC_KEY_PATH`, `JWT_KEY_ID` (§7 Q5) |
| **Replace** | `MAX_REQUEST_BODY_BYTES=16384` → `MAX_REQUEST_BODY_BYTES` (default) **plus** `MAX_BULK_BODY_BYTES` (§7 Q7) |
| **Missing — add** | `REDIS_URL`; `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`; `WORKER_CONCURRENCY`, `JOB_LEASE_SECONDS`, `JOB_HEARTBEAT_SECONDS`, `JOB_MAX_ATTEMPTS`; `TRAINING_GLOBAL_CONCURRENCY=1`, `TRAINING_COOLDOWN_SECONDS=900`, `TRAINING_MIN_SEQUENCES=1000`; `MAX_PRODUCTS_PER_SYNC=5000`, `MAX_EVENTS_PER_BATCH=5000`, `EVENT_FUTURE_WINDOW_HOURS=24`, `EVENT_PAST_WINDOW_DAYS=90`; `RECOMMENDATION_MAX_TOP_N=100`, `RECOMMENDATION_MAX_RECENT_EVENTS=50`, `RECOMMENDATION_MAX_EXCLUSIONS=200`, `SESSION_TTL_SECONDS=1800`; `SERVING_DRIVER=compose\|k3s`, `CANDIDATE_INDEX=inprocess\|qdrant`; `PROMETHEUS_URL`; `SMTP_*`; `CORS_ALLOWED_ORIGINS` |
| **Keep as adapter config** | `QDRANT_URL`, `QDRANT_COLLECTION_PREFIX`, `QDRANT_EMBEDDING_DIM=128`, `QDRANT_TOP_K=100` |

Every hard-coded bound the prototype displays (5,000 products, 5,000 events, 1,000 sequences, 15-minute cooldown, embedding dim 128) becomes a named setting. **Nothing that a user-facing message quotes should be a literal in code.**

### 22.5 Backups

Backups go **off-site**, outside the three nodes. A backup on the host it protects is not a backup.

| Asset | Method | Frequency | Retention | RPO |
|---|---|---|---|---|
| PostgreSQL | Base backup + continuous WAL archiving | Base weekly, WAL continuous | 30 d | **≤ 5 min** |
| PostgreSQL logical | `pg_dump` | Daily | 14 d | 24 h |
| Model bundles | Mirror to off-site bucket | Hourly | 90 d | 1 h |
| Processed snapshots | Mirror | Daily | 30 d | 24 h |
| Raw uploads | **Not backed up** | — | — | Re-uploadable by the tenant |
| Configuration | Git | On commit | Full history | 0 |
| Secrets | Encrypted vault file, off-site | On change | 10 versions | 0 |

**Restore drill quarterly.** An untested backup is a hypothesis. The drill restores PostgreSQL to a scratch host and verifies row counts.

### 22.6 Disaster recovery

Priority order for a total-loss rebuild: provision hosts and restore secrets → **restore PostgreSQL first** (without it nothing else is meaningful, since it holds every resource's identity) → restore model bundles (brings serving back) → start control plane and inference, verify a recommendation end to end → restore processed snapshots (restores training) → raw uploads are not restored.

**Deliberately accepted, per CON-05:** no warm standby, no cross-region replication, no automatic failover. All three require a fourth machine. The recovery plan is documented, scripted and rehearsed instead — the correct trade at this scale, and one to state to stakeholders rather than obscure.

---

## 23. Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **The `API.md` conflict is not resolved and two contracts get half-built** | High | **Critical** | §7 Q1 is a blocking decision. Resolve in writing before Phase 2. Retire or rescope `API.md` |
| R2 | RLS is added late and must be retrofitted across a populated schema | Medium | Critical | Phase 2 is a hard prerequisite; isolation suite is a merge gate from Phase 2 onward |
| R3 | Backend enums drift from the frontend's `GROUPS`, silently breaking badges | **High** | Medium | Contract test §19.2 extracts the prototype's enums and asserts parity |
| R4 | Gate 5 preconditions omitted; the console offers actions the server rejects | High | Medium | Every read response carries an `actions`/`can_*` block; API tests assert it |
| R5 | Gate 4/5 ordering inverted, leaking resource existence | Medium | High | Explicit isolation test `test_gate4_precedes_gate5` |
| R6 | Model quality below the popularity baseline; nothing is ever `eligible` | **Medium** | High | Phase 8 offline-first with metric floors; baseline evaluated on every run; `rejected` status exists for exactly this |
| R7 | Training-serving skew — offline metrics do not predict serving behaviour | Medium | High | Shared `FeatureBuilder`; feature-schema version and checksums in every manifest; CI parity fixtures |
| R8 | GPU unavailable or too small for the configured sampling | Medium | Medium | CPU fallback for small datasets; bounded 2-hop sampling; `waiting_for_resources` state already exists in the enum |
| R9 | Per-tenant inference processes exhaust node RAM as tenants grow | Low at ASM-01 | High later | ASM-01 caps at 4 active; LRU eviction and quantization are the documented next steps |
| R10 | Disk exhaustion from accumulated checkpoints and uploads | **High** | High | Lifecycle rules (uploads 30 d, checkpoints deleted on success); alert at 80% |
| R11 | Email delivery does not exist, so invitations and recovery cannot complete | Medium | High | **Assumption A5 — confirm now.** Fallback: an admin CLI that prints the token |
| R12 | The 16 KB body cap ships and every bulk operation fails | Medium | High | §7 Q7 — per-endpoint limits in Phase 1 config |
| R13 | Platform identity is treated as "just another role" and inherits tenant scope | Medium | **Critical** | Separate table, separate realm, realm checked before any handler; two isolation tests |
| R14 | Single-node PostgreSQL is a total single point of failure | **Certain** | High | Accepted per CON-05. Tested restore; first additional host runs a replica |
| R15 | Scope creep from `API.md`'s dataset groups / solutions / campaigns | Medium | Medium | §7 Q1 decision recorded as an ADR; §12 is the contract of record |
| R16 | Prototype error copy is paraphrased, so the console and server disagree | Medium | Low | Shared error-copy catalogue; contract test §19.2 |
| R17 | Cooldown and last-admin rules are enforced client-side only | Medium | Medium | Both enforced server-side; last-admin under a row lock |
| R18 | Customer lifecycle stays unresolved and blocks a demonstration requirement | Medium | Low | §7.3 — raise with the supervisor before Phase 6 |

---

## 24. Production Readiness Checklist

Given CON-05 this is *demonstration-readiness with production hygiene*, not an HA claim.

**Security**
- [ ] TLS 1.3 on both public surfaces; automatic certificate renewal
- [ ] Argon2id passwords; EdDSA tokens; JWKS published
- [ ] API credentials HMAC-only at rest, shown once, versioned pepper
- [ ] RLS `ENABLE` **and `FORCE`** on every tenant table; runtime role is non-owner
- [ ] `usage_events` and `audit_logs` have **no `UPDATE`/`DELETE` grant**; `api_keys` has no `DELETE`
- [ ] Per-endpoint body limits; rate limits on all five configured classes
- [ ] Firewall default-deny; databases and storage on private addresses only
- [ ] Secrets from files or a store; **none in images, Compose literals or Git**
- [ ] Dependency and image scanning in CI
- [ ] `.env.example` complete and committed; **real `.env` never committed** (already in `.gitignore` **[C]**)

**Isolation — the gate that matters most**
- [ ] Isolation suite passes and is a **required** merge check
- [ ] Every table carrying `tenant_id` has a corresponding isolation test (CI-enforced)
- [ ] Foreign resources return `404`, never `403`
- [ ] Gate 4 precedes gate 5, with a test proving it
- [ ] Cross-realm token rejection tested both directions
- [ ] Bundle manifest `tenant_id` verified before load

**Correctness**
- [ ] Migrations reversible; up and down tested in CI
- [ ] Every accepted job reaches a terminal state or is bounded-retried (ER-NF-01)
- [ ] Failed activation demonstrably retains the previous version (ER-F-06)
- [ ] Rollback target validated before the active version changes (ER-F-07)
- [ ] Idempotency proven for events, batches, syncs, training and feedback (NR-NF-05, ER-F-04)
- [ ] Recommendation ordering deterministic for identical inputs (ER-NF-06)
- [ ] `model_version` and `strategy` in every recommendation response (ER-F-05)
- [ ] No temporal leakage in the evaluation split

**Observability**
- [ ] Structured logs with `request_id` on every line; secrets and payloads never logged
- [ ] Dashboards for host, GPU, API, jobs, training, inference, capacity, business
- [ ] Alerts: inference P95 > 300 ms, fallback > 5%, queue depth, job failure rate, disk > 80%, `ready < 1` for an active tenant
- [ ] **Measurement gaps reported as gaps, never as zeros** (UC-30)
- [ ] Audit written for every action ER-F-11 enumerates

**Resilience**
- [ ] Every failure mode in §9.4 has a documented, rehearsed recovery
- [ ] Backups off-site; **restore drill executed and verified**
- [ ] Lifecycle rules purge uploads and checkpoints
- [ ] Lease expiry recovery demonstrated by killing a worker mid-job
- [ ] Fallback lane demonstrated with the model store unreachable

**Operations**
- [ ] One-command deploy per node; rollback by tag
- [ ] Migrations run before the API starts and are one-release backward-compatible
- [ ] Runbooks: restore, rotate secrets, evict a stuck job, force a rollback, suspend a tenant
- [ ] OpenAPI published and matching `/integration`'s documented shapes
- [ ] Demo account bootstrap script (`DEMO_*` settings already exist **[C]**)

**Documentation**
- [ ] `API.md` conflict resolved in writing (§7 Q1)
- [ ] The four SRS defects (§7.2) reported to the supervisor
- [ ] ADRs recorded for Q1–Q12
- [ ] This plan updated as decisions land

---

## 25. Final Recommended Architecture

**Contract.** SRS-native resources — tenants, users, credentials, products, events, submissions, training jobs, dataset snapshots, model versions, deployments, recommendations, feedback, usage, plans, audit. `snake_case`, `/v1`, colon-suffixed actions, `{error:{class, code, reason, reference}}`, business identifiers as idempotency keys, `limit`/`offset`+`total` for console lists and cursors for high-volume reads. `API.md`'s Personalize model is **not** built.

**Processes.** `control-api` (FastAPI modular monolith, 11 domain modules) · `job-worker` ×2 (CPU) · `training-worker` ×1 (GPU, concurrency 1) · `deployment-reconciler` (leader-locked) · `inference` (one warm process per active tenant, pinned by `GRAPHREC_TENANT_ID`).

**Data.** One PostgreSQL 16+ — system of record **and** job queue via `SELECT … FOR UPDATE SKIP LOCKED`. Shared schema, `tenant_id` everywhere, RLS with `FORCE`, non-owner runtime role, `SET LOCAL app.tenant_id` per transaction from the verified claim. 27 core tables. Composite `(tenant_id, id)` foreign keys. Partial unique indexes enforce one active training job per tenant, one active model version per tenant, one deployment per tenant. BRIN on interaction time; partition later only if measured need appears.

**Storage.** One S3-compatible store, `tenants/{tenant_id}/{uploads|snapshots|graphs|checkpoints|models}/`. Presigned URLs, single-key scope, 15-minute expiry. Bundles in **safetensors** with a SHA-256 digest and `tenant_id` in the manifest — never `pickle` across the worker→inference boundary.

**Cache.** One Redis: rate limits, semaphores, session context, deployment-binding cache, `jti` denylist. **Nothing authoritative.** Flushing it costs a cold cache and some session context, never consistency.

**Queue.** PostgreSQL `jobs` table. Leases with heartbeat, expiry-based crash recovery, exponential backoff on transient errors only, failed rows as the dead-letter queue, fair-share dispatch. No broker, no outbox, no publisher process.

**Training.** Plain PyTorch + PyTorch Geometric on one GPU. Nine stages: `queued → waiting_for_resources → preparing_data → building_graph → training → evaluating → indexing_embeddings → registering → succeeded`. Temporal leave-last-out split, BPR loss with popularity-corrected negatives, gated fusion of an edge-aware GNN pathway and a self-attention sequence pathway, per-epoch checkpointing, popularity baseline evaluated alongside every run.

**Serving.** One warm process per active tenant, holding resident item embeddings. Local Ed25519 verification — no control-plane call on the fast path. Four-stage funnel: multi-source candidate retrieval → eligibility filtering against a cached active-catalog bitmap → batched DGSR scoring → deterministic ordering with bounded, versioned diversity and freshness. Popularity fallback lane. `model_version` and `strategy` in every response. **Target P95 < 300 ms (NR-NF-04).**

**Deployment.** Docker Compose per node under systemd; images tagged by commit SHA; migrations first, then N1 → N3 → N2 with smoke tests between. A `ServingDriver` port carries the Compose ↔ k3s choice so the scaling demonstration (XR-F-08) does not make Kubernetes a day-one dependency.

**Security.** Isolation in depth — query, RLS, schema-level composite keys, storage prefixes, cache prefixes, process pinning, manifest verification. `404` for foreign resources. Immutable ledgers. One-time secrets. Two authentication realms.

**Observability.** Prometheus + Grafana; structured logs with `request_id`; audit and security-event tables; alerts on inference P95, fallback rate, queue depth, job failure rate, disk and per-tenant readiness. Measurement gaps reported as gaps.

### The one thing to be honest about

This architecture has **no high availability**, and that is not an oversight — CON-05 states the platform is *"a limited-capacity educational system, not a production-ready high-availability service"*, and CON-03 caps it at three nodes. Every node is a single point of failure for what it owns; losing the serving node takes recommendations down completely. The correct response is to say so plainly, keep tested backups, and know that the first additional machine should run a PostgreSQL replica and a second inference process. Everything here is designed so that adding it is a deployment change, not a rewrite.

---

## Implementation Sequence

A linear, checkable sequence. Steps 0.1–0.4 are decisions, not code, and everything downstream depends on them.

**Step 0 — Decide before writing code**
0.1 Resolve **§7 Q1** (SRS-native vs Personalize contract). Record as ADR-001. **Blocking.**
0.2 Resolve **Q2** (queue), **Q3** (orchestration), **Q4** (vector store), **Q5** (token scheme). ADR-002…005.
0.3 Confirm **A5** (email delivery exists) and the **§7.3** open items: cooldown, last-admin rule, customer lifecycle.
0.4 Report the **four SRS defects (§7.2)** to the supervisor.
0.5 Freeze `§3.4` enumerations as the shared vocabulary; generate the backend enum types from them.

**Step 1 — Foundation (Phase 1)**
1.1 Scaffold `apps/` + `graphrec/` per §20. 1.2 Pydantic Settings covering the full §22.4 surface. 1.3 Structured logging with `request_id`. 1.4 Error envelope + copy catalogue (§17.5). 1.5 Compose: Postgres, Redis, object store, API, `migrate`. 1.6 Alembic wired to the existing `alembic.ini`; create `graphrec_owner` and `graphrec_app`. 1.7 CI: ruff, mypy, pytest, migration up/down. 1.8 `/healthz`, `/readyz`.

**Step 2 — Identity, tenancy, RLS (Phase 2) — the hard prerequisite**
2.1 Migration: tenants, tenant_users, platform_users + permissions, invitations, refresh_sessions, recovery_tokens, plans, subscriptions, quotas, overrides. 2.2 **RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK` on every tenant table.** 2.3 `tenant_context.py` — `SET LOCAL app.tenant_id` from the verified claim only. 2.4 Ed25519 keypair, JWKS endpoint, claim schema. 2.5 Argon2id. 2.6 `deps.py` implementing gates 1–4 in order. 2.7 Endpoints: `POST /v1/tenants`, `/v1/auth/*`, `/v1/platform/auth/*`, `/v1/invitations:accept`, `GET /v1/tenant`, `/v1/me`, `/v1/users*`. 2.8 Last-active-administrator rule under a row lock. 2.9 **Isolation suite v1 + authorization matrix. Wire both as required CI gates.**
→ *Serves `/register`, `/login`, `/admin/login`, `/invite/accept`, `/recover*`, `/account`, `/account/tenant-status`, `/users*`.*

**Step 3 — Credentials (Phase 3)**
3.1 `api_keys` + `scopes` migration. 3.2 HMAC-SHA-256 generation and verification with versioned pepper. 3.3 Create / list / describe / rotate (with grace) / revoke. 3.4 Scope enforcement in `deps.py`; scope-delegation refusal. 3.5 `GET /v1/scopes`.
→ *Serves `/credentials` and `/integration`.*

**Step 4 — Job system (Phase 4)**
4.1 `jobs` migration with the partial claim index. 4.2 Claim query with `FOR UPDATE SKIP LOCKED`, fair-share ordering. 4.3 Lease, heartbeat, expiry sweeper. 4.4 Retry classifier (transient vs deterministic). 4.5 Cooperative cancellation at stage boundaries. 4.6 `job_worker` claim loop. 4.7 Concurrency and crash-recovery tests.

**Step 5 — Catalog (Phase 5)**
5.1 `products`, `product_categories` migration with the partial eligibility index. 5.2 **The shared eligibility predicate — one function, used by the API and by serving.** 5.3 `POST` (409 on duplicate), `PUT`, `PATCH`, `GET`, `:disable` (reason required). 5.4 Product-count quota with the counts in the message.
→ *Serves `/products`, `/products/new`, `/products/:productId`.*

**Step 6 — Ingestion (Phase 6)**
6.1 `customers`, `interaction_events`, `submissions`, `submission_errors` migration; `UNIQUE(tenant_id, external_event_id)`. 6.2 `POST /v1/events` with `duplicate_confirmed`. 6.3 `POST /v1/events/batches` and `POST /v1/products:bulk-upsert` → `202` + submission + job. 6.4 Worker handlers: streaming, bounded-memory validation; staging then a single merge transaction; capped error samples. 6.5 **Unified `GET /v1/submissions/{id}`** + the `/events/batches/{id}` alias.
→ *Serves `/events/submit`, `/products/sync`, `/submissions/:id`.*

**Step 7 — Metering (Phase 7)**
7.1 `usage_events` (INSERT-only grant) and `monthly_usage_aggregates` migration. 7.2 Redis fast counters + durable ledger + reconciliation rollup job. 7.3 Effective-limit resolution: plan, then active override. 7.4 `GET /v1/usage`, `/trends`, `/subscription` — **with `measurement_status`, never a substituted zero.** 7.5 Quota checks inside creating transactions.
→ *Serves `/usage`.*

**Step 8 — DGSR offline (Phase 8) — parallelisable from Step 1**
8.1 `FeatureBuilder`. 8.2 Graph construction + bounded 2-hop sampling. 8.3 DGSR model: GNN pathway, sequence pathway, gated fusion. 8.4 Training loop, negative sampling, BPR, checkpointing. 8.5 **Temporal leave-last-out split.** 8.6 Metrics + popularity baseline. 8.7 Fixture dataset, deterministic seed, leakage test.

**Step 9 — Training jobs (Phase 9)**
9.1 `models`, `training_jobs`, `dataset_snapshots`, `training_metrics` migration; **partial unique for one active job per tenant.** 9.2 `training_worker` implementing the nine stages, writing `progress` and `stage_index` at each. 9.3 `POST /v1/training-jobs` with all four admission checks at enqueue. 9.4 `GET /v1/training-jobs/eligibility`. 9.5 `GET /v1/training-jobs/{id}` with the stage rail contract. 9.6 `:cancel` with a required reason. 9.7 `GET /v1/datasets/snapshots/{id}`. 9.8 Checkpoint resume test.
→ *Serves `/training`, `/training/:jobId`.*

**Step 10 — Registry (Phase 10)**
10.1 `model_versions`, `model_evaluation_metrics` migration; partial unique for one active version. 10.2 Bundle export: safetensors, manifest with `tenant_id` and digest. 10.3 `CandidateIndex` port + in-process adapter; the `indexing_embeddings` stage builds and uploads it. 10.4 Registration step sets status `registered`, then `eligible` or `rejected` against the metric floor. 10.5 `GET /v1/model-versions`, `/summary`, `/{id}` with the three-way comparison and the `actions` precondition block. 10.6 `:archive` with rollback-target protection.
→ *Serves `/models`, `/models/:versionId`.*

**Step 11 — Serving (Phase 11)**
11.1 `model_deployments`, `deployment_revisions`, `serving_replicas`, `model_activation_history` migration. 11.2 `ServingDriver` port + Compose adapter. 11.3 `reconciler`: leader lock, desired→actual convergence, replica reporting, `ready ≥ 1` floor. 11.4 `inference`: pinned tenant, local verification, bundle load with manifest and digest verification. 11.5 The four-stage funnel; deterministic ordering; versioned ordering policy. 11.6 Fallback lanes. 11.7 `:activate` and `:rollback` with **load-before-swap** and previous-version retention. 11.8 `POST /v1/recommendations`, `/session`, `/feedback/*`. 11.9 `GET /v1/deployment*`, `/metrics/summary`, `/service-status/errors`. 11.10 Load test to NR-NF-04.
→ *Serves `/service-status` and the whole machine-facing product.*

**Step 12 — Audit and platform (Phase 12)**
12.1 `audit_logs`, `security_events` migration with append-only grants. 12.2 Audit writes on every ER-F-11 action. 12.3 `GET /v1/audit-logs` — tenant-scoped, redacted. 12.4 Platform permission dependency. 12.5 All 13 `/v1/platform/*` endpoints, including the **three-section composed tenant detail**. 12.6 `GET /v1/platform/status` with `measurement_gaps`.
→ *Serves `/audit` and all 8 `/admin/*` routes. **All 36 frontend routes are now backed.***

**Step 13 — Hardening (Phase 13)**
13.1 Per-node Compose + systemd (+ k3s profile if selected). 13.2 CI/CD with ordered deploys and smoke tests. 13.3 Firewall, private networking, secret management. 13.4 Backups + **a rehearsed restore drill**. 13.5 Dashboards and alerts. 13.6 Publish OpenAPI; verify it matches `/integration`. 13.7 Runbooks. 13.8 Failure drills, load test, security scan. 13.9 Walk the §24 checklist.

### Verification gates between steps

| After | Prove |
|---|---|
| Step 2 | A foreign resource returns `404`; RLS blocks a raw query without context; the authorization matrix passes; realms cannot cross |
| Step 4 | Two workers claim disjoint jobs; a killed worker's job requeues; a deterministic failure consumes no attempts |
| Step 6 | The same `event_id` twice yields one row and two successes; an oversize batch returns `413`; a partial failure keeps the accepted remainder |
| Step 7 | `UPDATE` on `usage_events` raises; a delayed measurement renders as a status, not a zero |
| Step 8 | Metrics beat the popularity baseline; the leakage test passes |
| Step 9 | Two concurrent training requests yield one job and one `409`; a crash resumes from the checkpoint |
| Step 10 | A corrupted bundle is refused at load; a foreign-tenant manifest is refused |
| Step 11 | A failed activation leaves the previous version serving; P95 < 300 ms under load; `ready ≥ 1` holds |
| Step 12 | Tenant audit never reveals another tenant; a partially-permitted platform user sees withheld sections, not a `403` |
| Step 13 | A restore drill reproduces verified row counts |

---

### Sources

All conclusions above trace to files in this workspace:

- `docs/BSSE1415_SPL3_mid.docx` — the SRS (§1–§6, Tables 1–41, UC-01…UC-31, entities §5.2.1–§5.2.16, Qdrant contract §6.3)
- `Design system decision pending/GraphRec Console.dc.html` — the frontend prototype (L620–1856)
- `Design system decision pending/ROUTES.md` — prototype route, role and gate map
- `ROUTES.md` — route tree with SRS traceability and the "Beyond the SRS" defect analysis
- `docs/FRONTEND_BUILD_PROMPT.md` — build brief; §2b recovered endpoint inventory
- `docs/GraphRec_Ultimate_Architecture.md` — §4, §12, §20–§27, §35, §39, §40
- `SYSTEM_DESIGN.md` — §7–§10, §15–§16, §23, §26–§32, §39–§40, §48–§50
- `API.md` — §1–§27 (assessed as conflicting; see §7 Q1)
- `docs/PROJECT_OVERVIEW.md` — prior-implementation record
- `alembic.ini`, `.env`, `.env.example`, `.dockerignore`, `.gitignore`, `.git/` state
