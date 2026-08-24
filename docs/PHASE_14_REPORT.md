# Phase 14 — Console: the tenant realm

**Scope (BUILD_PROMPT L679-681):** `/home` (from `GET /v1/onboarding`) ·
`/credentials` with the one-time secret modal · `/integration` · `/account` ·
`/users*` · `/products*` · `/events/submit` · `/submissions/:id` with live
polling · `/training*` with the nine-stage rail · `/models*` with the three-way
comparison · `/usage` · `/service-status` · `/audit`.

**Done when:** all 30 tenant routes render real data and every gate-5 control is
disabled from the server's `actions`/`can_*` fields with the server's reason.

**Gate:** 🛑 *"CONFIRM the design system (§10.7) before starting."* Asked at the
top of Phase 13 and again here; unanswered. §10.7 states what to do while the
question is open — build on tokens, use the Modernist palette so screenshots
stay comparable — so the phase proceeded on that standing instruction. Recorded
as **ADR 0034**, explicitly as a decision taken by instruction rather than by
preference, and marked provisional so that an answer supersedes it rather than
amends it.

## 1. Built

Nineteen route components, ~5,500 lines of new frontend, 25 new tests (18
route/behaviour, 4 design-system lint, 3 polling), and 24 new backend tests that
found six defects in code written in Phases 12 and 13.

### The nineteen routes

Registered in `src/router.tsx` under the tenant shell, each behind a
`requireRoleLoader` carrying §4's role table. The asymmetry in that table is
deliberate and easy to mistake for an oversight: **the Tenant Administrator has
no catalogue access at all.** `/products*`, `/events/submit` and
`/submissions/*` are Developer-only; `/users*`, `/audit`, `/training*`,
`/models*`, `/usage` and `/service-status` are Administrator-only; only
`/home`, `/credentials`, `/integration` and `/account` are shared. A developer
route is therefore *not* "administrator plus developer", and the router says so
in a comment so the next person to widen one has to argue with it first.

* **`/home`** — the §5c checklist from `GET /v1/onboarding`, then the launcher
  filtered by the same `tenantNav` table the sidebar reads, so the two cannot
  disagree. A step the caller's role cannot perform is still drawn, as plain
  text with "A Tenant Administrator does this one" — hiding it would leave a
  developer looking at a complete list and an integration that returns nothing.

* **`/credentials`** — the list plus three dialogs. The one-time secret lives in
  a `useState` in the component and nowhere else: not in the query cache, which
  is keyed, shared and survives navigation, and never in a route, because a
  route holding a secret is a URL holding a secret. `dismissible={false}` on
  that one dialog only — every other dialog closes on Escape, and this is the
  only one whose contents cannot be recovered.

* **`/integration`** — a static endpoint reference (six endpoints, request and
  response snippets, an error-class table) beside a live credential/scope table
  built from `visible_prefix`. Deliberately not a playground: a page that fires
  real writes at a real catalogue to demonstrate a request is a page that
  demonstrates it once and explains it forever.

* **`/account`** — display name, and a password form that sends
  `keep_session: readRefreshToken('tenant')`. The server keeps the session that
  can *prove* it is this one rather than trusting a claim that it is.

* **`/users`, `/users/:userId`** — filters are client-side, with a comment
  saying why (`GET /v1/users` is unpaginated because a tenant's user count is
  bounded by how many people work there). The invitation dialog renders the
  one-time token as a full link and states plainly that nothing was emailed.
  `is_last_active_administrator` drives both `GatedAction`s on the detail page.

* **`/products`, `/products/new`, `/products/sync`, `/products/:productId`** —
  eligibility is a badge from `row.eligible` and "why not" is
  `row.ineligibility ?? row.exclusion_reason ?? '—'`, verbatim, never
  reconstructed. Price is sent as a string: going through a JavaScript number to
  get there is how a price becomes `19.989999999999998`. `/products/new` and
  `/products/sync` are registered before `/products/:productId` so neither is
  read as an identifier.

* **`/events/submit`** — two tabs. The single-event form carries a regenerable
  `event_id` so `duplicate_confirmed` can be demonstrated rather than described;
  the batch form parses its JSON locally first, because a JSON error is the
  reader's typo and does not need a round trip to say so.

* **`/submissions/:submissionId`** — 2 s polling that stops at a terminal
  status, one `aria-live="polite"` line, five counts, and the rejected-items
  table beside the sentence that the rest of the batch was applied.

* **`/training`, `/training/:jobId`** — four eligibility cards (data, quota,
  concurrency, cooldown) and one control taking its enablement and its sentence
  from `eligibility`. The detail page's rail is `job.stages` from the server,
  not a local constant, so a pipeline that grows a stage does not need a console
  release.

* **`/models`, `/models/:versionId`** — the three-way comparison, with
  `serving` and `status === 'active'` as separate columns and a comment on why
  they are not the same fact. A null measure renders `—` and never `0.000`.

* **`/usage`** — a figure appears only when `measurement_status === 'measured'`;
  otherwise an em dash and the status label. A stale number presented as current
  is worse than no number.

* **`/service-status`** — four 15 s live queries that never stop, led by the
  `serving_previous` warning banner.

* **`/audit`** — five columns, and the actor's *type* rather than their name:
  the fact a tenant needs and the most a tenant is owed.

### Supporting changes

* **`StageRail` generalised** with `stages` and `label` props rather than a
  second rail component for submissions. Two rails would have meant two sets of
  state classes to keep in step.
* **`GatedAction` gained `busy`**, separate from `allowed`, so a slow request
  does not read as a refusal — a disabled-because-busy button has no reason to
  give, and `reason` stays the server's.
* **`requireRoleLoader`** in `src/guards` — gate 3 as a per-route loader.
  Loaders run in parallel, so there is no ancestor data to read; the fetch is
  free because `tenantGuard` has already cached `me`.
* **`src/test/tenant.tsx`** — `respondWith(table)` matches by URL prefix rather
  than chaining `mockResolvedValueOnce`, because these pages issue several
  parallel queries whose order React Query does not promise.
  `renderGuarded` mounts `RouteErrorBoundary` as the route's `errorElement`, so
  a gate-3 refusal renders the real 403 page instead of a bare thrown `Response`.
* **`GET /v1/onboarding`** and the console-only `/me` endpoints gained their
  first tests (24 of them, `tests/authz/test_console_surface.py`), each against
  a private tenant from the new `fresh_tenant` fixture — these are the mutating
  paths, and running them against the shared `realm` would change what later
  tests sign in with.

## 2. Verified

* **Five gates green.** `ruff format --check` (279 files), `ruff check`, `mypy`
  (160 files), `lint-imports` (3 contracts kept), `pytest` — **1126 passed**, up
  from 1102.
* **Frontend: 96 tests in 15 files**, `tsc --noEmit` clean under `strict` plus
  `noUncheckedIndexedAccess`.
* **The two completion criteria have tests, not assurances.**
  * Gate 5 comes from the server: the revoked credential's Rotate button is
    disabled and carries `blocked_reason`; the last active administrator's two
    controls are disabled with the server's sentence, reached through
    `aria-describedby`; rollback is disabled while activate stays enabled on the
    same page, from `actions.*`.
  * Roles are route guards, not hidden buttons: a developer at `/users` and an
    administrator at `/products` each get the 403 page, and `fetch` is asserted
    to have been called with exactly `['/v1/me']` — the refusal happens before a
    single tenant-scoped query is issued.
* **Foreign resources 404 and say nothing.** A foreign product and a foreign
  user each render `heading "Not found"`, and the identifier that was asked for
  is asserted absent from the DOM — a 404 page that quotes the id back is a
  disclosure wearing the right status code.
* **Polling stops.** The submission page is advanced 10 s past a terminal status
  under fake timers and asserted to have issued no further request. A page that
  keeps asking about a finished submission costs a request every two seconds for
  as long as the tab stays open, and the tab that stays open is the one somebody
  left on a second monitor.
* **The one-file design-system promise is now enforced** rather than asserted:
  `src/styles/tokens.test.ts` reads the stylesheets and every `.ts`/`.tsx` file
  and fails on a hex, `rgb()`, `hsl()`, `oklch()` or `color-mix()` outside
  `tokens.css`; it fails on a `var(--x)` with no `--x:`; and it checks that both
  themes are defined over the same vocabulary. The lint was verified by breaking
  it on purpose and watching it fail.

## 3. Decisions and deviations

**ADR 0034 — the console stays on the Modernist tokens.** Recorded above.

**ADR 0035 — gate 4 is thrown from render.** `QueryState` rethrows `ApiError`
403 and 404, which React Router catches exactly as it catches a loader throw, so
every detail route inherits the `/404` answer from the component it already uses
for loading and empty states. Only those two statuses: a 500 or a timeout still
renders in place, because a detail page whose side panel fails should degrade to
a page with a broken panel, not to an error page that loses the part which
worked.

**ADR 0036 — a superseded invitation is revoked, never deleted.** The runtime
role holds no `DELETE` on `invitations` and that is correct; the row is the
record that somebody was invited, and an administrator investigating how an
account came to exist needs the superseded attempts as much as the one that
worked.

**Deviation: the design-system lint was vacuous when first written.** It used
`import.meta.glob(..., { query: '?raw' })`, which returns an **empty string for
every `.css` file** — Vite resolves a stylesheet through its CSS pipeline before
the raw query is honoured. Two of the four assertions were passing over no input
at all. It now reads the bytes with `node:fs` (which is why `@types/node` is a
new dev dependency), and two of the assertions guard their own input size, so
the same mistake fails loudly rather than silently. This was caught during the
phase and is recorded because a lint that reports success while checking nothing
is the worst possible artefact to leave behind.

**Deviation: `/v1/me`'s blank-name refusal comes from Pydantic, not the
service.** `_Body` strips whitespace and the field is `min_length=1`, so `"   "`
never reaches `update_own_profile`. Its own `display_name_required` check stays
as the second line of the same defence for a direct caller of the service; the
test pins that the 422 *names the field*, because an unnamed 422 leaves the
console with nothing to put under the input.

## 4. Bugs this phase found in code written earlier

Seven, of which four were unreachable-until-called backend defects that no
existing test had ever exercised.

1. **Nobody could change their own password.** `change_own_password` called
   `verify_password(current_password, user.credential_digest)`; the signature is
   `verify_password(digest, password)`. The arguments were reversed, so the
   correct current password was always rejected and the endpoint could only ever
   fail. Written in Phase 13, shipped with no test. Fixed, and the call now
   passes `password=` by keyword so the ordering cannot silently reverse again.

2. **Every resend-invitation returned a 500.** `reissue_invitation` issued
   `DELETE FROM invitations`, and the runtime role holds `SELECT, INSERT,
   UPDATE` on that table and no `DELETE` (migration 0002). The grant was right
   and the code was wrong — see ADR 0036. Now marks `revoked_at`, which
   `Invitation.is_open()` already treats as closed.

3. **Two error codes had no approved copy**, so both paths raised
   `MissingErrorCopy` and answered 500 instead of the status they intended:
   `current_password_invalid` (should be 422) and `user_not_invited` (409).
   Added to `ERROR_COPY`, both marked `(derived)` — the prototype renders no
   message for either path.

4. **`keep_session` could never hold a refresh token.** The field was bounded at
   `max_length=512` while `RefreshRequest.refresh_token` — the same value — is
   bounded at 4096. Any real token was refused as too long, so the "keep the tab
   you are typing in" behaviour was unreachable and the caller was signed out of
   the session they were using. Corrected to 4096 with a comment naming the
   invitation-token bound it was copied from.

5. **`--space-5` was referenced and never defined.** `layout.css` used it for
   `.page`, `.topbar`, `.card`, `.standalone` and the gate shell. An unresolvable
   `var()` invalidates the whole declaration at computed-value time, so the main
   content padding of every page in the console was silently not applied. Found
   by the new token lint on its first honest run — which is exactly the failure
   the lint's own comment predicts: not a colour, a spacing step, and a layout
   that looks merely cramped so nobody files it.

6. **Invalid DOM in every table's loading state.** `QueryState` rendered
   `TableSkeleton` — a bare `<tbody>` — directly inside a `<div>`. No browser
   parses that as written and a screen reader has no row semantics for it. Now
   wrapped in `<table className="table" aria-hidden="true">`.

7. **A foreign resource rendered an inline banner instead of `/404`.**
   `QueryState` swallowed every query failure by design, which is right for a
   panel and wrong for a detail page: it produced a third answer, distinguishable
   from both 403 and 404, in violation of §13. Fixed per ADR 0035.

## 5. Not done

* **The two deferred tenant-layout badges** (active model, service state) are
  still deferred. They need a cheap summary read that does not fire on every
  navigation.
* **`ROUTES.md`** (§14 deliverable) is not written; it lands with Phase 15,
  when the remaining eight routes exist and the table would otherwise have to be
  written twice.
* **No a11y pass yet.** Focus order, dialog focus trapping and visible focus are
  implemented per §13 and spot-checked in tests, but the systematic pass is
  Phase 15's scope.
* **`/integration` is a reference, not a playground**, by choice. It shows what
  a request looks like; it does not send one.
* **Carried forward, unchanged:** the 15-minute training cooldown is
  provisional; no retention sweep for orphaned artifacts; training concurrency
  is per tenant rather than platform-wide; the metric floor is not
  tenant-configurable; the training worker takes the in-memory counter default;
  the reconciler is serial and scheduled by nothing; `serving_replicas` rows are
  not swept; audit has no retention or partitioning; `security_events` has no
  alerting; platform operators have no self-service recovery; recovery timing is
  not equalised.
* **Invitation rows now accumulate**, one per resend, and are never swept. At
  the rate a human presses a button this is not a retention problem; if it
  becomes one it belongs in the same sweep as the audit trail.
