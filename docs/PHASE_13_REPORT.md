# Phase 13 — Console: foundations

**Scope (BUILD_PROMPT L676-678):** Vite + TS scaffold · `tokens.css` and both
themes · the 19 primitives · `enums.ts` from `gen-enums` · `types.gen.ts` from
OpenAPI · the API client with refresh-and-retry · token store · the four layout
shells · gates 1–4 as loaders · error boundaries rendering `/403`, `/404`,
`/error` · public routes (`/register`, `/login`, `/recover*`, `/invite/accept`,
`/admin/login`) · `/account/tenant-status`.

**Done when:** a user can register, sign in, and be correctly gated — against
the real backend.

**Gate:** 🛑 *"CONFIRM the design system (§10.7) before starting."* §10.7
answers its own gate — build against CSS custom properties only, use the
Modernist tokens for now, **and ask which system to use before Phase 14**. The
phase proceeded on that instruction; the question is asked at the top of Phase
14 rather than recorded here as closed.

## 1. Built

~11,700 lines of frontend across 53 source files and 9 test files, plus ~720
lines of backend that the console turned out to require.

### The scaffold

* **`frontend/vite.config.ts`** and **`frontend/vitest.config.ts`** — two files,
  not one, and the split is forced rather than stylistic. Vitest 2 bundles its
  own copy of Vite, so a single config that both types `test` and passes
  `plugins` hands a Vite 6 plugin object to a Vite 5 `Plugin` type and produces
  a page of variance errors. Each file is honestly typed against the tool that
  reads it. Dev proxies `/v1` to `localhost:8000`.
* **`frontend/vitest.setup.ts`** — jest-dom, `cleanup`, and a conditional
  `Request` shim. jsdom 25 under this Node hands `RequestInit.signal` to undici,
  whose brand check rejects jsdom's `AbortSignal` even though `instanceof`
  passes; every react-router navigation under test threw. The shim probes for
  the defect first and only patches when it is present, so it disappears on its
  own when the runtime is fixed.
* **`frontend/tsconfig.json`** — strict, plus `noUncheckedIndexedAccess`,
  `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noUnusedLocals`,
  `noUnusedParameters` and `verbatimModuleSyntax`. No path aliases: the `@/`
  alias has to be declared in three places that can disagree, and relative
  imports cannot.
* **`scripts/gen-client.sh`** (72) — §10.3's generator. Regenerates
  `frontend/openapi.json` from the live app, then `types.gen.ts` from it.
  `--check` regenerates into a scratch directory, diffs, restores, and exits 1
  on drift. It found real drift on its first run.
* **`scripts/gen_openapi.py`** (40) — dumps the document without starting a
  server, so the check can run in CI without Postgres.

### The design system

* **`src/styles/tokens.css`** (180) — every colour, space, radius, weight and
  duration, defined twice: `:root` and `[data-theme='dark']`. Nothing downstream
  contains a literal colour, which is the property that makes §10.7's deferred
  question a one-file change.
* **`base.css`**, **`primitives.css`**, **`layout.css`** (1,117 together) —
  reset, the 19 primitives' styles, and the shell/page/card/form geometry.
* **`src/ui/`** (994) — the **19 primitives** §10.6 names: Button, Input,
  Select, Textarea, Field, Table, Badge, Banner, Dialog, Tabs, Pagination,
  FilterBar, EmptyState, Skeleton, StatCard, DefinitionList, StageRail,
  CopyField, Breadcrumbs, behind one `index.ts`. `Dialog` traps focus, restores
  it on close, and closes on `Escape`; `CopyField` exists because the one-time
  secret modal in Phase 14 must not be a route.
* **`src/lib/theme.ts`** — `localStorage` is used here and nowhere else in the
  console, with a comment saying why that is not a contradiction of ADR 0033: a
  theme is a display preference, not a credential.

### The API layer

* **`src/api/types.gen.ts`** (5,796, generated) — from all **63** OpenAPI paths.
* **`src/lib/enums.ts`** (200, generated) — by `scripts/gen_enums.py`, the same
  script that writes `graphrec/common/enums.py`, so the console's vocabulary and
  the server's are the same artefact and `tests/contract/test_enum_parity.py`
  says so.
* **`src/api/session.ts`** — the token store of ADR 0033. Access token in a
  module-level `Map`; refresh token in `sessionStorage`; the two realms keyed
  apart so a platform sign-in cannot be mistaken for a tenant one.
* **`src/api/client.ts`** — bearer attached, `X-Request-Id` captured into
  `ApiError.reference`, **no tenant identifier ever sent** (NR-NF-02), one
  refresh in flight per realm shared across concurrent callers, exactly one
  retry, second 401 clears the session.
* **`src/api/errors.ts`** — the envelope, typed. `isApiError` is a type guard
  rather than an `instanceof`, because an error crossing a bundle boundary is
  not always the class you think it is.
* **`src/api/hooks/{auth,identity}.ts`** — register, sign in (both realms),
  recover, confirm, accept an invitation, sign out; `meQuery`, `tenantQuery`,
  `platformMeQuery`.

### Gates and routes

* **`src/guards/index.ts`** (378 with tests) — gates 1–4 as loaders, in the
  server's order. **Gate 5 is deliberately absent and the module says so**: a
  gate-5 guard would navigate, and §13 forbids navigating away from a page
  because one control on it is unavailable.
* **`src/routes/errors/`** — `/403`, `/404` and `/error` as addressable routes
  *and* as what `RouteErrorBoundary` renders, in one file so the two cannot
  drift. 403 offers no retry; 404 names no resource.
* **`src/layouts/`** — the **four shells** (public, tenant, platform, state
  gate) plus `nav.ts`, which is where role and permission filtering lives so
  that both layouts and both test suites read the same table.
* **`src/routes/public/`** — `/register`, `/login`, `/recover`,
  `/recover/confirm`, `/invite/accept`, `/admin/login`.
* **`src/routes/account/TenantStatus.tsx`** — the gate-2 landing page.
* **`src/router.tsx`**, **`App.tsx`**, **`main.tsx`** — one `QueryClient` shared
  by loaders and the tree, theme applied before first paint.

### Backend the console required

* **`POST /v1/auth/recovery`** and **`POST /v1/auth/recovery:confirm`** — the
  `/recover*` screens had no backend. Built against the `recovery_tokens` table
  that has existed unused since Phase 3, with **migration 0014** adding the
  `tenant_lookup.resolve_recovery_token` resolver. ADR 0032.
* **`graphrec/common/delivery.py`** (67) and **`scripts/recovery_token.py`**
  (85) — the administrator CLI that BUILD_PROMPT L90 specifies, and a
  deliberately alarming `WARNING` when no transport is configured.
* **`GET /v1/tenant` exempted from gate 2** via a named dependency,
  `current_tenant_principal_any_state`. ADR 0031.

## 2. Verified

**Frontend: 71 tests across 9 files, all passing.** `tsc -b` clean.
`npm run build` succeeds — 139 modules, 345.91 kB JS, 16.85 kB CSS.
`scripts/gen-client.sh --check` reports the generated client up to date against
63 paths.

The tests worth naming are the ones that assert an absence:

* **`session.test.ts`** (7) — the access token appears in neither storage's
  serialised contents (asserted on *contents*, so renaming a key does not defeat
  it), and `localStorage` is a recording stub that fails the test if anything
  writes to it at all.
* **`client.test.ts`** (8) — no request carries a tenant identifier; six
  concurrent 401s produce exactly one refresh; a second 401 clears the session
  rather than refreshing again.
* **`guards.test.ts`** (13) — the gates fire in order, and gate 2 stops *before*
  `/v1/me` is fetched rather than after, which is checked by asserting the fetch
  did not happen.
* **`Recovery.test.tsx`** (8) — the rendering for a real address and the
  rendering for an invented one are compared **to each other**, character for
  character. Any future branch on whether the account exists shows up as a diff.

**Backend:** the five gates green — `ruff format --check` (275 files), `ruff
check`, `mypy` (157 files, strict), `lint-imports` (3 contracts), and the full
pytest suite.

`tests/authz/test_recovery.py` (302) covers the non-disclosure properties
directly: identical responses for real, fictional, locked and unknown-code
requests; no audit row on either path; a confirmed recovery revoking every
refresh session. `tests/authz/test_gate_order.py` grew the both-halves
assertion ADR 0031 describes. `tests/contract/test_openapi_document.py` (50) is
new and asserts the document builds at all — which is how the `serving.py`
defect below was caught.

## 3. Decisions and deviations

Three ADRs, all written this phase:

* **ADR 0031** — gate 2 exempts exactly one read, `GET /v1/tenant`. Without it
  the gate-2 landing page is a redirect loop with nothing readable in it.
* **ADR 0032** — a recovery proof is never returned in a response, unlike an
  invitation token. The asymmetry is about who is asking: an authenticated
  administrator who chose the recipient, versus an anonymous stranger who typed
  an address.
* **ADR 0033** — access token in memory, refresh token in `sessionStorage`,
  never `localStorage`; one shared refresh per realm; one retry.

**Deviations from the phase brief:**

* **The 🛑 gate was self-answered.** §10.7 tells the phase what to build against
  *and* tells it to ask before Phase 14. Proceeding is what the section
  instructs, but it is not the same as a human answering, and it is named here
  rather than dressed up. The question is asked before Phase 14 starts.
* **Two endpoints were added that the phase did not ask for.** Building
  `/recover*` against nothing would have produced two forms that cannot work,
  and "done when a user can register, sign in, and be correctly gated — against
  the real backend" does not admit a stub.
* **`Recover`'s success screen does not compare the password confirmation
  client-side.** The server compares first so that a typo cannot consume a
  single-use proof, and duplicating the check in the console would only make the
  server's ordering look optional.

## 4. Bugs this phase found in code written earlier

* **A leaked database connection on every gated request, since Phase 3.**
  `apps/control_api/deps.py` iterated the inner gate generator with a bare
  `async for`. FastAPI finalises a dependency generator by throwing
  `GeneratorExit` at the `yield`, which unwound the wrapper but left the inner
  generator suspended inside its own `async with sessionmaker()` — so nothing
  closed the session and the connection lived until GC. It surfaced as
  `BaseConnection.__del__` warnings in whatever unrelated test happened to run
  when the collector fired, and had been misread three times: once as Docker
  being down, once as a Pydantic annotation error, once as flakiness. Fixed with
  `contextlib.aclosing` in both wrappers, with the explanation in the docstring
  so the next person does not remove it as noise.

* **`/openapi.json` could not be generated, since Phase 11.**
  `apps/control_api/routers/serving.py` had `ArtifactStore` imported only under
  `TYPE_CHECKING` while using it inside an `Annotated[...]` FastAPI must resolve.
  FastAPI could not resolve the forward reference, fell back to treating the
  parameter as a query parameter, and failed at schema generation. Nothing
  noticed because nothing had ever asked for the document. Moved to a runtime
  import with a comment saying why it cannot go back, and
  `tests/contract/test_openapi_document.py` now asks.

* **Contract drift in the generated client.** `gen-client.sh --check` found the
  `GET /v1/tenant` change already out of sync on its first run — which is the
  script working, one commit after being written.

## 5. Not done

**Deferred to Phase 14, by scope:** the 29 remaining tenant routes; the `/home`
onboarding checklist (`GET /v1/onboarding` — named in Phase 14's scope and
**absent from all 63 OpenAPI paths**, so it has to be built); the tenant
layout's active-model and service-status badges, which need endpoints Phase 14
wires up.

**Deferred to Phase 15, by scope:** the eight `/admin/*` routes, the full a11y
pass, the three per-role workflow tests, and `ROUTES.md`.

**Open, and not deferred to anything:**

* **Platform operators have no self-service recovery.** Their rows carry
  `tenant_id IS NULL` and the resolver returns a tenant id, so the endpoint
  cannot see them. Today the answer is another operator with database access.
  Recorded in ADR 0032 and added to the ADR index's open questions.
* **Recovery timing is not equalised.** The real path runs an argon2 hash the
  fictional path does not, and the difference is measurable. Doing it properly
  means constant-time work on both branches; doing it badly is worse than not
  doing it. The answer is rate limiting at the edge, written down rather than
  implied.
* **`sessionStorage` means a new tab is a new sign-in.** Accepted cost of ADR
  0033.

**Still open from earlier phases:** the 15-minute training cooldown is
provisional; no retention sweep for orphaned artifacts; training concurrency is
per tenant rather than platform-wide; the metric floor is not tenant-
configurable; the training worker still takes the in-memory counter default; the
reconciler is serial and scheduled by nothing; `serving_replicas` rows are not
swept; no audit retention or partitioning; `security_events` has no alerting.
