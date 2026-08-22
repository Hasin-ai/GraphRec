# GraphRec Frontend — Build Prompt

> Copy everything below the line into a fresh session. It is self-contained: the recipient does not need the SRS.

---

You are building the complete frontend for **GraphRec**, a multi-tenant recommendation platform. Every route, role, permission and state below is derived from the project's SRS and its use-case, activity, ER and pipeline diagrams. **Build exactly this. Do not add features that are not listed, and do not drop any that are.**

## 1. What GraphRec is

GraphRec provides recommendation-as-a-service to independent e-commerce businesses ("tenants"). Each tenant synchronizes a product catalog, streams customer interaction events, trains a tenant-specific DGSR (dynamic graph sequential recommendation) model, reviews model quality, activates a version, and then receives real-time Top-N recommendations through a server-to-server API. A platform operator oversees all tenants, plans, quotas, health and audit history.

The frontend you are building is the **operator console** — the "Tenant Admin Dashboard". It is not the shopping site, and it is not the recommendation API. Recommendations themselves are never rendered here.

This is a bounded academic project: at most four active tenants, offline batch training with global concurrency of 1, no payment processing, no multi-region.

## 2. Tech stack

- React 18 + TypeScript, Vite
- React Router v6 (nested routes, layout routes, `loader`-style data fetching or TanStack Query — your choice, be consistent)
- Plain CSS or CSS Modules with the design tokens in §11. No Tailwind, no component library — build the components.
- Vitest + React Testing Library for the tests you write
- All backend calls go through a typed `src/api/*` layer against the endpoints in §2b

**No backend currently exists.** Build the API layer against §2b as a contract, with typed request/response models you define and a mock adapter so every screen is runnable and testable without a server. Keep the mock behind one swappable module — do not scatter fixtures through components.

## 2b. API contract

Paths recovered from a prior implementation of this system. Treat them as authoritative for **shape and naming**; request and response bodies are yours to define, derived from the entity fields in §7.

| Endpoint | Frontend route |
|---|---|
| `POST /login` · `POST /setup-password` | `/login` · `/invite/accept` † |
| `GET/POST /api-keys` · `GET/DELETE /api-keys/{id}` · `POST /api-keys/{id}/rotate` | `/credentials` |
| `GET /v1/products` · `GET/PUT/PATCH /v1/products/{external_id}` | `/products` · `/products/:productId` |
| `POST /v1/products:bulk-upsert` | `/products/sync` |
| `POST /v1/products/{external_id}:disable` | Disable dialog |
| `POST /v1/events` · `POST /v1/events/batches` | `/events/submit` |
| `GET /v1/events/batches` · `GET /v1/events/batches/{batch_id}` | `/submissions/:submissionId` |
| `POST /v1/training-jobs` · `GET /v1/training-jobs` | `/training` |
| `GET /v1/model-versions` · `GET /v1/model-versions/{version_id}` | `/models` · `/models/:versionId` |
| `POST /v1/model-versions/{version_id}:activate` | Activate dialog |
| `POST /v1/models/{model_id}:rollback` | Roll-back dialog |
| `POST /v1/model-versions/{version_id}:archive` | Archive dialog |
| `GET /v1/datasets/snapshots/{snapshot_id}` | Snapshot panel on `/training/:jobId` |
| `GET /v1/deployment` · `/replicas` · `/autoscaling` · `/v1/metrics/summary` | `/service-status` |
| `GET /usage` · `GET /subscription` | `/usage` |
| `GET /tenants` · `GET /tenants/{id}` · `POST /tenants/{id}/status` | `/admin/tenants` · `/admin/tenants/:tenantId` |
| `GET /plans` · `POST /tenants/{id}/quotas` | `/admin/plans*` · tenant detail |
| `GET /status` · `GET /failures` · `GET /audit` | `/admin/status` · `/admin/audit` |
| `POST /v1/recommendations` · `/session` · `/v1/feedback/*` | **none** — server-to-server only, build no UI |

**Endpoints the 36 routes need that this inventory lacks.** Define these yourself in the same style:

- `GET /v1/training-jobs/{job_id}` and `POST /v1/training-jobs/{job_id}:cancel` — `/training/:jobId` cannot work without both
- A unified submission read covering product-sync results, not just event batches — `/submissions/:submissionId` serves both
- Tenant user CRUD and invitation — `/users`, `/users/:userId` †
- Platform authentication and a permission-bearing platform identity — `/admin/login` †
- Tenant-scoped audit read — `/audit` ‡ (the existing `GET /audit` is platform-scoped)

## 3. Actors

| Actor | Human? | Uses this frontend? |
|---|---|---|
| **Tenant Administrator** | Yes | Yes — training, models, usage, status, credentials |
| **Tenant Developer** | Yes | Yes — catalog, events, submissions, credentials |
| **Platform Administrator** | Yes | Yes — tenants, plans, cross-tenant usage, health, audit |
| **Tenant E-Commerce Application** | No | **No** — server-to-server API client only |
| E-Commerce Customer | Yes | **No** — never contacts GraphRec directly |

Only three roles get screens. The Tenant E-Commerce Application authenticates with an API credential and never renders a page — build **nothing** for it.

## 4. The authorization model — five gates

Evaluate in this exact order. A later gate assumes earlier ones passed. Gates 1–3 guard routes; gates 4–5 guard individual actions.

| # | Gate | Blocks on | Result |
|---|---|---|---|
| 1 | **Identity** | No session; user status is `invited`, `locked` or `disabled` | Redirect to `/login` |
| 2 | **Tenant state** | Tenant status is not `active` | `/account/tenant-status`, navigation suppressed |
| 3 | **Role / permission** | Role or named permission not held | `/403` |
| 4 | **Ownership** | Resource belongs to a different tenant | `/404` — **never** `/403` |
| 5 | **Resource state** | Lifecycle forbids the action | Disabled control + inline reason. **No route change.** |

**Three rules that are easy to get wrong:**

1. **No tenant identifier appears in any tenant route path.** Tenant identity is derived server-side from the session. A `/t/:tenantId/...` shape is forbidden. Only `/admin/tenants/:tenantId` names a tenant, and that is platform scope.
2. **Gate 4 must run before gate 5.** If eligibility were checked first, probing with another tenant's version id would return "not eligible" instead of "not found" — leaking that the resource exists.
3. **A foreign resource is indistinguishable from a missing one.** Never render "you don't have access to this job" or name the resource type on `/404`.

Guards must be real route guards, not hidden buttons. The backend remains the authority; the frontend enforces the same rules so the UI never offers an action that will be rejected.

### Named platform permissions

The Platform Administrator is **not** one blanket role. Five independently grantable permissions:

| Permission | Grants | Routes |
|---|---|---|
| `platform permission` | Tenant accounts and status transitions | `/admin/tenants`, `/admin/tenants/:tenantId` |
| `plan-management permission` | Plan limits, tenant assignment, quota overrides | `/admin/plans`, `/admin/plans/:planId`, plan controls on tenant detail |
| `authorized platform scope` | Cross-tenant usage summaries | `/admin/usage`, usage panel on tenant detail |
| `monitoring access` | Shared health, workload, capacity, failures | `/admin/status` |
| `audit permission` | Redacted failures and audit history | `/admin/audit` |

`/admin/tenants/:tenantId` **composes three permissions** — its status, plan and usage sections each render only if the corresponding permission is held. A holder of only `platform permission` sees the page with the other sections withheld, not a whole-route 403. The platform sidebar filters per permission, and `/admin` redirects to the first permitted route.

### Tenant role capabilities

Derived from role. The two tenant roles barely overlap — they share only sign-in and credentials.

| Capability | Tenant Admin | Tenant Dev |
|---|---|---|
| Credential management | Yes | Yes |
| Tenant user management **†** | Yes | **No** |
| Catalog write (add / update / disable / synchronize) | **No** | Yes |
| Event submission | **No** | Yes |
| Submission result read | **No** | Yes |
| Training request & cancellation | Yes | **No** |
| Model version read | Yes | **No** |
| Model activate / roll back / archive | Yes | **No** |
| Usage, quota, model and service status | Yes | **No** |

The Tenant Administrator having **no** catalog access is intentional and comes straight from the use-case diagrams.

## 5. Complete route tree

Three tiers, all to be built:

- unmarked — traced to a use case or functional requirement (29)
- **†** — **required beyond the SRS** (4). Load-bearing: without them 14 of the unmarked routes are unreachable. See §5b.
- **‡** — **platform completeness** (3). Each has a textual hook in the SRS but no use case. See §5c.

```
/                                    redirect by identity → /home | /admin | /login

├── PublicLayout                     unauthenticated
│   ├── /register
│   ├── /login
│   ├── /recover
│   ├── /recover/confirm
│   ├── /invite/accept               †
│   └── /admin/login                 †  separate platform realm
│
├── StateGateLayout                  authenticated · tenant not active
│   └── /account/tenant-status
│
├── TenantLayout                     authenticated Tenant User · tenant from session
│   ├── /home                                        [Admin · Developer]
│   ├── /credentials                                 [Admin · Developer]
│   ├── /integration                 ‡               [Admin · Developer]
│   ├── /account                     ‡               [Admin · Developer]
│   ├── /users                       †               [Admin]
│   │   └── /users/:userId           †
│   ├── /audit                       ‡               [Admin]
│   ├── /products                                    [Developer]
│   │   ├── /products/new
│   │   ├── /products/sync
│   │   └── /products/:productId
│   ├── /events/submit                               [Developer]
│   ├── /submissions/:submissionId                   [Developer]
│   ├── /training                                    [Admin]
│   │   └── /training/:jobId
│   ├── /models                                      [Admin]
│   │   └── /models/:versionId
│   ├── /usage                                       [Admin]
│   └── /service-status                              [Admin]
│
├── PlatformLayout                   Platform Administrator · per-route permission
│   ├── /admin                       redirect → first permitted route
│   ├── /admin/tenants
│   │   └── /admin/tenants/:tenantId
│   ├── /admin/plans
│   │   └── /admin/plans/:planId
│   ├── /admin/usage
│   ├── /admin/status
│   └── /admin/audit                 tabs: Failures | Audit records
│
└── Error routes                     rendered inside the active layout
    ├── /403
    ├── /404
    └── /error
```

36 addressable routes, 3 redirects, 4 layout shells.

## 5b. The four routes beyond the SRS

The SRS models no way to create a Tenant Developer or to authenticate a Platform Administrator. Taken literally it produces a system only its single registration-time administrator can ever use. These four routes close that, and nothing else in this prompt goes beyond the specification.

**`/users`** — Tenant Administrator only. List of tenant users: display name, email, role, status, created-at, last-authenticated-at. Action: **Invite user** (dialog — email, display name, role). Filter by role and status.

**`/users/:userId`** — Detail plus dialogs: **Change role**, **Resend invitation**, **Lock**, **Unlock**, **Disable**, **Re-enable**. Constraints:
- `(tenant, email)` is unique → a duplicate email is a **conflict**, not a validation error
- The role selector offers exactly `tenant administrator` and `tenant developer` — no other value is permitted
- User status: `invited` · `active` · `locked` · `disabled`
- The **last active administrator cannot be demoted or disabled** — disable the control and say why. This is a derived safety rule, not from the SRS.

**`/invite/accept`** — Public, token-based. The invited person sets their own authentication material, moving them `invited → active`. Mirrors `/recover/confirm`. Expired or invalid tokens are rejected without disclosing account details. On success → `/login`.

**`/admin/login`** — Platform Administrator sign-in, a **separate authentication realm** from `/login`. A platform operator is not a tenant user and resolves no tenant scope. Non-disclosing errors. On success → `/admin`. This assumes a backend platform-identity holding the five named permissions; if the API does not yet expose one, build the screen against the contract and surface a clear failure.

## 5c. Platform completeness routes

Optional but expected of anything presented as a platform. Each has an SRS hook; none has a use case.

**`/integration`** — Tenant Administrator and Developer. The API contract, in one place. Base URL and authentication scheme; endpoint reference for catalog sync, event submission (single and batch), submission result, recommendation request and feedback; request and response shapes; the error vocabulary (validation, conflict, limit, unavailable) including the traceable error reference; idempotency-key semantics for external identifiers; and **this tenant's own active credential prefixes with their granted scopes**, so the reader sees which operations their integration may actually perform. Copy buttons on every snippet. **Not** a live playground — do not issue real requests.
*Hook: NR-NF-07 — "documented requests and responses".*

**`/account`** — Any tenant user, their own record only. Edit display name; change authentication material (current + new + confirm). Read-only: role, tenant, account status, last-authenticated-at. Does **not** manage other users.
*Hook: §5.2.3 `display_name`, `credential_digest`.*

**`/audit`** — Tenant Administrator only. Tenant-scoped, read-only, redacted action history. Filter by action type and time. Columns: occurred-at, actor type, action type, resource, outcome. Never exposes credential secrets, raw event payloads, or any hint that another tenant exists.
*Hook: §5.2.16 "in tenant-facing views" and Rule 12 "tenant-facing audit queries" — both presuppose the view exists.*

**Onboarding checklist — a component on `/home`, not a route.** A dismissible progress list following §3.5's ordered story: configure users → create credential → synchronize catalog → submit events → request training → review quality → activate a version → monitor. Each step deep-links to the route that performs it and reflects real state (catalog non-empty, events received, a succeeded job exists, a version active). Not a wizard — every step is already a route.

## 6. Layout shells

| Shell | Session & scope | Chrome |
|---|---|---|
| **PublicLayout** | No session, no tenant | Brand only. No navigation — nothing is permitted yet. |
| **TenantLayout** | Tenant from credentials; every query tenant-scoped server-side | Role-filtered sidebar, tenant name, active-model + service badge, sign out |
| **PlatformLayout** | Platform scope, not a Tenant User | Separate sidebar filtered per permission. **No tenant switcher** — tenant is a filter, not a scope. |
| **StateGateLayout** | Session valid, tenant not active | Message and status only, navigation suppressed |

Detail routes nest under their collection route and inherit its layout and data scope. After a terminal action, return the user to the collection view.

## 7. Route specifications

### Public

**`/register`** — Standalone form. Inputs: business name, administrator identity, contact information. Creates the tenant *and* its initial administrator; the registrant becomes that administrator. Duplicate or invalid registration is rejected inline with correction guidance and the form stays filled. On success → `/login`.

**`/login`** — Standalone form. Rejects invalid, inactive and rate-limited attempts with a **non-disclosing** message (never reveal whether the account exists). On success, resolve role and route to `/home` or `/admin`. Link to `/recover`.

**`/recover`** — Step 1. Account identifier only. The response states the next action **without confirming whether the account exists**.

**`/recover/confirm`** — Step 2. Recovery proof plus new authentication material. Expired or invalid proof rejected without disclosing account details. On success → `/login`.

### Tenant — shared

**`/home`** — The permitted-services launcher. Shows only the modules this role may enter, so an Administrator and a Developer see materially different pages. This is a launcher, **not** an analytics dashboard — do not add charts or KPI tiles.

**`/credentials`** — List + dialogs. Columns: credential name, visible prefix, allowed integration operations, expiry, revoked-at, created-at, last-used-at. Expired and revoked credentials render as unable to authorize.
Actions (all dialogs): **Create**, **Rotate**, **Revoke**.
The **one-time secret must be a modal shown exactly once** — never a route, never re-openable. The full secret is not retained by the system and is displayed only at creation or rotation.
Credential scopes are assigned inside the create/rotate dialog, from this operation set: catalog write & synchronization · event submission (single and batch) · recommendation requests · recommendation feedback · submission result read.

### Tenant — Developer

**`/products`** — List with filter. Columns: external product id, title, category, brand, price, active flag, availability status, updated-at. Mark ineligible products visibly — they are never returned by serving. Actions: filter, open, add, synchronize.

**`/products/new`** — Form. Tenant-local product identifier plus product information. Report duplicate identifier, invalid data and quota excess inline.

**`/products/sync`** — Two-phase page. Phase 1: bounded product collection + synchronization identifier. Phase 2: **accepted / updated / skipped / failed** counts. Oversized or invalid submissions are rejected or partially reported. Link through to the full result at `/submissions/:submissionId`.

**`/products/:productId`** — Detail + edit. Report missing product or conflicting update as a state conflict. Actions: **Update**; **Disable** (confirmation dialog requiring a reason).

**`/events/submit`** — Form supporting single event and batch. Single: event identifier, customer identifier, product identifier, event type, occurred-at, optional context and value. Batch: bounded event collection + batch identifier. Returns acceptance, **duplicate confirmation**, or a batch identifier with initial counts. Link to the result.

**`/submissions/:submissionId`** — Polled detail, serving **both** product-sync and event-batch results: processing status, counts, safe error details. A foreign identifier returns no resource details. There is deliberately **no index route** — reach it from a submission.

### Tenant — Administrator

**`/training`** — Job list with filter. Columns: state, requested model type, requested-at, completed-at, requester. Header shows the **one-active-job rule** and current eligibility (data sufficiency, quota, cooldown).
Action: **Start training** — a dialog taking model type, bounded configuration and a request identifier. Gate 5 applies: disable with reason when data is insufficient, quota is exhausted, cooldown is active, or a job is already running. Surface rejection reasons inline in the dialog.

**`/training/:jobId`** — Polled detail. Render the current stage and progress across the full state machine, plus timestamps and sanitized failure reason:

```
queued → waiting_for_resources → preparing_data → building_graph
       → training → evaluating → indexing_embeddings → registering → succeeded

any active state → cancelling → cancelled
any active state → failed
```

On terminal success: quality measures (Recall@10, HR@10, NDCG@10, Coverage) and a link to the produced model version. On failure or cancellation: safe reason and **no version**.
Action: **Cancel** — confirmation dialog with reason, gated on the job being in a cancellable state.

**`/models`** — Version list. Columns: version number, model type, lifecycle status, created-at, quality summary, active indicator. The header consolidates model status — counts of active, desired, eligible, retired and failed. Render an **explicit empty state** when no model exists.
Lifecycle states: `registered` · `eligible` · `active` · `retired` · `rejected` · `archived` · `failed_deployment`.

**`/models/:versionId`** — Detail + dialogs. Shows evaluation measures with **comparison against baseline and the current active version**, eligibility, feature contract, artifact digest, dataset snapshot and producing job. If activation previously failed, show that alongside the still-active previous version.
Actions, each a confirmation dialog and each gated on resource state:
- **Activate** — requires the version to be eligible. If activation fails, the previous version **must remain active** and the UI must say so.
- **Roll back** — dialog listing eligible retained targets; validate the target before the active version changes.
- **Archive** — requires the version to be inactive and not required for rollback; active and protected versions are rejected in place.

**`/usage`** — Filtered report. Per usage type: measured quantity, effective limit, remaining allowance where calculable, reset period. Plus summarized trends by period. Unavailable measurements show a safe status, never a blank or a zero.
Usage types: `events` · `recommendations` · `training` · `products` · `storage` · `service_capacity`.

**`/service-status`** — Status board with optional time range. Shows availability, active version, **desired vs ready capacity**, last transition, recent errors and fallback rate. Missing service or measurement delay is stated explicitly.
Deployment states: `pending` · `progressing` · `available` · `degraded` · `rolling_back` · `stopped`.

### Platform Administrator

**`/admin/tenants`** — List: tenant code, name, status, assigned plan, created-at. Actions: filter, open, change status (dialog + reason). Tenant states: `pending` · `active` · `suspended` · `deleting` · `deleted`.

**`/admin/tenants/:tenantId`** — Composed detail. Three permission-gated sections: **status and lifecycle** (`platform permission`), **plan assignment and approved quota overrides with effective period** (`plan-management permission`), **usage summary** (`authorized platform scope`) — the last excluding private event payloads. Each action is a dialog and each writes an audit record.

**`/admin/plans`** — List: plan code, name, event / recommendation / training limits, additional service limits, whether new assignments are allowed. Actions: open, create.

**`/admin/plans/:planId`** — Detail + edit. Plan limits and assigned tenants. Reject invalid, conflicting and negative limits with the conflict named. Action: close plan to new assignments.

**`/admin/usage`** — Cross-tenant usage by tenant, period and usage type. **Excludes private event payloads.** Out-of-scope tenants are rejected, not shown empty.

**`/admin/status`** — Shared service health, workload, capacity and failure summary over a time range. **Measurement gaps are identified as gaps, never rendered as zero.**

**`/admin/audit`** — One route, two tabs.
- *Failures* — redacted terminal failures, filtered by severity and time.
- *Audit records* — immutable append-only history, filtered by tenant, action type and time. Columns: actor type, action type, resource type, outcome, occurred-at, correlation reference. Sensitive details stay redacted.
- `actor_type`: `tenant_user` · `tenant_application` · `platform_administrator` · `system_process`
- `action_type`: `credential` · `training` · `activation` · `rollback` · `quota` · `tenant` · `access` · `security`
- `outcome`: `succeeded` · `failed` · `denied` · `cancelled`

### Error routes

**`/403`** — Gate 3. **Terminal by design** — offer no retry. The activity diagram routes permission errors straight to exit.
**`/404`** — Gate 4. Resource missing *or* foreign, deliberately indistinguishable. Never name the resource type.
**`/error`** — Unhandled failure carrying a **traceable error reference**, with no credentials and no other tenant's information.
**`/account/tenant-status`** — Gate 2. States the tenant's lifecycle position and that a Platform Administrator controls the transition.

## 8. Build these as dialogs / inline, NOT routes

| Capability | Form | Why |
|---|---|---|
| One-time credential secret | Modal, shown once | The secret is displayed only at creation or rotation and never retained. A route is bookmarkable — that contradicts it. |
| Create / rotate / revoke credential | Dialogs | One use case, one action-selection step |
| Assign credential scopes | Field group in the create/rotate dialog | An input to the action |
| Disable product | Confirmation dialog + reason | Inline action on an existing product |
| Start model training | Dialog on `/training` | Rejection reasons belong beside the trigger |
| Cancel training | Confirmation dialog | An actor step inside the monitoring loop |
| Activate / roll back / archive model | Confirmation dialogs | Each is a "confirm" step returning to the same detail view |
| Quality comparison vs baseline & active | Panel in version detail + activation dialog | An input to the activation decision |
| Ineligible-action feedback (gate 5) | Disabled control + inline reason | Returns to "perform another action?" on the same screen |
| Validation / conflict / limit errors | Inline banner on the originating page | The workflow loops back to "correct supplied information" on the same screen |
| Duplicate submission accepted | Status component | A success outcome, not an error |
| Quota rejection | Inline banner at the point of action | Enforced before the operation is accepted |
| Fallback / degraded indicator | Status badge in the tenant layout | A continuous property, not a destination |
| Tenant status / plan / quota override | Dialogs on tenant detail | "Review and confirm → validate → apply and audit → display updated" |
| Failures vs audit records | Two tabs, one route | A single use case covers both |
| Sign out | Inline action in the layout | Terminates the session; needs no address |

## 9. Do NOT build — backend only

Build no UI for any of these. They exist, but no human actor interacts with them.

- **Recommendation request, results and feedback.** The core product is entirely server-to-server (`POST /v1/recommendations`). Its only trace in the UI is the fallback rate and recent errors on `/service-status`.
- Snapshot construction, graph building, DGSR training, bundle export, Qdrant indexing — surfaced only as stage names on `/training/:jobId`
- Candidate retrieval, eligibility filtering, scoring, re-ranking
- Idempotency and duplicate detection — surfaced as "duplicate confirmed"
- Serving-capacity autoscaling — surfaced as desired vs ready capacity
- Cold-start and session-blended strategies
- Retry policy, dead-letter handling
- Audit record *writing*, Qdrant collection lifecycle, row-level tenant isolation
- **Customer entity** — no screen reads, lists or manages customers anywhere
- **Recommendation Request / Result / Feedback records** — no browsing UI for any human actor

## 10. Required UI states

Every list, detail and form implements the states that apply to it:

- **Loading** — skeleton for lists and detail panels; never a bare spinner on a full page
- **Empty** — explicit and specific ("No model versions yet"), never a blank region
- **Validation error** — field-level, inline, form stays filled, focus moves to the first error
- **Conflict** — name the conflict ("a product with this identifier already exists")
- **Limit / quota exceeded** — inline banner at the point of action, stating the limit and reset
- **Forbidden** — `/403`, terminal
- **Not found** — `/404`, non-disclosing
- **Temporarily unavailable** — status component, with fallback indicated where permitted
- **Processing / progress** — polled, with the current stage named
- **Success** — confirm what happened in the past tense, then offer the next action
- **Failure** — sanitized reason plus a traceable reference; never raw stack traces
- **Confirmation** — for every destructive or state-changing action; require a reason where the spec says so

## 11. Design system — Claude

### The stance

Warm, editorial, quiet. This is an operator console for a machine-learning platform: people come to it to check a training job, judge whether a model is safe to activate, and find out why something failed. It should feel like a well-set reference document that happens to be interactive — **not** a analytics product, and not a generic admin template.

Three principles, in priority order:

1. **Legibility over density.** Someone reading `indexing_embeddings` at 2am should not have to squint. Generous line height, real whitespace between groups, never more than one accent per screen region.
2. **State is the content.** Almost every screen's job is to communicate a lifecycle position — job state, model lifecycle, deployment health, tenant status. Encode it in *form as well as text*: a pill with semantic color, a severity stripe, a progress rail. Never a bare string in a table cell.
3. **Quiet by default, loud only for consequence.** Activation, rollback, archive, revoke and tenant suspension change production behavior. Those are the only places that get danger color and a confirmation.

Ivory grounds, one clay accent, serif headings over a clean sans. Restraint over decoration. No gradients, no glassmorphism, no emoji as iconography, no drop shadows heavier than a hairline lift.

### Color tokens

```css
:root {
  --paper:        #faf9f5;   /* page ground, ivory */
  --surface:      #ffffff;   /* cards, tables */
  --surface-sunk: #f0eee6;   /* table headers, wells, cream */
  --ink:          #141413;
  --ink-soft:     #3d3d3a;
  --muted:        #6f6e69;
  --rule:         #e5e3da;
  --rule-strong:  #cfccc0;
  --accent:       #c15f3c;   /* clay */
  --accent-soft:  #f6eae3;
  --accent-ink:   #a34e2e;

  --ok:      #4f6f4a;   --ok-bg:      #e8efe6;
  --warn:    #9a6a12;   --warn-bg:    #f6efdd;
  --danger:  #8e4747;   --danger-bg:  #f4e6e3;
  --info:    #47607a;   --info-bg:    #e7ebef;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #1f1e1d;  --surface: #262624;  --surface-sunk: #30302e;
    --ink: #f5f4ef;    --ink-soft: #c9c7bf; --muted: #91908a;
    --rule: #3a3937;   --rule-strong: #52514d;
    --accent: #d97757; --accent-soft: #3a2a22; --accent-ink: #e89b7f;
    --ok: #8fb489;     --ok-bg: #222b20;
    --warn: #d6ac5e;   --warn-bg: #332715;
    --danger: #d89494; --danger-bg: #332321;
    --info: #9fbbd4;   --info-bg: #212b33;
  }
}
:root[data-theme="dark"] { /* repeat the dark block so the toggle wins both ways */ }
```

Define every color as a token on bare `:root` first, then redefine tokens only inside the media query and `[data-theme]` blocks. Never give a color its only definition inside a theme block. Give `body` an explicit token background.

### Typography

| Role | Stack | Usage |
|---|---|---|
| Display | `"Tiempos Text", Charter, "Iowan Old Style", Georgia, serif` | Page titles, section headings, card titles. Weight 500, letter-spacing `-0.015em`. |
| UI / body | `"Styrene B", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` | Everything interactive, table content, labels |
| Mono | `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` | Routes, identifiers, digests, state names, timestamps |

Uppercase labels get `letter-spacing: 0.09em` and `font-size: 10.5px`. Any column of digits gets `font-variant-numeric: tabular-nums`. Body copy stays near 65–75 characters wide.

### Shape, spacing, motion

- Radii: **12px** cards / tables / dialogs, **8px** inputs / buttons, **20px** pills and badges
- Spacing on a 4px scale; use flex/grid `gap`, not per-element margins
- Shadows subtle: `0 1px 2px rgba(20,20,19,.05), 0 10px 30px -20px rgba(20,20,19,.35)`
- Wide tables scroll inside their own `overflow-x: auto` container — the page body never scrolls sideways
- Motion: 120–180ms ease-out on hover and dialog entry. Respect `prefers-reduced-motion`.
- Visible focus ring on every interactive element: `2px solid var(--accent)`, `outline-offset: 2px`

### Semantic color is not the accent

Clay is the brand and the interaction color: links, primary buttons, focus rings, active nav. It **never** means "success" and never carries state meaning. Lifecycle and outcome use `--ok / --warn / --danger / --info`. A screen where the accent and a semantic color compete for the same attention is wrong — pick one.

Map every enumeration to a fixed color so it reads the same everywhere:

| State group | Neutral | Info | Warn | Danger | OK |
|---|---|---|---|---|---|
| Training job | `queued`, `waiting_for_resources` | `preparing_data`, `building_graph`, `training`, `evaluating`, `indexing_embeddings`, `registering` | `cancelling`, `cancelled` | `failed` | `succeeded` |
| Model lifecycle | `registered`, `archived` | `eligible` | `retired`, `rejected` | `failed_deployment` | `active` |
| Deployment | `stopped` | `pending`, `progressing` | `degraded`, `rolling_back` | — | `available` |
| Tenant | `deleted` | `pending` | `suspended`, `deleting` | — | `active` |
| Tenant user | — | `invited` | `locked` | `disabled` | `active` |
| Audit outcome | `cancelled` | — | `denied` | `failed` | `succeeded` |

### Components to build

`Button` (primary / secondary / danger / ghost; loading and disabled states) · `Input` `Select` `Textarea` with label, hint and error slot · `Table` with sticky header, sortable columns, empty state and loading skeleton · `Badge` (pill, semantic, per the map above) · `Dialog` (focus trap, Esc to close, confirm/cancel, optional required-reason field) · `Banner` (info / success / warning / danger; inline, dismissible where non-blocking) · `Skeleton` · `EmptyState` (icon-free, headline + one sentence + primary action) · `Breadcrumbs` · `Sidebar` (role-filtered, grouped with hairline dividers) · `StatCard` · `Tabs` · `Pagination` · `FilterBar` · `CopyField` (for identifiers, prefixes, digests) · `StageRail` (the training progress indicator) · `DefinitionList` (label/value pairs on detail pages)

### Patterns that recur

**Tables** are the dominant surface — products, versions, jobs, users, tenants, plans, audit. One treatment throughout: sticky header in `--surface-sunk` with 10.5px uppercase labels; 12px/15px cell padding; hairline `--rule` row separators, none after the last row; identifiers and timestamps in mono with `tabular-nums`; state as a `Badge`, never plain text; row actions right-aligned and revealed on hover *and* on focus. Wide tables scroll in their own container.

**Detail pages** open with a header block — title, state badge, and the one or two actions that matter — then a `DefinitionList` of attributes, then subordinate panels. Actions live in the header, not scattered.

**Dialogs** are 480px for confirmations, 640px for forms. Title states the action in the imperative ("Activate version 7"). Body states the consequence in one sentence, including what happens on failure where the spec says so ("If activation fails, version 6 remains active."). Destructive confirms use a danger primary button labelled with the verb — never "OK".

**Forms** label above input, hint below, error replaces hint in `--danger`. Errors appear on submit, not on keystroke. The form stays filled and focus moves to the first invalid field. Submit shows a loading state and disables; it does not disappear.

**Polled views** (`/training/:jobId`, `/submissions/:submissionId`) show the stage name, a `StageRail`, and a quiet "updated 3s ago". Never a full-page spinner on refresh — update in place so the reader doesn't lose their position.

### Copy

Write from the operator's side. Name things as the SRS names them — the domain vocabulary *is* the interface language, so `model version`, `training job`, `dataset snapshot`, `credential`, not invented synonyms.

- Buttons are verbs: "Activate", "Roll back", "Revoke", "Invite user"
- Confirmations state the consequence, then the verb
- Success messages are past tense and specific: "Version 7 activated." Not "Success!"
- Errors say what went wrong and what to do: "A product with identifier `SKU-4471` already exists. Use a different identifier or update the existing product." Never "An error occurred", never an apology
- Empty states name the thing and offer the next step: "No model versions yet. Train a model to produce your first version."
- Non-disclosing messages stay non-disclosing — never soften `/404` into "you may not have access"

### Breadcrumbs

Tenant name is the root crumb, because tenant scope lives in the session rather than the path.

```
{Tenant} › Products › {external_product_id}
{Tenant} › Training › Job {short id} · {state}
{Tenant} › Model Versions › v{version_number}
Platform › Tenants › {tenant_code}
Platform › Failures & Audit › {active tab}
```

Public and error routes carry **no** breadcrumb — no session means no root crumb, and 403/404 must not name what was sought.

## 12. Navigation per role

**Tenant Administrator** — Home · API Credentials · Integration **‡** · Users **†** — Training · Model Versions — Usage & Quotas · Service Status · Audit **‡**
*(no catalog or event entries)*

**Tenant Developer** — Home · API Credentials · Integration **‡** — Products · Synchronize Catalog · Submit Events
*(submission results are reached from a submission, not the sidebar)*

`/account` **‡** belongs in the user menu in the layout header alongside sign out — not in the sidebar.

**Platform Administrator** — Platform Status · Tenants · Plans & Quotas · Tenant Usage · Failures & Audit
*(each entry renders only if its named permission is held)*

## 13. Hard constraints

1. Build every route in §5, §5b and §5c, and every action in §7. Nothing more.
2. No tenant identifier in any tenant route path.
3. Foreign resource → `/404`, never `/403`.
4. Guards are real route guards, not hidden buttons.
5. Gate 5 disables controls in place with a stated reason — it never navigates.
6. The one-time credential secret is a modal, shown once, never a route.
7. Build no UI for recommendations, feedback, or customers.
8. Every destructive action gets a confirmation dialog; those specified with a reason require one.
9. Both light and dark themes fully token-defined across all three viewer states.
10. Every interactive element is keyboard reachable with a visible focus state; dialogs trap focus.

## 14. Deliverable

- Complete `src/` with routes, layouts, pages, components, guards and a typed API layer
- Vitest coverage for: each guard's allow and deny path, the gate-4 → `/404` behavior, one full workflow per role
- A short `ROUTES.md` mapping each route to its role, permission and gates

Build it in dependency order: tokens and primitives → layouts and guards → public routes → tenant routes → platform routes → error routes → tests. Report what you built and anything you could not.
