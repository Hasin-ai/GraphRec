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
cd web && npx playwright install chromium && npm run e2e
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
  brand/        BrandMark, GraphIllustration, ThemeButton (shared by every layout)
  marketing/    BRAND copy (hero + auth showcase) and plan limits (plans.ts)
  layouts/      MarketingLayout, PublicLayout, TenantLayout, PlatformLayout, route guards (gates 1-3)
  ui/           Page, Form, Dialog, primitives (the prototype's shared renderer)
  lib/          formatting, state->tone map (GROUPS), scope vocabulary
  pages/        marketing/ (landing + pricing, sections/), public/, tenant/, platform/, errors/
  styles/       modernist.css (tokens + components), console.css (layout + primitives),
                system.css + app.css (semantic layer, console tokens), marketing.css (public site, scoped under .mkt)
```

### Public site and `MarketingLayout`

`/` is the public landing page for signed-out visitors; a tenant session still
redirects to `/home` and a platform session to `/admin/status` (`Root()` in
`App.tsx`). `/pricing` is always reachable, signed in or not. Both render in
`MarketingLayout`: a sticky header (anchor links to the landing sections, a
light/dark toggle and a session-aware call to action), a hamburger menu below
960 px, and a footer that links into the console. It is separate from
`PublicLayout`, which stays the split-screen auth shell. Plan limits on
`/pricing` come from `src/marketing/plans.ts`, which mirrors the seeded
`pricing_plans` rows (migrations `0001`, `0012`, `0031`); operators can change
plans at runtime, so the page shows the seeded defaults. Plans carry no prices.

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
| — | `/` (new, signed out) | public landing page in `MarketingLayout`; signed in, redirects to `/home` or `/admin/status` |
| — | `/pricing` (new) | live plan limits from public `GET /v1/plans` (seeded defaults, labelled as such, if the read fails) |
| `/register` | `/register` | `POST /v1/tenants` (business name + admin email; shows the one-time setup link) |
| `/invite/accept` | `/setup` (alias `/invite/accept`) | `POST /v1/auth/setup-password` |
| `/login` | `/login` | `POST /v1/auth/login` |
| `/recover`, `/recover/confirm` | `/recover` | `POST /v1/auth/recover-password` with an operator-issued recovery token (self-service email is decision D-05) |
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
| `/training`, `/training/:id` | same | `GET/POST /v1/training-jobs`, `GET /v1/training-jobs/{id}`, `POST …:cancel` (with optional reason) |
| `/models`, `/models/:id` | same | `/v1/model-versions` list/get, `:activate`, `:archive`, `:rollback` (each with an optional audited reason) |
| `/usage` | `/usage` | `GET /v1/usage` (9 dimensions) + `GET /v1/subscription` |
| `/service-status` | `/service-status` | `/v1/deployment`, `/v1/deployment/scaling`, `/v1/metrics/summary` |
| `/admin/tenants`, `/admin/tenants/:id` | same | list/get, `POST .../status` (reason required), `POST .../quotas`, `POST .../plan`, `POST .../recovery`, tenant usage |
| `/admin/plans`, `/admin/plans/:id` | same | `GET /v1/platform/plans`, `PUT /v1/platform/plans/{id}` |
| `/admin/status` | `/admin/status` | `GET /v1/platform/status` |
| `/admin/audit` | `/admin/audit` | `GET /v1/platform/failures`, `GET /v1/platform/audit` (tenant/action filters, paging, reasons) |
| `/403`, `/404`, `/error` | same | rendered inside the active layout |

Team members and invitations (`/users`), plan editing and assignment, and job
cancellation are built. Not built yet, because the API has no endpoint for them:
tenant-scoped audit (`/audit`), `/account/tenant-status` (decision D-13),
cross-tenant usage (`/admin/usage`), per-user management (`/users/:id`) and
named platform permissions (decision D-04: the platform realm is still one
shared token). See `docs/GAP_ANALYSIS.md` and `docs/DECISIONS.md`.

## Sessions

The token pair from `POST /v1/auth/login` lives in `sessionStorage` (tab
scoped, cleared when the tab closes). The 15-minute access token is renewed
with the single-use refresh token (`POST /v1/auth/refresh`, rotated on every
use) shortly before it expires and once on `token_expired`; the session ends
when refresh fails or the user signs out, and the guards route back to sign-in. The platform token is kept the same way and is only ever
sent as a bearer header to `/v1/platform/*`.
