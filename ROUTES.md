# GraphRec Frontend Routes

36 addressable routes, 3 redirects, 4 layout shells. Roles: **TA** Tenant Administrator · **TD** Tenant Developer · **PA** Platform Administrator.

Authorization gates, evaluated in order — 1 identity · 2 tenant state · 3 role/permission · 4 ownership · 5 resource state. Gates 1–3 guard routes; 4–5 guard actions.

## Route tiers

| Tier | Mark | Count | Meaning |
| --- | --- | --- | --- |
| **1 — SRS** | none | 29 | Traced to a use case or functional requirement. Build all. |
| **2 — Required beyond SRS** | **†** | 4 | Load-bearing. The SRS models no way to create a Tenant Developer or authenticate a Platform Administrator, leaving 14 of its own routes unreachable. See [Beyond the SRS](#beyond-the-srs). |
| **3 — Platform completeness** | **‡** | 3 | Optional. Each has a textual hook in the SRS but no use case. Needed for the system to read as a platform rather than a coursework artifact. See [Platform completeness](#platform-completeness). |

## Public — `PublicLayout` (no session)

| Route | Purpose |
| --- | --- |
| `/register` | Register a tenant and its initial administrator in one step; the registrant becomes that administrator |
| `/login` | Authenticate a tenant user and resolve role, then route into the tenant shell |
| `/recover` | Step 1 of account recovery — submit account identifier, get the next action without confirming the account exists |
| `/recover/confirm` | Step 2 — submit recovery proof and new authentication material |
| `/invite/accept` **†** | Accept a tenant invitation and set authentication material; moves the user from `invited` to `active` |
| `/admin/login` **†** | Platform Administrator sign-in — a separate authentication realm from `/login` |

## Tenant — shared (`TenantLayout`)

| Route | Role | Purpose |
| --- | --- | --- |
| `/home` | TA · TD | Launcher listing only the services this role may enter, plus an integration-progress checklist — not a dashboard |
| `/credentials` | TA · TD | Create, rotate, revoke and scope API credentials; the secret appears once, in a modal |
| `/integration` **‡** | TA · TD | The API contract: endpoints, authentication, payload shapes, error codes, and this tenant's active credential scopes |
| `/account` **‡** | TA · TD | The signed-in user's own display name and authentication material |

## Tenant — Administrator only

| Route | Purpose |
| --- | --- |
| `/users` **†** | Tenant users with role, status and last sign-in; invite a new administrator or developer |
| `/users/:userId` **†** | One user's detail; change role, resend invitation, lock, unlock, disable or re-enable |
| `/training` | Training history plus current eligibility; start a job, subject to the one-active-job rule |
| `/training/:jobId` | Watch a job through its 12 states; cancel it; read the terminal result or failure reason |
| `/models` | All model versions with lifecycle state and the active indicator; consolidated model-status counts |
| `/models/:versionId` | Quality vs baseline and active version; activate, roll back, or archive |
| `/usage` | Measured usage against plan limits, remaining allowance, reset period, and trends |
| `/service-status` | Availability, active version, desired vs ready capacity, recent errors, fallback rate |
| `/audit` **‡** | This tenant's redacted action history — credential, training, activation, rollback and access events |

## Tenant — Developer only

| Route | Purpose |
| --- | --- |
| `/products` | List and filter the tenant catalog, with ineligible products visibly marked |
| `/products/new` | Add one product with a tenant-local identifier |
| `/products/sync` | Bulk-synchronize a bounded catalog and see accepted / updated / skipped / failed counts |
| `/products/:productId` | View and update one product; disable it with a reason |
| `/events/submit` | Submit a single customer interaction event or a bounded batch |
| `/submissions/:submissionId` | Track processing status, counts and safe errors for a product sync **or** an event batch |

## Platform Administrator — `PlatformLayout`

Each route is gated on its own named permission; the sidebar renders only permitted entries.

| Route | Permission | Purpose |
| --- | --- | --- |
| `/admin` | — | Redirect to the first route the holder's permissions allow |
| `/admin/tenants` | `platform permission` | All tenants with status and plan; change tenant status with a reason |
| `/admin/tenants/:tenantId` | *composes three* | One tenant's lifecycle, plan assignment and quota overrides, and usage — each section gated separately |
| `/admin/plans` | `plan-management permission` | Pricing plans and their event / recommendation / training limits |
| `/admin/plans/:planId` | `plan-management permission` | Edit one plan's limits and see its assigned tenants |
| `/admin/usage` | `authorized platform scope` | Cross-tenant usage by tenant, period and type — excluding private event payloads |
| `/admin/status` | `monitoring access` | Shared health, workload, capacity and failures, with measurement gaps shown as gaps |
| `/admin/audit` | `audit permission` | Two tabs: redacted failures, and the immutable audit history |

## Error & state routes

| Route | Gate | Purpose |
| --- | --- | --- |
| `/account/tenant-status` | 2 | Blocks a valid user whose tenant is pending, suspended, deleting or deleted |
| `/403` | 3 | Role or permission denied — terminal, offers no retry |
| `/404` | 4 | Resource missing **or** belonging to another tenant, deliberately indistinguishable |
| `/error` | — | Unhandled failure with a traceable reference and nothing leaked |

## Redirects

| From | To |
| --- | --- |
| `/` | `/home` · `/admin` · `/login` — by identity |
| `/admin` | First permitted platform route |
| `/products` (as TA) | `/403` — the catalog is Developer-only |

## Beyond the SRS

Four routes have no use case behind them. Without them the specified system cannot be operated at all: **14 of the SRS's own 29 routes are unreachable**, because no modelled path creates a Tenant Developer or authenticates a Platform Administrator.

### `/users` and `/users/:userId` — tenant user management

**Why it is missing.** NR-F-01 creates *"a tenant and initial administrator account"* — an administrator only. No use case, functional requirement or diagram models creating a second user.

**Why it is nonetheless required.** §2.1 makes "manages tenant users" an explicit Tenant Administrator responsibility. §3.5 has the Administrator "configure authorized users and assign suitable integration permissions" as step two of the project's own user story. §5.2.3 defines a Tenant User entity with a `role` enumeration containing `tenant developer` and a `status` enumeration containing `invited` — both meaningless without a provisioning flow.

**Without it:** `/products`, `/products/new`, `/products/sync`, `/products/:productId`, `/events/submit` and `/submissions/:submissionId` are permanently unreachable.

**Constraints carried over from §5.2.3:**
- `(tenant_id, email)` is a unique alternate key → duplicate email within a tenant is a conflict, not a validation error
- "A user cannot receive a role outside the permitted tenant role set" → the role selector offers exactly `tenant administrator` and `tenant developer`
- Status transitions cover `invited · active · locked · disabled`
- *Derived safety rule, not in the SRS:* the last active administrator cannot be demoted or disabled, or the tenant becomes unadministrable

### `/invite/accept` — invitation acceptance

**Why it is required.** A consequence of the above. `status: invited` can never become `active` without a public route where the invited person sets their own authentication material. Mirrors the `/recover/confirm` pattern: token in, credential set, redirect to `/login`.

### `/admin/login` — platform authentication

**Why it is missing.** UC-02 Sign In lists only Tenant Administrator and Tenant Developer as actors.

**Why it is nonetheless required.** UC-27 through UC-31 each presuppose a platform permission, and §5.2.16 models `platform_administrator` as an `actor_type` distinct from `tenant_user`. But §5.2.3 Tenant User is the ER model's only identity entity, and its `role` enumeration is closed to administrator and developer — so **the platform operator has no entity to exist as, and the five named permissions have nothing to attach to.**

**Without it:** all 8 `/admin/*` routes are permanently unreachable.

**Requires a backend decision:** a platform-identity entity holding the five permissions (`platform permission`, `plan-management permission`, `authorized platform scope`, `monitoring access`, `audit permission`). It must be a separate authentication realm from `/login` — a platform operator is not a tenant user and resolves no tenant scope.

### Raise these as SRS defects

All four are gaps in the specification rather than design choices. They are worth reporting as defects — an SRS that cannot provision two of its own three actors is incomplete, independent of any frontend.

## Platform completeness

Three optional routes and one component. Each has a textual hook in the SRS but no use case, so each is defensible without being load-bearing. Omit them and the system still satisfies the SRS; include them and it reads as a platform rather than a coursework artifact.

### `/integration` — the API contract

**Hook.** NR-NF-07: *"GraphRec shall support straightforward server-to-server integration using **documented** requests and responses."*

**Why it matters.** The entire product is an HTTP API consumed by the Tenant E-Commerce Application, yet nowhere in the console can a Tenant Developer find the contract. This is the most serious of the three.

**Contents.** Base URL and authentication scheme; endpoint reference for catalog sync, event submission (single and batch), submission result, recommendation request and feedback; request and response shapes; the error vocabulary (validation, conflict, limit, unavailable) with the traceable error reference from NR-NF-06; idempotency-key semantics per NR-NF-05; and **this tenant's own active credential prefixes with their granted scopes**, so the reader sees which operations their integration may actually perform.

**Not** a live playground — issuing real requests is tier 3 and unsupported by the SRS.

### `/account` — own profile

**Hook.** §5.2.3 stores `display_name` and `credential_digest` per Tenant User; §5.2.4 keeps `last_used_at`.

**Why it matters.** No use case lets a signed-in person change their own name or password. Without it, a user whose credentials are compromised has no self-service remedy — only `/recover`, which requires losing access first.

**Contents.** Display name; change authentication material (current + new); read-only role, tenant, account status and last-authenticated-at. Does **not** manage other users — that is `/users`.

### `/audit` — tenant-facing history

**Hook.** §5.2.16: audit records must not contain *"another tenant's information **in tenant-facing views**"*. Rule 12: *"**Tenant-facing audit queries** shall never reveal another Tenant's existence or data."* Both sentences presuppose that tenant-facing audit views exist; UC-31 nonetheless assigns audit review to the Platform Administrator alone.

**Why it matters.** ER-F-11 records credential changes, activation, rollback and quota changes. Those are the tenant's own actions, and the tenant cannot see them.

**Contents.** Tenant-scoped, read-only, redacted. Filter by action type and time. Columns: occurred-at, actor type, action type, resource, outcome. Never exposes credential secrets, raw event payloads, or any hint of another tenant.

### Onboarding checklist — a component, not a route

**Hook.** §3.5 Project User Story is a literal ordered sequence: register → configure users → create credential → synchronize catalog → submit events → request training → review quality → activate → serve → monitor.

**Implementation.** A dismissible progress checklist on `/home`, each step deep-linking to the route that performs it and reflecting real state (catalog non-empty, events received, a succeeded job exists, a version is active). Not a route, not a wizard — the steps are already routes.

### Left unresolved

**Customer data lifecycle.** §5.2.5 enumerates customer status as `active · anonymized · deleted` and notes that *"anonymization may preserve non-identifying aggregate behavior where permitted"* — but no use case exposes customers to any human actor, and §5.2.5 stresses that direct personal data is minimized. A `/customers` browser would contradict that minimization; a bulk anonymization action has no natural home. Flagged rather than designed. Decide with your supervisor whether the demonstration needs it.

## Deliberate omissions

- **No `/submissions` index.** UC-11 takes an identifier and defines no filter, unlike UC-13 and UC-16 which explicitly say "or filter". Reach a submission from the sync or batch result that produced it.
- **No routes for recommendations, feedback, or customers.** UC-21/22/23 belong to the Tenant E-Commerce Application, a machine actor; no use case exposes customer records to any human. The only trace in the UI is the fallback rate and recent errors on `/service-status`.
- **No tenant identifier in any tenant route path.** NR-NF-02 requires tenant identity to be derived from authenticated credentials; only `/admin/tenants/:tenantId` names a tenant, under platform scope.
- **No tenant settings editing.** §5.2.2 `settings` is "approved tenant-level configuration", implying platform control; no use case covers editing it. (Per-*user* profile is covered by `/account` ‡.)

- **Nothing from §1.3 Out of Scope.** The SRS explicitly excludes real payment processing, multi-region operation, unlimited tenant scaling, enterprise disaster recovery and HA, and arbitrary tenant-supplied model code — so there is no billing, no invoicing, no plan checkout and no region selector. CON-05 states the platform is *"a limited-capacity educational system, not a production-ready high-availability service."*

- **No commercial-PaaS conventions without an SRS hook.** Deliberately excluded as invention: webhooks, sandbox vs production environments, SDK downloads, a live API playground, per-request recommendation debugging, latency dashboards, alerting, MFA/SSO, active-session management, support desk, public status page, data export. Of these, **per-request debugging** is the one a production recommendation platform would miss most — the entities exist (`Recommendation Request`, `Recommendation Result`, `candidate_source`, `strategy`) but no use case surfaces them, so "why did this customer get these products?" has no answer in this console.
- **No tenant-side plan selection.** §2.1 has the Business Owner "select service plan", but Business Owner is a stakeholder, not an actor, and plan assignment is UC-28 (Platform Administrator). Plan appears read-only on `/usage`.
