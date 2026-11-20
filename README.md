# GraphRec & ReelStore

A multi-tenant, graph-based sequential recommendation platform (**GraphRec**), its typed client library (**Python SDK**), and its production-grade reference storefront (**ReelStore**).

> Developed as the Software Project Lab III (SPL-3) project at the Institute of Information Technology (IIT), University of Dhaka.

## Projects in This Repository

| Project | Directory | Purpose |
|---|---|---|
| **GraphRec** | [`graphrec/`](graphrec/README.md) | Multi-tenant recommendation platform: FastAPI API, DGSR PyTorch training/serving engine, background worker & scheduler, PostgreSQL (with forced RLS), Redis, Qdrant, and React 19 operator console. |
| **ReelStore** | [`reelstore/`](reelstore/README.md) | Independent MovieLens film storefront (FastAPI + React 19) that integrates with GraphRec via the Python SDK, with an interactive Insight drawer and on-demand capability proof battery. |
| **Python SDK** | [`sdks/python/`](sdks/python/README.md) | Shared typed client library (`graphrec-sdk`) covering storefront, tenant admin, and platform admin API surfaces. |

## How GraphRec and ReelStore Relate

ReelStore is a standalone client application that consumes GraphRec strictly over HTTP through the shared Python SDK (`sdks/python`), mirroring how any external e-commerce storefront integrates with GraphRec:

```text
┌───────────────────────────┐        ┌────────────────────────────┐
│  ReelStore (reelstore/)   │        │  GraphRec Console          │
│  React 19 + FastAPI :5290 │        │  (graphrec/web/) :5180     │
└─────────────┬─────────────┘        └──────────────┬─────────────┘
              │ graphrec-sdk (ApiKey)               │ REST (JWT / Bearer)
              └──────────────────┬──────────────────┘
                                 ▼
                  ┌─────────────────────────────┐
                  │  GraphRec API (graphrec/)   │
                  │  FastAPI :8010 + DGSR       │
                  └───┬──────────┬──────────┬───┘
                      │          │          │
              ┌───────▼──┐  ┌────▼───┐  ┌───▼────┐
              │PostgreSQL│  │ Qdrant │  │ Redis  │
              │  (RLS)   │  │ (ANN)  │  │(limits)│
              └───────▲──┘  └────▲───┘  └────────┘
                      │          │
              ┌───────┴──────────┴───────┐
              │ Worker & Scheduler (DGSR)│
              └──────────────────────────┘
```

Both projects have independent dependencies, Docker Compose stacks, test suites, and documentation. They share only the client SDK in `sdks/python/` and communicate over the HTTP API (or Docker network when running side by side).

## Repository Structure

```text
GraphRec/
├── graphrec/                  # GraphRec multi-tenant recommendation platform
│   ├── apps/api/              # FastAPI HTTP API & routers
│   ├── graphrec_core/         # Domain services, auth, billing, DGSR model & serving
│   ├── migrations/            # Alembic PostgreSQL migrations (with RLS)
│   ├── infrastructure/        # Postgres init scripts and production Caddyfile
│   ├── scripts/               # Operational, OpenAPI export, SDK doc-gen, and eval scripts
│   ├── tests/                 # Unit, integration, and e2e test suites
│   ├── web/                   # React 19 + Vite operator console & docs portal
│   ├── docs/                  # Architecture, API, SRS, security, performance & ops docs
│   ├── Dockerfile             # Multi-stage API / worker / scheduler image
│   └── docker-compose.yml     # Full GraphRec stack (dev + prod overlay)
├── reelstore/                 # ReelStore reference MovieLens storefront
│   ├── app/                   # FastAPI BFF, Redis state store, proof battery, observability
│   ├── frontend/              # React 19 + Vite storefront UI & Insight drawer
│   ├── data/                  # MovieLens catalog, personas, model card, cover index
│   ├── scripts/               # Bootstrap, data build, cover upload, CLI capability proof
│   ├── tests/                 # Unit and contract tests
│   ├── e2e/                   # Playwright browser tests for ReelStore
│   ├── docs/                  # ReelStore deployment & operations runbooks
│   ├── Dockerfile             # Multi-stage ReelStore image
│   └── docker-compose.yml     # Standalone Compose project joining GraphRec's network
├── sdks/                      # Shared client SDKs
│   └── python/                # graphrec-sdk package, examples, unit & contract tests
├── .github/                   # CI/CD workflows, issue templates, PR template
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## Technology Stack

- **Backend API & Services**: Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2
- **ML Model**: PyTorch implementation of **DGSR** (*Dynamic Graph Neural Networks for Sequential Recommendation*, IEEE TKDE 2022)
- **Data & Infrastructure**: PostgreSQL 17 (forced Row-Level Security), Qdrant (vector search), Redis 7 (rate limits, slot leases, shared storefront state), RustFS (optional S3 cover storage for ReelStore)
- **Frontends**: React 19, TypeScript, Vite, Nginx (GraphRec console), Playwright & Vitest
- **Deployment**: Docker, Docker Compose, Caddy (production TLS overlay)

## Quick Start

### 1. Start GraphRec

```bash
cd graphrec
cp .env.example .env           # configure secrets as needed
docker compose up -d --build
```

Services started:
- **Operator Console & Docs**: `http://localhost:5180`
- **GraphRec API**: `http://localhost:8010`
- **Qdrant**: `http://localhost:6333`

### 2. Start ReelStore (Optional Reference Storefront)

With GraphRec running, bootstrap a ReelStore tenant and launch the storefront from the repository root:

```bash
docker compose -f reelstore/docker-compose.yml --env-file graphrec/.env run --rm reel-bootstrap
docker compose -f reelstore/docker-compose.yml up -d --build reel
```

ReelStore will be available at `http://localhost:5290`.

## Documentation

- **GraphRec Platform**: [graphrec/README.md](graphrec/README.md)
  - [API Reference](graphrec/docs/API.md) · [Deployment](graphrec/docs/DEPLOYMENT.md) · [Operations](graphrec/docs/OPERATIONS.md) · [Security](graphrec/docs/SECURITY.md) · [Performance](graphrec/docs/PERFORMANCE.md) · [Architecture Decisions](graphrec/docs/DECISIONS.md)
- **ReelStore Storefront**: [reelstore/README.md](reelstore/README.md)
  - [Deployment](reelstore/docs/DEPLOYMENT.md) · [Operations](reelstore/docs/OPERATIONS.md)
- **Python SDK**: [sdks/python/README.md](sdks/python/README.md)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md) · **Changelog**: [CHANGELOG.md](CHANGELOG.md)

## Acknowledgements

- Supervisor: **Dr. Rezvi Shahariar**, Associate Professor, IIT, University of Dhaka
- Author: **Hasin Ahmed** — BSSE, IIT, University of Dhaka
- Model reference: Zhang et al., *Dynamic Graph Neural Networks for Sequential Recommendation*, IEEE TKDE 2022
- Reference dataset: [MovieLens](https://grouplens.org/datasets/movielens/) by GroupLens Research
