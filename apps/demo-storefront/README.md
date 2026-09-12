# Facet — a GraphRec demonstration store

A small beauty storefront (FastAPI + React 19) that consumes GraphRec through
the Python SDK the way a real merchant would: the browser only ever talks to
this server, the server holds the API key, and every recommendation carries
its provenance (model version, strategy, fallback tier) so the demo never
claims more than the platform is doing.

```
browser  ->  /api/demo/*  (this server, port 5190)  ->  GraphRec /v1/* (port 8010)
```

## Run

```bash
# 1. GraphRec stack
docker compose up -d --build                    # from the repository root; API on :8010

# 2. storefront server
cd apps/demo-storefront
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]" -e ../../sdks/python
python scripts/bootstrap_tenant.py               # registers a tenant, writes GRAPHREC_* into .env
python scripts/seed.py                           # catalog, persona histories, snapshot, training, activation
uvicorn app.main:app --port 5190

# 3. frontend
cd frontend && npm install
npm run build                                    # served by the FastAPI app at http://localhost:5190
npm run dev                                      # or Vite on :5191, proxying /api/demo to :5190
```

`bootstrap_tenant.py` only ever *updates* `.env` (other keys are kept) and
prints nothing that is not also written there. Without a `.env` the server
refuses to start: `GRAPHREC_API_KEY` must be a real `gr_live_` key.

## What the demo shows

| Surface | Route | GraphRec calls |
|---|---|---|
| Catalog | `/` | `products` (cached 30 s), `recommendations` shelf, impression feedback |
| Product | `/products/:id` | `view` event, "goes with" shelf that excludes the current item |
| Cart / order | drawer, `/order/:id` | `add_to_cart` / `remove_from_cart` events, purchase batch |
| Compare lab | `/demo/compare` | the same Top-N for every persona side by side, with pairwise overlap |
| Demo rail | button, bottom right | session identity, last provenance, `/health`, proof legend |

Four shoppers can be switched from the header. Persona selection is a
presenter control (a cookie), not authentication:

- **Maya** — barrier-first skincare, fragrance-free (`demo-maya`)
- **Noah** — curl care and scalp health (`demo-noah`)
- **Lina** — fragrance-forward, buys gifts (`demo-lina`)
- **New visitor** — no history; cold-start control, session-only recommendations

Every browser event is sent through the SDK's `EventTracker` (buffered,
background flush) with a deterministic `event_id`, so retries become
`duplicate`, not double counts. Purchases derive their order id and event ids
from a browser-generated `clientOrderKey`: replaying the request returns the
same `ORD-…` with `duplicateCount` instead of a second order.

A shelf that fails (scope, quota, rate limit, GraphRec down) renders an
explicit "unavailable" state with the correlation id; it never takes the page
down with it. Upstream calls are bounded (2 s timeout, one retry).

## Proof status — no invented personalisation

The raw `strategy` GraphRec returns never drives a user-facing claim. Each
recommendation response carries a `proofStatus`:

| Status | Meaning |
|---|---|
| `catalog_fallback` | GraphRec reported a fallback; the shelf shows catalog order |
| `serving_preview` | a model version answered, but nobody has verified it personalises |
| `model_verified` | `MODEL_PROOF_VERIFIED=true` and `MODEL_PROOF_VERSION_ID` name the *exact* version that answered |

`scripts/verify_personalization.py` is the gate. It requests the same Top-N
for Maya, Noah and Lina twice each and checks that a model version is
returned, no known shopper gets the fallback, repeated requests are stable,
shoppers with different histories get *different* rankings, and excluded or
inactive products never appear. It writes `verification-result.json` and exits
non-zero on any failure. It never flips `MODEL_PROOF_VERIFIED` itself — a
person reads the report and copies the version into `.env`.

**Current state (2026-09-12):** the backend's training job is a placeholder
(synchronous, random item vectors, no offline metrics), so every persona —
including the cold-start visitor — receives the identical ranking and the
gate fails on "shoppers with different histories received identical
rankings". The store therefore runs in `serving_preview`, and the compare lab
shows Jaccard 1.00 across all pairs. That is the honest current state; it
resolves itself once real training lands and the gate passes.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHREC_BASE_URL` | `http://localhost:8010` | GraphRec origin; never exposed to the browser |
| `GRAPHREC_API_KEY` | — | storefront key: `catalog:read catalog:write events:read events:write recommendations:read` |
| `GRAPHREC_SEED_API_KEY` | falls back to the storefront key | seed key with `training:*`, `models:*` and `models:deploy` for `scripts/seed.py` |
| `DEMO_PORT` | `5190` | server port |
| `DEMO_DISABLE_MISSING` | `false` | let `seed.py` disable tenant products that are not in the demo feed |
| `DEMO_COOKIE_SECURE` | `false` | set `Secure` on the persona/session cookies |
| `MODEL_PROOF_VERIFIED` / `MODEL_PROOF_VERSION_ID` | `false` / empty | only after the gate passed for that version |
| `GRAPHREC_TIMEOUT_SECONDS` / `GRAPHREC_MAX_RETRIES` / `CATALOG_CACHE_SECONDS` | `2.0` / `1` / `30` | page-path bounds |

`bootstrap_tenant.py` also records `DEMO_ADMIN_EMAIL`, `DEMO_ADMIN_PASSWORD`
and `DEMO_TENANT_ID` so the tenant can be opened in the operator console.

## Tests

```bash
pytest                          # 23 tests; GraphRec is replaced by fakes in tests/conftest.py
cd frontend && npm test         # vitest: cart maths and proof-status rules
cd frontend && npm run build    # tsc --noEmit && vite build
```

The scripts (`bootstrap_tenant.py`, `seed.py`, `verify_personalization.py`)
are the live-stack checks; `seed.py` is idempotent (fixed external ids,
`demo-seed-v1`-derived event ids), so a rerun reports `duplicate`, not new
events.

## Layout

```
app/
  main.py            app factory, lifespan (SDK client + tracker), body limit, SPA serving
  config.py          Settings (.env); refuses placeholder keys
  dependencies.py    per-request Identity from cookies; access to the SDK services
  graphrec.py        builds the AsyncGraphRec client, EventTracker and CatalogSync
  catalog.py         cached product list with the demo's accent colours
  proof.py           proofStatus and cross-persona similarity
  errors.py          SDK error -> storefront error envelope (with correlation id)
  routes/            session, products, events, recommendations (+ feedback, purchase, compare)
fixtures/            the 24 products and the personas' scripted histories
scripts/             bootstrap_tenant, seed, verify_personalization
tests/               FastAPI tests against fake GraphRec services
frontend/src/
  lib/               api client, store (session, cart, provenance), proof helpers
  components/        Header, Shelf, ProductCard, Tile, CartDrawer, DemoRail, Toast
  pages/             Catalog, Product, Compare, Order
```
