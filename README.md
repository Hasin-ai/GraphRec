# GraphRec

GraphRec is a multi-tenant recommendation platform developed as small, working
vertical slices. The hardened paths are public tenant registration, tenant-user
sign-in, the protected subscription/quota overview, current usage
reconciliation, and scoped API-key lifecycle management. A second group of
domain paths (catalog, events, datasets, training, model versions, deployment
status, recommendations, and platform administration) exists as a working
scaffold whose model training and scoring are still placeholders.

## Hardened paths

- Registration: `http://localhost:5180/register` -> `POST /v1/tenants`
- Account setup: `http://localhost:5180/setup#token=...` -> `POST /v1/auth/setup-password`
- Sign-in: `http://localhost:5180/login` -> `POST /v1/auth/login`
- Usage and subscription: `http://localhost:5180/usage` -> `GET /v1/usage`,
  `GET /v1/subscription`
- API keys: `http://localhost:5180/credentials` -> redacted list/detail plus
  create/rotate/revoke endpoints
- Durable effects include tenant setup, hashed tenant-scoped refresh sessions,
  an immutable tenant usage ledger, and versioned HMAC-only API-key verifiers.
- Isolation uses forced PostgreSQL row-level security on every tenant-owned
  table; protected reads derive tenancy from a verified bearer or API key and
  accept no tenant selector.

## Domain scaffold

- Catalog: `/v1/products`, `/v1/products:bulk-upsert`
- Events: `/v1/events`, `/v1/events/batches`
- Datasets: `/v1/datasets/upload` (multipart JSON or CSV), `/v1/datasets/snapshots`
- Training and models: `/v1/training-jobs`, `/v1/model-versions`
- Serving: `/v1/recommendations`, `/v1/feedback/*`, `/v1/deployment*`, `/v1/metrics/summary`
- Platform administration: `/v1/platform/*`, authenticated with the
  `PLATFORM_ADMIN_TOKEN` shared secret (leave it empty to disable these routes)

Known placeholders in the scaffold: training jobs index synthetic embeddings
into Qdrant instead of real GNN output, recommendation scoring uses a fixed
query vector and Qdrant rank order, feedback endpoints acknowledge but do not
persist, and deployment/autoscaling/metrics responses are static.

## Account setup

Registration creates an *invited* administrator and returns a one-time
`setup_token` in the `201` response only. The console shows it once as a setup
link (`/setup#token=…`, kept in the URL fragment so it never reaches a
server log); `POST /v1/auth/setup-password` takes `{setup_token, password,
email?}`, activates the account once, and answers every rejection with
`401 invalid_setup_token`. Tokens expire after
`ACCOUNT_SETUP_TOKEN_TTL_SECONDS` (24 hours by default), are stored only as a
SHA-256 hash, and are revoked when a new one is issued. An idempotent
registration replay never returns the token again; issue a fresh one with:

```bash
docker compose exec api python -m scripts.issue_account_setup_token admin@example.org
```

## Permissions

Every tenant route checks the credential's scope and answers `403
insufficient_scope` when it is missing. `tenant_administrator` holds all
tenant scopes; `tenant_developer` holds `keys:write`, `catalog:*`, `events:*`
and `training:read`. Access tokens carry the scopes granted at login, so sign
in again after a role or scope change. API keys are limited to the scopes the
creating role may delegate (administrators: all 14 API-key scopes; developers:
catalog and events).

## Local sign-in demonstration

Create a separate local-only demo credential, then sign in through the
documented endpoint:

```bash
docker compose --env-file .env.example --profile demo run --rm demo-account
```

- Email: the `DEMO_LOGIN_EMAIL` value in `.env` (example default:
  `demo-admin@example.org`)
- Password: the `DEMO_LOGIN_PASSWORD` value in `.env`

The bootstrap is not a public setup endpoint and must not be enabled on a VPS.

The registration contract intentionally asks only for a business name and
administrator email; the password is chosen later on the setup page with the
one-time token.

## Operator console

`frontend_02/` is the operator console (React 19, Vite, TypeScript) built from
the Modernist design prototype kept under `frontend_02/design/`. It talks to
the API through the nginx `/v1/` proxy in Compose, or the Vite dev proxy
locally. See `frontend_02/README.md` for the route map, which prototype
screens are not backed by the API, and how to run it against a bare uvicorn.

- Tenant realm: `/login`, `/register`, `/setup`, then `/home`, `/credentials`,
  `/integration`, `/account`, `/products`, `/products/sync`, `/events/submit`,
  `/submissions/:id`, `/datasets`, `/training`, `/models`, `/usage`,
  `/service-status`. Navigation and route gates are derived from the scopes
  the login returns.
- Platform realm: `/admin/login` with `PLATFORM_ADMIN_TOKEN`, then
  `/admin/status`, `/admin/tenants`, `/admin/plans`, `/admin/audit`.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:5180/register` to create a tenant; the response shows
the one-time setup link, which activates the administrator at `/setup` and
signs you in. Returning users sign in at `http://localhost:5180/login`.
**Usage & Quotas** shows the reconciled current-period usage against plan
limits; **API Credentials** creates, inspects, rotates and revokes a scoped
server credential. One-time secrets must be saved before closing their
confirmation view. The API health check is available at
`http://localhost:8010/healthz` for local operations only. Both host ports are
configurable in `.env`.

For frontend development without rebuilding the image:

```bash
cd frontend_02
npm install
npm run dev        # http://localhost:5173, proxies /v1 to http://localhost:8010
```

## Verify

```bash
docker compose exec -T api pytest -q
docker compose --profile test run --rm frontend-test
```

Or, for the console alone: `cd frontend_02 && npm test -- --run && npm run build`.

`GraphRec_Complete_SRS.md` is the in-repo specification. Integration tests
require the Compose PostgreSQL database; the unit tests run without it.

## SDKs

Client libraries for Python (`sdks/python`) and TypeScript (`sdks/typescript`)
cover every API route, with retries, body-size splitting and e-commerce
helpers. See [`sdks/README.md`](sdks/README.md); each has an end-to-end smoke
test that runs against the Compose stack.
