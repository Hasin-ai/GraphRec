# GraphRec — Project Overview

> A production-grade, multi-tenant recommendation platform powered by a Dynamic Graph Neural Network (DGSR-lite) with strict per-tenant data isolation, a full ML training pipeline, and real-time inference.

---

## Table of Contents

1. [What is GraphRec?](#1-what-is-graphrec)
2. [Architecture at a Glance](#2-architecture-at-a-glance)
3. [Core Technology Stack](#3-core-technology-stack)
4. [Repository Layout](#4-repository-layout)
5. [Domain Model & Database](#5-domain-model--database)
6. [API Surface](#6-api-surface)
7. [ML Pipeline — Offline Training](#7-ml-pipeline--offline-training)
8. [ML Pipeline — Online Inference](#8-ml-pipeline--online-inference)
9. [Security Model](#9-security-model)
10. [Frontend Control Panel](#10-frontend-control-panel)
11. [Running Locally](#11-running-locally)
12. [Testing](#12-testing)
13. [Configuration Reference](#13-configuration-reference)
14. [Development Roadmap](#14-development-roadmap)

---

## 1. What is GraphRec?

GraphRec is a **multi-tenant, SaaS recommendation-as-a-service platform**. Tenants (businesses) onboard, upload their product catalogs and user-event streams, trigger model training, and then call a single recommendations endpoint from their own applications to receive personalised Top-N item lists in real time.

The recommendation engine is based on **DGSR-lite** — a simplified variant of the *Dynamic Graph Neural Network for Sequential Recommendation* model, implemented with **PyTorch Geometric (PyG)**. It models users and items as nodes in a time-stamped interaction graph, learning both long-range preference patterns and short-term session context.

Key product properties:

| Property | Detail |
|---|---|
| **Multi-tenancy** | Complete data isolation via PostgreSQL Row-Level Security (RLS); every query is automatically scoped to the authenticated tenant. |
| **Subscription tiers** | Plan-based quota enforcement on API calls, training jobs, and resource limits. |
| **Immutable audit ledger** | `usage_events` table is INSERT-only; no runtime role may UPDATE or DELETE records. |
| **One-time secrets** | API keys are shown once on creation/rotation and stored only as HMAC-SHA-256 verifiers — never in plaintext. |
| **Versioned model registry** | Every trained model is registered as an immutable version; tenants promote versions to production explicitly. |

---

## 2. Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────┐
│  Tenant Applications & Admin Dashboard (React / Vite SPA)   │
└──────────────────┬───────────────────────────────────────────┘
                   │  HTTPS
┌──────────────────▼───────────────────────────────────────────┐
│              FastAPI Gateway  (apps/api)                     │
│  Auth · Tenants · API-Keys · Datasets · Events · Products    │
│  Training Jobs · Model Registry · Deployment · Recommendations│
└──┬───────────────┬──────────────────────────────────────────┘
   │               │
   ▼               ▼
PostgreSQL     RabbitMQ Message Broker
(RLS-enforced) ──► Celery Training Workers ──► RustFS Object Storage
   ▲               │                               │
   │               ▼                               ▼
   └────── Model Registry ◄──────── Serving Bundle (weights, embeddings, mappings)
                   │
                   ▼
         Tenant-Pinned Inference Pods (Kubernetes)
         4-Stage Serving Funnel → Top-N JSON Response
```

**Data flows:**

1. **Ingest** — tenant apps push product catalogs (`POST /v1/products`) and behavioural events (`POST /v1/events`) through the gateway, stored in PostgreSQL under RLS.
2. **Train** — admin triggers `POST /v1/training-jobs`; the outbox scheduler dispatches a Celery task; a worker acquires a Redis lock, snapshots the tenant's data, builds a PyG graph, trains DGSR-lite, evaluates metrics, and stores an immutable serving bundle in RustFS.
3. **Activate** — admin promotes a model version (`POST /v1/deployments`); the deployment controller reconciles a Kubernetes pod per tenant.
4. **Recommend** — applications call `POST /v1/recommendations`; the pinned inference pod runs the 4-stage serving funnel (retrieval → filtering → scoring → re-ranking) and returns results in <300 ms P95.

---

## 3. Core Technology Stack

| Layer | Technology |
|---|---|
| **Runtime language** | Python 3.12 |
| **API framework** | FastAPI + Uvicorn |
| **Database** | PostgreSQL 17 with Row-Level Security |
| **ORM / migrations** | SQLAlchemy 2 + Alembic |
| **Message broker** | RabbitMQ |
| **Task queue** | Celery |
| **Cache / distributed locks** | Redis |
| **Object storage** | RustFS (S3-compatible) |
| **ML framework** | PyTorch + PyTorch Geometric (PyG) |
| **Container orchestration** | Docker Compose (local) / Kubernetes (production) |
| **Frontend** | React 18 + Vite + TypeScript |
| **Frontend styling** | Vanilla CSS (DigitalOcean-style control panel) |
| **Settings** | Pydantic Settings (env-file driven) |
| **Testing — backend** | Pytest + HTTPX TestClient (57 tests) |
| **Testing — frontend** | Vitest + React Testing Library (22 tests) |

---

## 4. Repository Layout

```
GraphRec/
├── apps/
│   └── api/                    # FastAPI application
│       ├── main.py             # App factory, middleware, router registration
│       ├── middleware.py       # Rate limiting, request-size guard, CORS
│       ├── errors.py           # Unified RFC 7807 error responses
│       └── routes/             # One module per resource domain
│           ├── auth.py         # POST /v1/auth/login, /v1/auth/refresh
│           ├── tenants.py      # POST /v1/tenants (registration)
│           ├── subscriptions.py# GET  /v1/subscription
│           ├── usage.py        # GET  /v1/usage
│           ├── api_keys.py     # Full API-key lifecycle
│           ├── datasets.py     # Dataset upload & listing
│           ├── products.py     # Product catalog upsert & listing
│           ├── events.py       # Behavioural event ingestion
│           ├── model_versions.py # Model registry reads
│           ├── deployment.py   # Deployment activation & status
│           ├── recommendations.py # Top-N inference endpoint
│           └── platform.py     # Health-check, admin platform ops
│
├── graphrec_core/              # Shared library (installed into all containers)
│   ├── auth/                   # JWT issue/verify, principal resolution
│   ├── api_keys/               # HMAC key generation & verification
│   ├── catalog/                # Product catalog domain logic
│   ├── database/               # SQLAlchemy engine, RLS helpers, session factory
│   ├── datasets/               # Dataset snapshot logic
│   ├── events/                 # Event batch processing
│   ├── models_reg/             # Model version registration
│   ├── registration/           # Tenant & user onboarding
│   ├── subscription/           # Plan & quota enforcement
│   ├── usage/                  # Usage ledger writes
│   └── schemas/                # Pydantic request/response models
│
├── migrations/
│   └── versions/               # 8 Alembic migrations (0001–0008)
│
├── frontend/
│   └── src/
│       ├── api/                # Typed fetch clients per domain
│       ├── auth/               # Token storage, auth context
│       ├── components/         # Navbar (topbar + sidebar), shared UI
│       ├── pages/              # One page component per route
│       └── styles.css          # Global design system (DO-style tokens)
│
├── docs/                       # Architecture docs, SRS, pipeline diagrams
├── infrastructure/             # Postgres init scripts, Kubernetes manifests
├── scripts/                    # CLI utilities (demo account bootstrap)
├── tests/                      # Integration test suites
└── docker-compose.yml          # Full local stack definition
```

---

## 5. Domain Model & Database

The schema is built up across 8 Alembic migrations:

| Migration | Tables introduced |
|---|---|
| `0001` | `tenants`, `tenant_users`, `invited_admins` |
| `0002` | `refresh_sessions` |
| `0003` | `subscription_plans`, `tenant_subscriptions` |
| `0004` | `usage_events` (immutable ledger) |
| `0005` | `api_keys` |
| `0006` | Index on `api_keys.key_hash` |
| `0007` | `allow_password_setup` column on `invited_admins` |
| `0008` | `products`, `customer_events`, `event_batches`, `model_versions`, `training_jobs`, `dataset_snapshots` |

**Row-Level Security** is the central isolation mechanism. Every table that holds tenant data has a policy of the form:

```sql
CREATE POLICY tenant_isolation ON products
  USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

The runtime database role (`graphrec_app`) cannot bypass RLS. Only the owner role used by migrations can do so.

---

## 6. API Surface

All protected endpoints require a `Bearer <JWT>` access token or a scoped API key in the `Authorization` header.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/tenants` | Register a new tenant organisation |
| `POST` | `/v1/auth/login` | Exchange credentials for access + refresh tokens |
| `POST` | `/v1/auth/refresh` | Rotate refresh token, get new access token |
| `GET` | `/v1/subscription` | Current plan limits and features |
| `GET` | `/v1/usage` | Reconciled month-to-date usage and remaining quota |
| `GET/POST` | `/v1/api-keys` | List / create scoped API keys |
| `GET/POST/DELETE` | `/v1/api-keys/{id}` | Inspect / rotate / revoke an API key |
| `POST` | `/v1/products/batch` | Upsert product catalog items |
| `GET` | `/v1/products` | List active products |
| `POST` | `/v1/events/batch` | Submit user behavioural event batch |
| `GET` | `/v1/datasets` | List dataset snapshots |
| `POST` | `/v1/training-jobs` | Enqueue a new model training job |
| `GET` | `/v1/training-jobs/{id}` | Training job status and metrics |
| `GET` | `/v1/model-versions` | List registered model versions |
| `GET` | `/v1/model-versions/{id}` | Inspect a model version |
| `POST` | `/v1/deployments` | Activate a model version for inference |
| `GET` | `/v1/deployments/active` | Current active deployment state |
| `POST` | `/v1/recommendations` | Get Top-N personalised recommendations |
| `GET` | `/healthz` | Platform health-check (unauthenticated) |

---

## 7. ML Pipeline — Offline Training

Training is fully asynchronous. Submitting `POST /v1/training-jobs` returns `202 Accepted`; actual work is performed by a Celery worker after being dispatched via RabbitMQ.

**Worker execution stages:**

1. **Data Snapshot** — Reads tenant's `customer_events` and `products` under RLS. Deduplicates, sorts chronologically, filters disabled products, and uploads a reproducible dataset snapshot to RustFS (`tenants/{id}/datasets/{snapshot_id}/`).

2. **Graph Construction** — Builds user and item node mappings. Creates timestamped interaction edges. Applies 2-hop bounded neighbourhood sampling (N=20 recent items, M=10 neighbour users).

3. **DGSR-lite Training** — Runs PyTorch Geometric message-passing rounds. Fuses long-range preference embeddings with short-term session context. Optimises BPR / Sampled Softmax loss. Saves periodic checkpoints to RustFS. Evaluates `Recall@10`, `HR@10`, `NDCG@10`, and item Coverage.

4. **Serving Bundle Export** — Uploads an immutable bundle to `tenants/{id}/models/{model_id}/{version}/`:

   | Artifact | Purpose |
   |---|---|
   | `weights.safetensors` | GNN model parameters |
   | `item_embeddings.safetensors` | Pre-extracted item embedding matrix |
   | `item_neighbors.parquet` | Precomputed nearest-item lookup |
   | `user_mapping.parquet` / `item_mapping.parquet` | ID conversion tables |
   | `feature_schema.json` | Normalisation params, vocabularies |
   | `popular_and_category_lists.json` | Cold-start fallback candidates |
   | `ordering_policy.json` | Versioned re-ranking business rules |
   | `manifest.json` | SHA-256 checksums, tenant ID, Git SHA |

**Training job states:** `queued → preparing_data → building_graph → training → evaluating → registering → succeeded` (with `cancelling → cancelled` and `→ failed` exit paths at each stage).

---

## 8. ML Pipeline — Online Inference

Active tenants run a **dedicated Kubernetes Deployment** (pinned pod). Each pod uses an init container to download and verify the serving bundle from RustFS before the main process starts.

**Four-stage serving funnel** (target P95 < 300 ms):

| Stage | What happens |
|---|---|
| **1. Candidate Retrieval** | Up to 4 parallel sources: personalised vector dot-product Top-K, nearest items of recent user interactions, popularity/category lists, and metadata-similarity cold-start candidates. Union deduplication yields ~100–300 candidates. |
| **2. Eligibility Filtering** | Hard removal of disabled/deleted/out-of-stock items, caller-supplied exclusions, recently purchased items, and cross-tenant boundary violations. |
| **3. DGSR Scoring** | Batch GNN forward pass scores survivor candidates. Cold (unmapped) items are routed to a conservative popularity-based cold lane. |
| **4. Re-Ranking** | Stable tie-breaking by product ID. Category/brand caps. Maximal Marginal Relevance diversity boost and freshness boost. Returns Top-N JSON with model version ID and strategy metadata. |

Every served response triggers an async feedback event (impression/click) published to RabbitMQ for future retraining signals.

**Fallback chain:** Rate limit exceeded → `429`; capacity exhausted → `503` + popularity baseline; circuit breaker open → last-known-good cache hit.

---

## 9. Security Model

| Control | Implementation |
|---|---|
| **Authentication** | Short-lived JWT access tokens (15 min default) + long-lived refresh tokens (7 day default), both signed with `HS256`. |
| **API key credentials** | Generated as `grk_<random>`, stored exclusively as `HMAC-SHA-256(pepper, key)` verifier. Displayed once on creation/rotation. |
| **Authorisation** | Every protected route resolves `AuthenticatedPrincipal` via FastAPI dependency. The dependency decodes the bearer token, verifies tenant and user are active, and sets the PostgreSQL RLS session variable `app.current_tenant_id`. |
| **Row-Level Security** | All tenant data tables enforce RLS policies. The runtime DB role cannot `SET` the tenant variable outside a transaction or bypass the policy. |
| **Immutable ledger** | `GRANT SELECT, INSERT ON usage_events TO graphrec_app` — no `UPDATE` or `DELETE` ever granted. |
| **API key table** | `GRANT SELECT, INSERT, UPDATE ON api_keys TO graphrec_app` — `DELETE` withheld to prevent silent purging of audit records. |
| **Rate limiting** | Per-endpoint sliding-window rate limits configurable in `.env`. |
| **Request size guard** | Configurable `MAX_REQUEST_BODY_BYTES` middleware rejects oversized payloads before deserialization. |
| **CORS** | Restricted to configured origins; credentials flag enabled. |

---

## 10. Frontend Control Panel

The frontend is a React 18 + Vite + TypeScript single-page application styled after the DigitalOcean Cloud Console design language.

**Layout:**
- **Topbar** — white bar (`#ffffff`, border `#e5e8ed`) containing a resource-search input, a primary `Create ˅` button (`#0069ff`), notification and help icons, and a team dropdown.
- **Sidebar** — deep navy panel (`#041640`) with category groups: `PROJECTS`, `AI & INFERENCE`, `DATA SERVICES`. Active items show a `#0069ff` left-edge indicator.
- **Content area** — tabbed page layouts with resource tables, status badges, and right-hand summary cards.

**Pages:**

| Route | Description |
|---|---|
| `/auth/login` | Credential sign-in form |
| `/auth/register` | Tenant registration form |
| `/app` | Project overview dashboard (resources, activity feed) |
| `/app/subscription` | Plan details and feature entitlements |
| `/app/usage` | Month-to-date usage metrics and quota bars |
| `/app/integration/api-keys` | API key list, create, rotate, revoke |
| `/app/data` | Dataset upload and snapshot listing |
| `/app/data/products` | Product catalog management |
| `/app/data/events` | Behavioural event submission |
| `/app/models` | Model version registry |
| `/app/models/train` | Trigger a new training job |
| `/app/deployment` | Deployment activation and status |
| `/app/recommendations` | Interactive recommendations tester |

---

## 11. Running Locally

**Prerequisites:** Docker Desktop with Compose V2.

```bash
# 1. Clone and configure environment
git clone <repo-url> && cd GraphRec
cp .env.example .env          # Edit secrets before use in production

# 2. Start the full stack
docker compose up --build

# 3. Create a demo login credential (one-time)
docker compose --profile demo run --rm demo-account
```

| Service | URL |
|---|---|
| Frontend SPA | http://localhost:5180 |
| API (FastAPI) | http://localhost:8010 |
| API Health check | http://localhost:8010/healthz |
| API Docs (Swagger) | http://localhost:8010/docs |

Default demo credentials are set by `DEMO_LOGIN_EMAIL` and `DEMO_LOGIN_PASSWORD` in `.env`.

---

## 12. Testing

```bash
# Backend — 57 integration tests
docker compose exec api pytest tests/ -v

# Frontend — 22 unit/component tests + production build + audit
docker compose --profile test run --rm frontend-test
```

Test coverage includes:
- Tenant registration and login flows
- Subscription plan enforcement
- Usage ledger immutability (`INSERT` succeeds; `UPDATE`/`DELETE` raise `DBAPIError`)
- API key full lifecycle (create, list, rotate, revoke, cross-tenant RLS blocking)
- Cross-tenant RLS isolation (foreign key IDs return `404`, not `403`, to prevent enumeration)
- Dataset upload, product upsert, event batch submission
- Model version registration and training job schema validation

---

## 13. Configuration Reference

All settings are read from environment variables (`.env` file). Key variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `JWT_SIGNING_SECRET` | — | HS256 signing key (min 32 chars) |
| `AUDIT_HASH_SECRET` | — | HMAC secret for audit record hashing |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | JWT access token lifetime |
| `REFRESH_TOKEN_TTL_SECONDS` | `604800` | Refresh token lifetime (7 days) |
| `API_KEY_HMAC_PEPPER` | — | HMAC pepper for API key verifiers |
| `MAX_ACTIVE_API_KEYS_PER_TENANT` | `25` | Hard cap per tenant |
| `LOGIN_RATE_LIMIT` | `8` | Max login attempts per window |
| `REGISTRATION_RATE_LIMIT` | `5` | Max registrations per window |
| `MAX_REQUEST_BODY_BYTES` | `16384` | Request body size limit |
| `API_PORT` | `8010` | Host port for the API container |
| `FRONTEND_PORT` | `5180` | Host port for the frontend container |

---

## 14. Development Roadmap

Completed vertical slices (in merge order):

- [x] **0001** Tenant registration
- [x] **0002** Tenant-user sign-in and JWT session management
- [x] **0003** Subscription plan overview
- [x] **0004** Usage reconciliation and immutable ledger
- [x] **0005** API-key full lifecycle (create / list / rotate / revoke)
- [x] **0006** API-key lookup performance index
- [x] **0007** Password setup gate
- [x] **0008** Domain pipeline tables (products, events, datasets, model versions, training jobs)

Planned next slices:

- [ ] Celery worker implementation and RabbitMQ integration
- [ ] RustFS integration and dataset upload to object storage
- [ ] DGSR-lite model training and evaluation harness
- [ ] Model serving bundle export and registry promotion
- [ ] Kubernetes deployment controller and inference pod spec
- [ ] Real-time inference endpoint with 4-stage serving funnel
- [ ] Tenant-facing analytics and recommendation feedback loop
