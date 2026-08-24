# Routes

Every address the console answers, and what has to be true to see it.

The table is the map; `src/router.tsx` is the territory. Where the two disagree
the router is right, and this file is a bug.

## The gates

Five, run in the order the backend runs them (`apps/control_api/deps.py`). The
order is the security property, not a style choice.

| # | Gate | Where it lives in the console | Refusal |
|---|------|-------------------------------|---------|
| 1 | **Identity** — is there a session for this realm | `requireTenantSession` / `requirePlatformSession`, in the layout loader | `/login`, or `/admin/login`, carrying `?next=` |
| 2 | **Tenant state** — is the tenant `active` | `tenantGuard`, in `TenantLayout`'s loader | `/account/tenant-status` |
| 3 | **Role or permission** — may this account be here at all | `requireRoleLoader` / `platformGuard(…, permission)`, per route | `/403` |
| 4 | **Ownership** — is this resource ours | `rethrowAsRouteError`, on a 404 from the API | `/404`, naming nothing |
| 5 | **Resource state** — may this action be taken *now* | **not a guard.** A disabled control and the server's reason, in place | nothing; it never navigates |

Gate 5 is deliberately not a route guard. Whether a resource is in a state that
permits an action is answered by the server in the resource's own `actions` and
`can_*` fields, and navigating away from a page because one button on it is
unavailable is the behaviour §13 forbids.

Gates 1–3 are guards, not the authorization. The server re-decides every one of
them against the token; a caller who edits the bundle to skip them gains a
different error message and nothing else. What they buy is that the console does
not render a page it is about to be refused, and — §13, explicitly — that a
route is guarded by a **route guard** rather than by a hidden button.

## Public — no session (4 shells: `PublicLayout`)

Gate 1 does not apply; these are the pages a visitor with no session needs.

| Route | Purpose | Notes |
|-------|---------|-------|
| `/register` | Register an organisation | Creates the tenant and its first administrator |
| `/login` | Tenant sign-in | Honours `?next=`; stores the tenant realm session |
| `/recover` | Request recovery | Answers a real account and an invented one identically |
| `/recover/confirm` | Complete recovery | Refuses without saying which half of the proof was wrong |
| `/invite/accept` | Accept an invitation | The same form as recovery confirmation, different endpoint |
| `/admin/login` | Platform sign-in | A separate realm gets a separate sign-in |

## Error pages — `PublicLayout`, standalone

Addressable, because somebody will link to one or type it. Each is *also* what
`RouteErrorBoundary` renders inside whichever layout was active, so an error
inside the tenant shell keeps the shell (§5).

| Route | Meaning |
|-------|---------|
| `/403` | Refused, and no retry will change it |
| `/404` | Nothing here — or nothing here *for you*, told identically |
| `/error` | Something failed; carries a correlation reference when one exists |

## Gate 2 landing — `StateGateLayout`

| Route | Gates | Notes |
|-------|-------|-------|
| `/account/tenant-status` | 1 only | Exempt from gate 2 by design — it is where gate 2 sends you. Redirects to `/home` if the tenant became active while the page was open |

## Tenant realm — `TenantLayout`

Gates 1 and 2 run once on the shell, before any child loader. Gate 3 is the
`Role` column. **No tenant identifier appears in any of these paths** (§13): the
tenant comes from the session, and a path segment naming it would be
attacker-controlled input a handler is tempted to trust.

| Route | Role | Gates | Notes |
|-------|------|-------|-------|
| `/home` | both | 1, 2 | Onboarding checklist and launcher |
| `/credentials` | both | 1, 2 | The one-time secret is a **modal**, never a route |
| `/integration` | both | 1, 2 | Must match the published OpenAPI |
| `/account` | both | 1, 2 | Own display name and password |
| `/users` | administrator | 1, 2, 3 | Invitation token shown once, in a dialog |
| `/users/:userId` | administrator | 1, 2, 3, 4 | Foreign id → `/404` |
| `/audit` | administrator | 1, 2, 3 | Redacted: no free-form detail column |
| `/training` | administrator | 1, 2, 3 | Start is gate 5: disabled with the server's reason |
| `/training/:jobId` | administrator | 1, 2, 3, 4 | Polls every 2 s, stops at a terminal state |
| `/models` | administrator | 1, 2, 3 | |
| `/models/:versionId` | administrator | 1, 2, 3, 4 | Activation and rollback are gate 5 |
| `/usage` | administrator | 1, 2, 3 | An unmeasured quantity is an em dash and a reason, never a zero |
| `/service-status` | administrator | 1, 2, 3 | Polls every 15 s and **never stops** |
| `/products` | developer | 1, 2, 3 | §4 gives the administrator no catalogue access at all |
| `/products/new` | developer | 1, 2, 3 | |
| `/products/sync` | developer | 1, 2, 3 | Bulk upsert; answers with a submission |
| `/products/:productId` | developer | 1, 2, 3, 4 | Addressed by the tenant's own external id |
| `/events/submit` | developer | 1, 2, 3 | |
| `/submissions/:submissionId` | developer | 1, 2, 3, 4 | Polls every 2 s, stops when terminal |

The administrator having no catalogue access is intentional and comes from the
use-case diagrams. A developer route is **not** "administrator plus developer"
and must not be widened into one.

## Platform realm — `PlatformLayout`

Gate 1 runs on the shell. Gate 2 does not apply — an operator has no tenant.
Gate 3 is per route, because §8's five permissions are granted independently: an
operator may hold `audit` and nothing else.

| Route | Permission | Gates | Notes |
|-------|-----------|-------|-------|
| `/admin` | — | 1 | Redirect to the first route this operator's permissions open. `/403` if none do |
| `/admin/tenants` | `platform` | 1, 3 | |
| `/admin/tenants/:tenantId` | `platform` | 1, 3, 4 | **The only path in the console that names a tenant.** Composes three permissions — see below |
| `/admin/plans` | `plan_management` | 1, 3 | |
| `/admin/plans/:planId` | `plan_management` | 1, 3, 4 | |
| `/admin/usage` | `platform_scope` | 1, 3 | |
| `/admin/status` | `monitoring` | 1, 3 | Polls every 15 s and never stops |
| `/admin/audit` | `audit` | 1, 3 | The estate's history, with a tenant column |

### The composed tenant detail

`/admin/tenants/:tenantId` is gated on `platform` **alone**, and this is
deliberate. The page shows three sections — status, plan, usage — whose
permissions are `platform`, `plan_management` and `platform_scope`. The server
returns all three regardless, each carrying `granted` and, when it is false, a
`reason`; the withheld ones render their heading and the server's sentence.

Gating the whole route on all three would turn away an operator who holds
`platform` and not `plan_management` from a tenant they are entitled to see.
A whole-route 403 here would be the wrong answer to the right question.

## The redirects

| From | To | Decided by |
|------|----|-----------|
| `/` | `/home`, `/admin`, or `/login` | Which realm holds a session. The tenant realm wins a tie — both at once is a developer's machine, and the tenant console is the one they meant |
| `/admin` | the first permitted `/admin/*` route | The operator's held permissions |
| `*` | `/404` | Nothing — a path that resolves to nothing is indistinguishable from one that resolves to something foreign, which is the point (§13) |

## Counts

6 public + 3 error + 1 gate-2 landing + 19 tenant + 7 platform = **36 addressable
routes**, plus 3 redirects and 4 layout shells.
