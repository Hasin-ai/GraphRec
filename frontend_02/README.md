# GraphRec operator console

React 19 + Vite + TypeScript console for the GraphRec API, built from the
Modernist design prototype in `design/` (`GraphRec Console.dc.html`,
`ROUTES.md`). The prototype's layout shells, shared page primitives (header,
banner, stats, stage rail, definition list, filter bar, table, panels, dialogs,
one-time secret) and state colours are ported one-to-one; every screen reads
and writes the real API instead of the prototype's mock store.

## Run

```bash
npm install
npm run dev          # http://localhost:5173 — proxies /v1 to http://localhost:8010
npm test -- --run    # vitest + Testing Library
npm run build        # tsc -b && vite build -> dist/
npm run e2e          # Playwright journey against the running Compose stack (see below)
```

### End-to-end journey

`e2e/console.spec.ts` drives the real console against the live API through
nginx: register -> setup -> credentials -> catalog -> events -> datasets ->
training -> activate -> serving -> usage -> gates -> platform realm (status
change, quota override, audit). Nothing is mocked; each run registers a fresh
tenant and suspends it at the end. Screenshots of every screen land in
`e2e-screens/`.

```bash
docker compose up -d --build          # stack on :5180 / :8010, PLATFORM_ADMIN_TOKEN set in .env
cd frontend_02 && npx playwright install chromium && npm run e2e
```

The suite carries one browser page through all steps because the API rate
limits sign-in (8/min per account) and API-key administration (10/min).

`VITE_API_PROXY=http://localhost:8000 npm run dev` targets a bare uvicorn
instead of the Compose API port. In Compose the `frontend` service builds this
directory and nginx proxies `/v1/` to the `api` service (see `nginx.conf`).

## Layout

```
src/
  api/          request() wrapper (auth, error envelope, 401 handling) + typed endpoints
  auth/         tenant and platform sessions (sessionStorage, tab-scoped)
  hooks/        useSession, useResource, useToast, useTheme
  layouts/      PublicLayout, TenantLayout, PlatformLayout, route guards (gates 1-3)
  ui/           Page, Form, Dialog, primitives (the prototype's shared renderer)
  lib/          formatting, state->tone map (GROUPS), scope vocabulary
  pages/        public/, tenant/, platform/, errors/
  styles/       modernist.css (tokens + components), console.css (layout + primitives)
```

## Authorization gates

| # | Gate | Where |
|---|---|---|
| 1 | Identity | `RequireTenant` / `RequirePlatform`: no session -> `/login` or `/admin/login`; a `401` from the API ends the session |
| 2 | Tenant state | Enforced by the API: an inactive tenant cannot sign in and its tokens stop verifying |
| 3 | Scope | `RequireScope` per route -> `/403`; navigation lists only routes whose scope the login returned |
| 4 | Ownership | A `404` for another tenant's resource renders the same "Not found" page, never naming the resource |
| 5 | Resource state | Disabled controls with an inline reason (revoked keys, non-eligible versions, running jobs, missing scope) |

Gate 3 is driven by the scopes in the login response, not by a role table in
the console. A tenant administrator therefore sees the catalog and event
screens too (the API grants `catalog:*` and `events:*` to that role); a
developer sees credentials, catalog, events, datasets and a read-only training
list.

## Route map versus the prototype

| Prototype route | Console | Backed by |
|---|---|---|
| `/register` | `/register` | `POST /v1/tenants` (business name + admin email; shows the one-time setup link) |
| `/invite/accept` | `/setup` (alias `/invite/accept`) | `POST /v1/auth/setup-password` |
| `/login` | `/login` | `POST /v1/auth/login` |
| `/recover`, `/recover/confirm` | `/recover` (informational) | no recovery endpoint; documents the operator-issued setup token |
| `/admin/login` | `/admin/login` | `GET /v1/platform/status` with `PLATFORM_ADMIN_TOKEN` |
| `/home` | `/home` | onboarding checklist answered by real reads |
| `/credentials` | `/credentials` | `/v1/api-keys` list, create, rotate (grace + reason), revoke |
| `/integration` | `/integration` | contract reference + active credentials |
| `/account` | `/account` | session record; no profile/password endpoint |
| `/products`, `/products/new`, `/products/:id` | same | `GET/PUT /v1/products`, `:disable` |
| `/products/sync` | `/products/sync` | `POST /v1/products:bulk-upsert` (synchronous counts + failures) |
| `/events/submit` | `/events/submit` | `POST /v1/events`, `POST /v1/events/batches`, recent batches |
| `/submissions/:id` | `/submissions/:id` | `GET /v1/events/batches/{id}` (event batches only) |
| — | `/datasets` (new) | `POST /v1/datasets/upload`, snapshots list/create |
| `/training`, `/training/:id` | same | `GET/POST /v1/training-jobs`; detail found in the list (no single read); no cancel endpoint |
| `/models`, `/models/:id` | same | `/v1/model-versions` list/get, `:activate`, `:archive`, `/v1/models/{id}:rollback` |
| `/usage` | `/usage` | `GET /v1/usage` (9 dimensions) + `GET /v1/subscription` |
| `/service-status` | `/service-status` | `/v1/deployment`, `/replicas`, `/autoscaling`, `/v1/metrics/summary` |
| `/admin/tenants`, `/admin/tenants/:id` | same | list/get, `POST .../status`, `POST .../quotas` |
| `/admin/plans`, `/admin/plans/:id` | same | `GET /v1/platform/plans` (read-only) |
| `/admin/status` | `/admin/status` | `GET /v1/platform/status` |
| `/admin/audit` | `/admin/audit` | `GET /v1/platform/failures`, `GET /v1/platform/audit` |
| `/403`, `/404`, `/error` | same | rendered inside the active layout |

Not built, because the API has no endpoint for it: tenant users and
invitations (`/users`), tenant-scoped audit (`/audit`), `/account/tenant-status`,
cross-tenant usage (`/admin/usage`), plan create/edit/close, plan assignment,
job cancellation, and named platform permissions (the platform realm is one
shared token, so every platform route is permitted once signed in).

## Sessions

The access token from `POST /v1/auth/login` lives in `sessionStorage` (tab
scoped, cleared when the tab closes) with its expiry; there is no refresh
endpoint, so an expired or rejected token signs the user out and the guards
route back to sign-in. The platform token is kept the same way and is only ever
sent as a bearer header to `/v1/platform/*`.
