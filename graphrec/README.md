# GraphRec

**A multi-tenant, graph-based sequential recommendation platform for e-commerce.**

GraphRec lets online stores ingest product catalogs and user interaction streams, train or import tenant-specific **DGSR** (*Dynamic Graph Neural Networks for Sequential Recommendation*) models, manage model versions, and serve low-latency Top-N recommendations through a REST API or the shared Python SDK.

## Key Features

- **Strict multi-tenancy**: PostgreSQL 17 with forced Row-Level Security (RLS) on every tenant-owned table and a non-superuser runtime role (`graphrec_app`).
- **Sequential, time-aware recommendations**: PyTorch implementation of DGSR capturing both long-term user preferences and short-term session intent, with popularity fallback and configurable diversity/freshness rules.
- **Scoped access model**: Three distinct surfaces — Storefront (`ApiKey` with granular scopes), Tenant Admin/Developer (JWT with single-use refresh rotation), and Platform Operator (attributed operator accounts and bootstrap token).
- **Async training & scheduling**: Background worker (`graphrec_core.dgsr.worker`) for DGSR training/checkpoint import and scheduler (`graphrec_core.scheduler`) for retraining policies and capacity control.
- **Vector retrieval**: Qdrant collections scoped per tenant and model version.
- **Operator console & developer portal**: React 19 + TypeScript + Vite web application (`web/`) covering tenant onboarding, catalog, events, datasets, training jobs, model lifecycle, usage/quotas, platform administration, and generated API/SDK documentation.
- **Production readiness**: Redis-backed rate limiting and admission control, structured JSON logging, `/healthz`, `/readyz`, `/metrics`, and a Caddy TLS production Compose overlay.

## Architecture

```text
graphrec/
├── apps/api/           # FastAPI app, middleware, body limits, error envelopes, routes
├── graphrec_core/      # Domain services (auth, api_keys, billing, catalog, events,
│                       # datasets, dgsr, models_reg, serving, scheduler, vector_store)
├── migrations/         # Alembic database migrations
├── infrastructure/     # Postgres runtime role init script, Caddyfile
├── scripts/            # OpenAPI export, SDK doc-gen, backup/restore, retention, eval
├── tests/              # Unit, integration, and e2e test suites
├── web/                # React 19 + Vite operator console (served via nginx)
├── docs/               # Technical documentation, SRS, traceability, load benchmarks
├── model_artifacts/    # Local mount point for pretrained DGSR checkpoints (gitignored)
├── Dockerfile          # Multi-stage image (build, runtime, test)
├── docker-compose.yml  # Development stack (postgres, migrate, redis, qdrant, api, worker, scheduler, frontend)
└── docker-compose.prod.yml  # Production overlay (Caddy TLS, internal-only services, retention job)
```

## Quick Start (Docker Compose)

### Prerequisites

- Docker and Docker Compose

### Run the Stack

```bash
cd graphrec
cp .env.example .env
# Edit secrets in .env as needed (required when GRAPHREC_ENV=production)
docker compose up -d --build
```

Default local endpoints:

| Service | URL |
|---|---|
| Operator Console & Docs | `http://localhost:5180` |
| API | `http://localhost:8010` |
| Health / Readiness | `http://localhost:8010/healthz`, `http://localhost:8010/readyz` |
| Qdrant | `http://localhost:6333` |

## Local Development (Without Docker for API/Web)

### Backend

Requires Python 3.12+ and running PostgreSQL, Redis, and Qdrant instances (which can be started via `docker compose up -d postgres redis qdrant`).

```bash
cd graphrec
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1"
pip install -c constraints.txt -e ".[test]" -e ../sdks/python
alembic upgrade head
uvicorn apps.api.main:app --reload --port 8010
```

Background processes:
- Training worker: `python -m graphrec_core.dgsr.worker`
- Retraining & capacity scheduler: `python -m graphrec_core.scheduler`

### Web Console

Requires Node.js 22+.

```bash
cd graphrec/web
npm ci
npm run dev    # http://localhost:5173 (proxies /v1 to http://localhost:8010)
```

## Environment Configuration

All settings are documented in [`.env.example`](.env.example) and validated by `graphrec_core.settings.Settings` (verified by `tests/test_config_surface.py`). Key variables include:

- `GRAPHREC_ENV` (`development` or `production`)
- `POSTGRES_DB`, `POSTGRES_OWNER_USER`, `POSTGRES_OWNER_PASSWORD`, `POSTGRES_APP_PASSWORD`
- `JWT_SIGNING_SECRET`, `AUDIT_HASH_SECRET`, `API_KEY_HMAC_PEPPER`
- `PLATFORM_ADMIN_TOKEN`
- `REDIS_URL`, `QDRANT_URL`
- `MODEL_ARTIFACT_DIR` (host directory mounted at `/artifacts` inside the API container)

## API & Python SDK

The HTTP API is versioned under `/v1` with a consistent JSON error envelope and `X-Correlation-ID` propagation. See [`docs/API.md`](docs/API.md) for endpoint details and [`../sdks/python/README.md`](../sdks/python/README.md) for the Python client:

```python
from graphrec_sdk import GraphRec

client = GraphRec(base_url="http://localhost:8010", api_key="gr_live_...")
client.storefront.events.record(
    event_id="evt_001",
    user_id="u_42",
    product_id="item_318",
    event_type="view",
)
recs = client.storefront.recommendations.for_user(user_id="u_42", limit=10)
```

## Testing

```bash
# Backend unit & integration tests (requires Compose Postgres, Redis, Qdrant)
cd graphrec
python -m pytest -q tests --ignore=tests/e2e

# Or inside Docker Compose:
docker compose --profile test run --rm api-test

# OpenAPI & SDK documentation drift checks
python scripts/export_openapi.py --check web/openapi.json
python scripts/build_sdk_docs.py --check
python scripts/check_doc_sdk_calls.py

# Web console typecheck, unit tests, and production build
cd web
npm run check:api
npx tsc -b --noEmit
npx vitest run
npm run build
```

## Deployment & Operations

Production deployment uses `docker-compose.prod.yml` with Caddy automatic TLS and internal-only database/API networking:

```bash
cd graphrec
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Detailed guides:
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Production deployment, TLS, backups, and upgrades
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — Monitoring, metrics, retention, and runbooks
- [`docs/SECURITY.md`](docs/SECURITY.md) — Authentication, RLS, secrets, and rate limiting
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — Serving latency and load test benchmarks
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — Recorded architectural decisions
- [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md) — Automated SRS requirement traceability
