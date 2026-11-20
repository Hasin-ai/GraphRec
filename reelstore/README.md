# ReelStore

**A MovieLens reference film storefront demonstrating GraphRec and DGSR end to end.**

ReelStore is a standalone FastAPI + React 19 storefront that integrates with GraphRec the way a real e-commerce application does: the browser talks only to ReelStore (`/api/reel/*`), while the backend holds the tenant's storefront API key and calls GraphRec through the shared Python SDK (`sdks/python`).

A built-in **Insight** drawer exposes what GraphRec did on every interaction: the 20-film sequential window read by DGSR, event receipts and idempotency checks, before/after recommendation list diffs, raw API request/response traces, deep readiness probes, and an on-demand 19-check **Capability Proof Battery**.

```text
Browser -> /api/reel/* (ReelStore :5290) -> graphrec-sdk -> GraphRec /v1/* (:8010) -> DGSR
```

## Key Features

- **Real data throughout**: 7,951 films from the DGSR MovieLens vocabulary with real titles, genres, and community tags, plus real MovieLens training users as demo personas.
- **Authoritative history & Redis shared state**: Shopper history is read from GraphRec's event API; shelf diffs and impression links persist in Redis across workers and restarts.
- **Interactive Insight drawer**: Sequence window inspection, event replay (`duplicate` idempotency check), shelf diffing, raw payload trace, readiness/feedback health, and live capability proofs.
- **Optional S3 cover storage**: Supports serving film covers via RustFS (`/reel-covers` same-origin proxy).
- **Independent deployment**: Has its own Dockerfile, Compose project, Python dependencies, React frontend, test suite, and operations documentation.

## Layout

```text
reelstore/
├── app/                # FastAPI backend: routes, GraphRec SDK client, Redis storage,
│                       # observability, and capability proof battery (app/proof/)
├── frontend/           # React 19 + TypeScript + Vite storefront UI & Insight drawer
├── data/               # films.json, personas.json, model_card.json, covers.json
├── scripts/            # bootstrap_reel.py, build_data.py, upload_covers.py,
│                       # prove_graphrec.py, e2e_check.py, offline_standin.py
├── tests/              # Unit and contract tests (mocked GraphRec client)
├── e2e/                # Playwright end-to-end specs for ReelStore
├── docs/               # DEPLOYMENT.md and OPERATIONS.md
├── Dockerfile          # Multi-stage build (builds frontend + installs sdks/python)
└── docker-compose.yml  # Standalone Compose stack joining GraphRec's Docker network
```

## Quick Start (Docker Compose)

ReelStore runs as its own Compose project (`name: reel`) and joins the running GraphRec Docker network. Run these commands from the **repository root**:

```bash
# 1. Start the GraphRec stack first
docker compose -f graphrec/docker-compose.yml up -d --build

# 2. Bootstrap tenant, catalog, persona histories, and checkpoint -> reelstore/.env
docker compose -f reelstore/docker-compose.yml --env-file graphrec/.env run --rm reel-bootstrap

# 3. Start ReelStore on http://localhost:5290
docker compose -f reelstore/docker-compose.yml up -d --build reel
```

Optional film covers via RustFS (console at `http://localhost:9001`):

```bash
docker compose -f reelstore/docker-compose.yml up -d rustfs
docker compose -f reelstore/docker-compose.yml run --rm reel-covers
docker compose -f reelstore/docker-compose.yml up -d --build reel
```

Notes:
- Re-run `reel-bootstrap` to reset the demo with a fresh tenant, then restart `reel` to pick up the new API key.
- Stop ReelStore without affecting GraphRec: `docker compose -f reelstore/docker-compose.yml down`.
- Override the port with `REEL_PORT` or the GraphRec Docker network name with `GRAPHREC_NETWORK` (defaults to `graphrec_default`).

## Local Development (Without Docker)

Requires Python 3.10+, Node.js 22+, and a running GraphRec API instance.

```bash
# 1. Install backend dependencies and the shared Python SDK
cd reelstore
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]" -e ../sdks/python

# 2. Bootstrap a tenant against local GraphRec (writes reelstore/.env)
python scripts/bootstrap_reel.py --platform-token <PLATFORM_ADMIN_TOKEN>
# Add --train if graphrec/model_artifacts/dgsr_movielens_32m is not present on this host.

# 3. Build frontend and run the server
cd frontend && npm ci && npm run build && cd ..
uvicorn app.main:app --port 5290
```

For frontend hot reload during development:
```bash
cd reelstore/frontend
npm run dev    # http://localhost:5291 (proxies /api/reel to :5290)
```

## Environment Configuration

See [`.env.example`](.env.example). Key variables written by `scripts/bootstrap_reel.py`:

- `GRAPHREC_BASE_URL` — GraphRec API origin (`http://api:8000` in Docker, `http://localhost:8010` on host)
- `GRAPHREC_API_KEY` — Storefront API key (never exposed to the browser)
- `REEL_TENANT_NAME`, `REEL_MODEL_VERSION_ID`, `REEL_MODEL_VERSION_TAG`
- `REEL_PORT` (default `5290`)
- `REEL_COVERS_BASE_URL` (default `/reel-covers`; empty disables cover images)

## Testing & Verification

```bash
# Backend unit & regression tests
cd reelstore
python -m pytest -q tests

# Frontend typecheck, OpenAPI drift check & production build
cd reelstore/frontend
npm run check:api
npm run build

# CLI capability proof battery (against a running ReelStore + GraphRec stack)
cd reelstore
python scripts/prove_graphrec.py --profile full

# Playwright browser E2E tests (against a running ReelStore instance)
npx playwright test -c reelstore/e2e/playwright.config.ts
```

## Documentation

- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Production deployment, secrets, and network topology
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — Runbooks for GraphRec outages, rate limits, key rotation, and model rollbacks
