# GraphRec frontend audit — September 18, 2026

## Scope and evidence

Inspected every route in `src/App.tsx`, every page and shared UI module, request/session hooks, both stylesheets, wire types, tests, and the corresponding FastAPI routes/services. Existing uncommitted changes are the baseline and are preserved. The demo storefront is a separate demonstration application, not the GraphRec console.

Live audit uses Vite on port 5173 against the existing local Compose API on 8010. `e2e/routes.spec.ts` creates a separate `Frontend audit …` tenant and real catalog, event, snapshot, training and model records. Screenshots and route/viewport observations are in `e2e-screens/before/`; no API mocks are used. The existing unit-test baseline is 22 passing tests. Screenshots of one-time secrets are masked. The initial overview capture was not settled and was rejected; the capture helper now waits for network idle.

## Product and sources of truth

React 19 + TypeScript + React Router 7 + Vite; custom `useResource` server-state hook, sessionStorage bearer sessions, CSS tokens and common primitives. No query library, chart library, UI framework or unused runtime dependencies were found. FastAPI delegates to tenant-scoped services and PostgreSQL row security; Qdrant provides vector indexing. Scopes come from authentication responses. There is no project switch endpoint or project selector; a tenant is bound to the signed-in identity (`tid` in the API-issued JWT). Platform operator authentication is separate.

Canonical data: `/v1/products` for catalog; `/v1/events/batches` for batch outcomes; `/v1/datasets/snapshots` for snapshots; `/v1/training-jobs` for job state; `/v1/model-versions` for activation; `/v1/deployment` for the API's configured serving version; `/v1/metrics/summary` for measured requests; `/v1/usage` for ledger usage and effective quotas. Model activation is not a dependency health probe. Do not synthesize infrastructure health from it.

## Findings before implementation

| Priority | Finding and evidence | Required correction |
| --- | --- | --- |
| Critical | `useResource` retains prior dependency data; session changes do not identify requests; a late 401 can clear a newer session. | Mask old resource data immediately, invalidate obsolete completions, remount session-owned UI and compare request identity before expiring sessions. |
| High | Usage headline excludes zero limits and uses `remaining`, rows use another rule, meters a third. `tenant-15-1440.png`. | One calculation from `used` and nullable `limit`, including zero limits and the 80% threshold. |
| High | Training claims “a request would be accepted” before reads complete and ignores usage errors. | Explicit checking/unavailable/blocked states; backend remains authoritative. |
| High | Independent sidebar model/deployment reads refresh on navigation, not activation. Home repeats the same calls and reports failed reads as missing setup. | Remove operational state from sidebar; show real state once on overview and operational pages; invalidate related reads after confirmed mutations. |
| High | Multiple collection pages show “no records” after failed reads; integration says no credential while loading or unauthorized. | Distinct initial-loading, failure, empty and successful-data states. |
| High | Secret dialog has no focus trap; other dialogs dismiss through backdrop/Escape while pending, risking lost secret disclosure. | Shared modal focus management, restore focus, lock dismissal while busy. |
| High | Default backend training registers a successful placeholder and synthetic embeddings; deployment status only checks an active row. | Disclose the backend limitation persistently; do not call this measured infrastructure health or real trained quality. |
| Medium | Home is ten navigation cards plus a seven-step checklist. Usage has eight summary/metadata cards and duplicated plan limits. | Operational overview; compact usage table; optional plan detail. |
| Medium | Global rounded/shadowed panels, nested metadata tiles, micro-labels and repeated state pills. | Sections, ruled definition lists, consistent typography and table surfaces. |
| Medium | Mobile shows the full account/navigation shell before content; dialogs have no height constraint. `responsive-usage-390.png`. | Collapsible navigation, constrained dialogs, intentional table scrolling. |
| Medium | Catalog accumulates 500-row pages, lookup failures become no results, and load-more can reject without handling. | Bounded URL pagination and explicit exact-ID lookup with errors. Preserve server limitations. |
| Medium | Rollback and platform status demand a reason that is never submitted or stored. | Remove the nonfunctional field, keep consequence confirmation. |
| Medium | Field errors are not associated with inputs; tabs lack keyboard behavior; no skip link or route focus management. | Shared form associations, accessible navigation and focus. |
| Low | Numeric locale dates are ambiguous; timestamps pulse; external web fonts create a network dependency. | Central readable timezone-labelled dates, no decorative motion, system typography. |

No hardcoded production analytics or fake notification counts were found. Documentation examples and input placeholders are examples, not fetched state; tests legitimately contain fixtures. The idempotency fallback uses randomness, not simulated analytics. Production misleading defaults include zero counts during failed reads, “all nine” usage copy, and inferred eligibility/completion. The global checklist dismissal is stored without tenant scope; remove that checklist rather than perpetuate parallel onboarding state.

## Complete route inventory and API map

All `/v1` paths below are real repository endpoints. Shared state contract: initial skeleton, persistent error with retry, empty only after a successful read, backend-confirmed mutation results. Shared responsive concerns: forms reflow to one column, tables scroll in named keyboard-focusable regions, code blocks scroll locally, dialogs fit the viewport. Shared removals/consolidation: metadata cards become definition rows; panels become sections; loading/error behavior belongs to shared primitives. Route-specific exceptions appear below.

| Route | Purpose / primary goal | Queries | Mutations / primary and secondary actions | Permission | States and current problems |
| --- | --- | --- | --- | --- | --- |
| `/` | Choose session destination | Session only | Redirect to home, platform or login | None | Preserve realms and browser history |
| `/login` | Enter tenant console | Session | POST auth/login; recover/register/setup links | Public | Idle, invalid, rate-limited, unavailable, signed in; excessive technical explanation |
| `/register` | Create tenant | None | POST tenants with idempotency key; open setup/copy link | Public | Invalid, conflict, pending, created, replayed; secret link must stay one-time |
| `/setup`, `/invite/accept` | Activate invited identity | Fragment token | POST auth/setup-password; back to login | One-time token | Invalid/expired/used token, validation, pending, signed in; preserve fragment scrubbing |
| `/recover` | Restore access | None | Navigate to setup/login | Public | No self-service recovery API; remove irrelevant operator command from customer flow |
| `/recover/confirm` | Legacy recovery URL | None | Redirect setup | Public | Must preserve fragment token |
| `/admin/login` | Enter platform console | GET platform/status to validate supplied token | Save tab session; tenant login link | Operator token | Invalid, pending, unavailable, signed in |
| `/home` | Assess system and next action | Permission-gated deployment, models, products, jobs, usage | Navigate to relevant lifecycle step; refresh | Tenant session | Loading/failed reads must not imply incomplete onboarding; remove cards/checklist |
| `/account` | Inspect current identity and access | Session | Copy identity, sign out | Tenant session | No profile/password-edit endpoint; show tenant identity, clear granted/not granted vocabulary |
| `/integration` | Integrate the API | api-keys if permitted | Copy examples/base URL | Tenant session | Credential errors/loading hidden; distinguish labelled examples from live data |
| `/credentials` | Manage integration access | api-keys | POST create/rotate, DELETE revoke; copy one-time secret | keys:write | Loading, empty, error, created/rotated/revoked; confirmed changes; secret focus trap missing |
| `/products` | Inspect catalog | products?limit&offset or ids | Search/page/open; confirm disable | catalog:read; writes require catalog:write | Loaded-page search ambiguous; unbounded DOM, swallowed errors |
| `/products/new` | Upsert a product | None | PUT products/{external_id}; cancel | catalog:write | Validation, pending, error, saved; clarify existing ID replaces fields |
| `/products/sync` | Bulk upsert catalog | None | POST products:bulk-upsert; inspect failures, repeat/open catalog | catalog:write | Invalid input, pending, partial/full result, failure; synchronous, no sync-job history endpoint |
| `/products/:productId` | Inspect/edit one product | products/{id} | PUT update, POST :disable; copy/back | catalog:read; write gate | Loading, missing, read-only, dirty, validation, saved; stale route data risk |
| `/events/submit` | Ingest interactions | events/batches if events:read | POST events or events/batches; inspect result | events:write | Single, duplicate, batch partial/rejected; read actions must respect events:read |
| `/submissions/:submissionId` | Inspect batch outcome | events/batches/{id} | Refresh/copy | events:read | Loading, missing, failed read, completed; no per-item errors retained |
| `/datasets` | Import data / freeze snapshot | datasets/snapshots | POST upload, POST snapshots | training:read; upload catalog:write + events:write; snapshot training:write | File selected/uploading/result/error, snapshot empty/ready; long format prose |
| `/training` | Inspect and request training | training-jobs, usage if permitted | POST training-jobs with optional snapshot/configuration; filter/open | training:read; write training:write | Checking, blocked quota/running, unavailable, failed/succeeded; false readiness and zero counts |
| `/training/:jobId` | Inspect job and model | training-jobs; model-versions/{id} if permitted | Refresh/open model | training:read | Missing/running/succeeded/failed; remove unsupported cancellation; poll only running state |
| `/models` | Select active version | model-versions | Confirm POST :activate; filter/open | models:read; models:deploy | Empty, eligible, active, retired, archived; redundant serving column and stats |
| `/models/:versionId` | Evaluate/change lifecycle | model-versions/{id}, model-versions, training-jobs if permitted | POST :activate, models/{id}:rollback, :archive | models:read; models:deploy or models:write | Missing/error/eligible/active/retired/archived; remove unsaved rollback reason |
| `/usage` | Identify consumption and blocking limits | usage; subscription if billing:read | Refresh, expand plan limits | usage:read | Limited/informational/approaching/exhausted; inconsistent calculations and over-cardification |
| `/service-status` | Inspect serving and requests | deployment, metrics/summary?window_minutes, model-versions if permitted | Refresh/change time window | deployments:read; metrics:read, models:read optional | Stopped/available; no traffic versus failed metrics; redundant state summary |
| `/admin` | Platform entry alias | None | Redirect status | Platform session at target | Stable existing URL |
| `/admin/status` | Assess platform | platform/status, tenants, failures | Refresh | Platform session | Healthy/degraded/not deployed; auxiliary read errors hidden, duplicated health metadata |
| `/admin/tenants` | Find tenant | platform/tenants | Search/filter/open; confirm status change | Platform session | Empty/filter/error; no tenant impersonation |
| `/admin/tenants/:tenantId` | Operate one tenant | platform/tenants/{id}, plans | POST status, POST quotas | Platform session | Missing/error/status/override result; reason is not persisted; overrides lack GET endpoint |
| `/admin/plans` | Inspect offered plans | platform/plans | Open plan | Platform session | Loading/error/empty/active/inactive; no plan edit/assignment API |
| `/admin/plans/:planId` | Inspect limits | platform/plans | Copy identifier/back | Platform session | Missing/loaded; limits should not become independent cards |
| `/admin/audit` | Diagnose failures and audit | platform/failures, platform/audit | Tabs/filter/tenant link | Platform session | Empty/filter/error; latest 50 only, no pagination API; URL state missing |
| `/403` | Explain access restriction | Session for layout | Return home | Any | Remove implementation “Gate 3” copy |
| `/404`, `*` | Recover from missing resource | Session for layout | Return home | Any | Non-disclosing error; remove implementation “Gate 4” copy |
| `/error` | Unexpected failure | Router correlation reference | Return/retry navigation | Any | Do not invent occurrence timestamp when absent |

## Backend gaps and explicit non-goals

No project switching, refresh-token endpoint, self-service password recovery, dataset deletion, cancellation, async progress/SSE, sync-history resource, general product full-text search, persistent operator reason field, or frontend invitation route currently exists. Tenant-user API support is present but adding a new members product is outside this existing-route redesign. Default model creation is a placeholder; frontend changes cannot make that ML pipeline production-ready. Usage reflects the ledger: a product count or active-version count may differ from registry state if the backend has not recorded/reconciled those usage dimensions. Do not rewrite ledger readings as catalog counts or claim healthy dependencies from an active-model row.

## Implementation plan

1. Guard resource/session boundaries and obsolete 401 responses; deduplicate simultaneous GETs.
2. Centralize quota state; truthful training eligibility, source-specific errors and mutation feedback.
3. Replace navigation-heavy overview and simplify usage/model/status layouts.
4. Consolidate visual tokens, sections, responsive navigation, dialogs/forms/tables.
5. Refine each remaining route, retain contracts and remove unsupported controls.
6. Verify meaningful unit regressions, existing live workflows, every route at representative widths/themes, production TypeScript/build. No lint command exists; do not claim lint passed.

## SRS integration follow-up — September 20, 2026

See [SRS_ACCEPTANCE.md](../SRS_ACCEPTANCE.md) for the subsequent role, real training, MovieLens, persistence and quota work. The rebuilt Docker console on port 5180 passed all 16 browser tests; the component suite passed 52 tests. Remaining SRS gaps are explicitly listed there.
