# GraphRec operator console — route, role and gate map

Prototype: `GraphRec Console.dc.html` (hash router — `#/home`, `#/models/v-7`, …).
36 addressable routes · 3 redirects · 4 layout shells. Mock store is seeded in the
`seed()` function; every screen runs without a server.

## Authorization gates

Evaluated in this order. A later gate assumes the earlier ones passed.

| # | Gate | Blocks on | Result |
|---|---|---|---|
| 1 | Identity | no session; user status `invited` / `locked` / `disabled` | redirect `/login` |
| 2 | Tenant state | tenant status ≠ `active` | redirect `/account/tenant-status`, navigation suppressed |
| 3 | Role / permission | role or named permission not held | `/403`, terminal |
| 4 | Ownership | resource resolves to another tenant | `/404`, non-disclosing |
| 5 | Resource state | lifecycle forbids the action | control disabled + inline reason, **no navigation** |

Implementation: `resolve(path, ctx)` runs gates 1–4 before a page function is ever
called; `own(match)` is gate 4 and returns `/404` for an unresolvable id. Gate 5 lives
in the page functions (`eligibility()`, the `disabled` / `reason` pairs on actions).

Redirects: `/` → `/home` | `/admin` | `/login` by identity. `/admin` → first permitted
platform route (`firstPerm`). A tenant user reaching `/account/tenant-status` while
active is redirected to `/home`.

## Public — PublicLayout (no session, brand only, no navigation)

| Route | Notes |
|---|---|
| `/register` | creates tenant + initial administrator; duplicate business name is a conflict, form stays filled |
| `/login` | non-disclosing failure; resolves role → `/home` or `/admin` |
| `/recover` | step 1, response does not confirm the account exists |
| `/recover/confirm` | step 2, expired proof rejected without disclosure |
| `/invite/accept` † | token-based; `invited → active`; on success → `/login` |
| `/admin/login` † | separate platform realm, resolves no tenant scope |

## Gate 2 — StateGateLayout

| Route | Notes |
|---|---|
| `/account/tenant-status` | states lifecycle position; only a Platform Administrator can transition it |

## Tenant — TenantLayout (tenant derived from session; no tenant id in any path)

| Route | Role | Gate 5 / notes |
|---|---|---|
| `/home` | Admin · Dev | role-filtered launcher; onboarding checklist (Admin), dismissible |
| `/credentials` | Admin · Dev | rotate/revoke disabled on revoked credentials; one-time secret modal |
| `/integration` ‡ | Admin · Dev | contract reference + this tenant's active credential scopes; no live requests |
| `/account` ‡ | Admin · Dev | own record only |
| `/users` † | Admin | invite dialog; duplicate email = conflict |
| `/users/:userId` † | Admin | gate 4; last active administrator cannot be demoted or disabled |
| `/audit` ‡ | Admin | tenant-scoped, redacted |
| `/products` | Dev | ineligible products marked "ineligible" |
| `/products/new` | Dev | duplicate id conflict, quota banner |
| `/products/sync` | Dev | two-phase; phase 2 counts link to `/submissions/:id` |
| `/products/:productId` | Dev | gate 4; disable dialog requires a reason |
| `/events/submit` | Dev | single / batch; duplicate confirmed is a success outcome |
| `/submissions/:submissionId` | Dev | gate 4; polled; serves product-sync and event-batch; no index route |
| `/training` | Admin | Start training disabled while a job runs / quota exhausted (concurrency 1) |
| `/training/:jobId` | Admin | gate 4; polled stage rail; cancel gated on cancellable state |
| `/models` | Admin | header counts active / desired / eligible / retired / failed; explicit empty state |
| `/models/:versionId` | Admin | gate 4; activate (eligible only), roll back (retained target), archive (inactive, unprotected) |
| `/usage` | Admin | unavailable measurement shows a status, never a zero |
| `/service-status` | Admin | desired vs ready capacity, fallback rate, recent errors |

Tenant Administrator has **no** catalog or event routes. Tenant Developer has **no**
training, model, usage or service routes. `/account` sits in the layout footer menu,
not the sidebar.

## Platform — PlatformLayout (per-route named permission, no tenant switcher)

| Route | Permission |
|---|---|
| `/admin/tenants` | `platform permission` |
| `/admin/tenants/:tenantId` | `platform permission` (route) — status section `platform permission`, plan section `plan-management permission`, usage section `authorized platform scope`; missing permissions withhold the **section**, not the route |
| `/admin/plans` · `/admin/plans/:planId` | `plan-management permission` |
| `/admin/usage` | `authorized platform scope` |
| `/admin/status` | `monitoring access` |
| `/admin/audit` | `audit permission` — tabs Failures \| Audit records |

## Errors (rendered inside the active layout)

`/403` gate 3, terminal, no retry · `/404` gate 4, never names the resource type ·
`/error` carries a traceable reference, no credentials, no other tenant's data.

## Dialogs (never routes)

One-time credential secret (shown once, not re-openable) · create / rotate / revoke
credential (scopes are a field group in create and rotate) · disable product (reason
required) · start training · cancel training (reason required) · activate / roll back
(reason required) / archive version · invite user · change role · resend invitation ·
lock / unlock / disable / re-enable user · tenant status change (reason required) ·
assign plan · approve quota override · close plan to new assignments.

## Not built, deliberately

No UI for recommendation request, results or feedback; no customer entity anywhere;
no snapshot / graph / training internals beyond stage names; no idempotency,
autoscaling, retry or audit-writing surfaces.

## Reviewing the prototype

The bar at the bottom is prototype scaffolding, not product chrome: switch identity
(Tenant Administrator / Developer / Platform Administrator / locked user / signed
out), change tenant status to exercise gate 2, toggle the five named platform
permissions to watch the sidebar and the composed tenant-detail sections change, probe
gate 4 with a foreign version id, and switch theme. Set `showReviewBar` to false to
hide it.

## For the React build

- Routes above map 1:1 to nested React Router routes; the four layout shells are layout
  routes. Gates 1–3 belong in the layout route loaders, gate 4 in each detail route's
  loader, gate 5 in the page component.
- Page content in the prototype is produced by one `pg_<routeId>` function per route
  plus a shared renderer (header, banner, stats, stage rail, definition list, filter
  bar, table, panels, dialog). In React those become the component set in §11:
  `Button, Input, Select, Textarea, Table, Badge, Dialog, Banner, Skeleton, EmptyState,
  Breadcrumbs, Sidebar, StatCard, Tabs, Pagination, FilterBar, CopyField, StageRail,
  DefinitionList`.
- State enumerations and their fixed semantic colors are in the `GROUPS` map; the
  training state machine is `JOB_STAGES`; credential scopes are `SCOPES`; platform
  permissions are `PERMS`.
- Visual tokens come from the bound Modernist design system (`_ds/…/styles.css`), not
  from the §11 Claude palette — that was the user's call. Semantic state colors
  (`--ok / --warn / --danger / --info / --neu`) are defined alongside it for both
  themes, since Modernist is a mono palette with no state roles.
