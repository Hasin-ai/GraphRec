# Phase 15 — Console: the platform realm

**Scope (BUILD_PROMPT L683-684):** All 8 `/admin/*` routes including the
composed tenant detail · sidebar filtered by held permissions · `/admin` → first
permitted route · the three per-role workflow tests · full a11y pass.

**Done when (L685):** all 36 routes are backed by real endpoints and the three
workflow tests pass against a live stack.

**Gate:** §10.7's design-system question remains unanswered. It was asked at the
top of Phase 13, again at Phase 14, and is asked again here. §10.7 states what to
do while it is open — build on custom properties, stay on the Modernist tokens
so screenshots remain comparable — so the phase proceeded on that standing
instruction. **ADR 0034** records it as provisional; nothing in this phase makes
answering it harder, because no route introduced a colour. `styles/tokens.test.ts`
enforces that, and it now has company: `a11y.test.tsx` checks the same
stylesheets for a focus ring.

## 1. Built

Seven route components (~1,520 lines), one platform API module, 16 new tests
across two files, and `ROUTES.md`. Two defects in Phase 14 code were found and
fixed on the way.

### The seven routes

Registered in `src/router.tsx` under `PlatformLayout`, each behind
`platformGuard(queryClient, request, permission)` with the one permission §8
grants it.

| Route | Permission | What it does |
|-------|-----------|--------------|
| `/admin/tenants` | `platform` | The estate: search, status filter, paged |
| `/admin/tenants/:tenantId` | `platform` | Three composed sections, three dialogs |
| `/admin/plans` | `plan_management` | The price list, and a create dialog |
| `/admin/plans/:planId` | `plan_management` | One plan, its limits, its tenants |
| `/admin/usage` | `platform_scope` | Every tenant's aggregates |
| `/admin/status` | `monitoring` | The live board, composed from two endpoints |
| `/admin/audit` | `audit` | The estate's history, with a tenant column |

`/admin` itself is a redirect to the first route the operator's permissions
open, and `/403` if none do. That and the permission-filtered sidebar were built
in Phase 13 and are covered by the nine tests in `layouts/nav.test.ts`; this
phase gave them somewhere to point.

**36 routes now resolve to a component backed by a real endpoint**: 6 public + 3
error + 1 gate-2 landing + 19 tenant + 7 platform. `ROUTES.md` is the map, with
each route's realm, role or permission, and the gates that run on it.

### The composed tenant detail

The page §8 spends the most words on, and the one most easily built wrong. It is
gated on `platform` **alone**. Its plan and usage sections are gated by the
server, per section, and come back `200` with `granted: false` and a `reason`
when they are withheld; the console renders the heading and the server's
sentence beneath it.

Gating the route on all three permissions would turn away an operator who holds
`platform` and not `plan_management` from a tenant they are entitled to see —
a whole-route 403 as the answer to a question about one section. Recorded as
**ADR 0037**, which is ADR 0030's rule applied to the one route where three
permissions meet.

The three dialogs on it are the consequential ones:

* **Change status** — requires a reason of at least four characters, because
  the status, the actor and the time are all mechanical and the reason is the
  only part a person writes. `deleting` is offered and labelled as
  irreversible.
* **Assign plan** — closed plans are filtered out of the picker, since a closed
  plan accepts no new assignments and offering one would produce a refusal the
  console could have predicted.
* **Grant exception** — the limit input accepts zero, and says so in its hint.
  A zero override is a legitimate instrument (stop this tenant's ingestion
  without suspending them), and a form that treated it as an empty field would
  make the instrument unreachable.

### The status board

`/admin/status` composes `/v1/platform/status` and `/v1/platform/failures` as
two queries rather than one. The failure list is filtered and the board is not;
refetching the board every time somebody narrows to `severity=critical` would
make the numbers above the filter flicker for no reason.

Two nullable fields are rendered as the distinction they encode rather than as
zero. `replicas.ready` being null means the orchestrator did not answer, which
is not the same as no ready replicas — only one of those two is an outage.
`serving_availability` being null means it was not measured in the window. Both
render an em dash and a sentence.

`measurement_gaps` renders the server's `reason` verbatim. UC-30's alternative
outcome is that a gap is *identified* rather than hidden, and a console that
wrote its own explanation would be hiding it behind a nicer one.

### The three workflow tests

`src/routes/workflows.test.tsx`, one per role, each walking several pages:

1. **Tenant Administrator** — `/home`, into `/users` via the sidebar, invite a
   colleague, the one-time invitation link appears in a modal and not in the
   address, close it, and the list has re-read itself with the new row marked
   `invited`.
2. **Tenant Developer** — `/products`, into `/products/new`, create a product,
   land on that product's own page. Asserts the path names the product and
   never the tenant.
3. **Platform operator** — `/admin`, redirected to `/admin/tenants` because
   `platform` is the only permission held, into the tenant, the withheld plan
   section states the server's reason, suspend with a reason, the badge reads
   `suspended`.

They import `routeTable` — the same array `createRouter` hands the browser —
rather than assembling routes of their own, because the entire category of bug
they exist to catch lives *in* the table: a route under the wrong layout, a
loader given the wrong permission, a mutation that never invalidates. Recorded
as **ADR 0038**.

The fetch mock is a small state machine rather than a fixed table, so that "the
list re-read itself after the write" is a real assertion; and an unexpected
request throws rather than falling back to a 200.

### The accessibility pass

`src/a11y.test.tsx`, 13 tests in three groups, and the split is the point —
recorded as **ADR 0039**.

1. **axe over a page from each of the four shells**, plus one with a dialog
   open, run against the real route table. `color-contrast` is disabled with the
   reason at the call site: jsdom applies no CSS, so the rule can only report
   *incomplete*, and a suite that left it on would show a green tick over a
   check that never ran.
2. **The focus trap, driven by keyboard.** Focus enters on open, Tab and
   Shift+Tab stay inside, Escape returns focus to the opener. The Tab test
   rounds the ring twice: a trap that only wraps the last element passes one
   pass and leaks on the second.
3. **The stylesheets as text** — `:focus-visible` exists, and no rule removes an
   outline without putting a `box-shadow` or another outline back.

`axe-core@4.13.0` is a new dev dependency.

## 2. Verified

**All five backend gates green, unchanged by this phase:**

```
ruff format --check .   279 files already formatted
ruff check .            All checks passed!
mypy graphrec apps      Success: no issues found in 160 source files
lint-imports            Contracts: 3 kept, 0 broken
pytest -q               1126 passed in 129.89s
```

**Frontend:** `tsc --noEmit` clean; `vitest run` — **17 files, 112 tests passed**
(96 before this phase, +16).

**Both new lints were verified by being broken.** A lint that reports success
while checking nothing is the worst artefact to leave behind, and this phase
produced one twice before catching it:

* `axe.run` was probed with an unlabelled input, an image with no `alt` and an
  empty button; it reported `label`, `image-alt`, `button-name`. It bites.
* The focus-ring lint was written twice wrong. The first version's `\s*` before
  a negative lookahead backtracked to zero width and matched the space in
  `outline: none`. The second read the selector's own colon — `:focus` — as a
  declaration separator. **Both passed over a deliberately planted
  `.negative-control:focus { outline: none; }` in `layout.css`.** The third is a
  function with its own test over five literals, two that must be flagged and
  three that must not, and it fails on the same planted violation.

**The workflow tests were run against the real route table**, not a test-only
one, which is the closest this phase gets to L685's "live stack": the loaders,
guards, layouts, redirects and query invalidations are all the shipping ones.
The HTTP boundary is mocked. See §5.

## 3. Decisions and deviations

**ADR 0037 — `/admin/tenants/:tenantId` is gated on one permission, not three.**
The route requires `platform`; sections are withheld in place with the server's
reason.

**ADR 0038 — the workflow tests walk the shipping route table.** `routeTable` is
now exported and `createRouter` wraps it. `renderRoutes` takes an optional
`QueryClient` so a test can pass the one the loaders were built with.

**ADR 0039 — the accessibility pass is three checks.** Because axe cannot see
focus behaviour and cannot see colour in jsdom.

**Deviation: `/` and `/admin` gained elements they will never render.** Both
loaders always redirect, and React Router warns that a data route without an
element renders a null `<Outlet />`. The warning is right — if either loader
ever stops redirecting the result is a blank page, the one failure mode nobody
reports — so each now renders a `LoadingAnnouncement`.

**Deviation: `formatBytes` uses binary steps with decimal names** (1024-based,
labelled `GB`). That is the convention the storage industry lost and everyone
else kept, and a reader comparing a plan's storage limit against their object
store's own figure wants the two to agree.

**`/admin/usage` builds its period filter from the periods present in the
answer** rather than from a fixed list, so the filter can never name a period
with nothing behind it.

## 4. Bugs this phase found in code written earlier

**1. `Pagination` counts from one; two pages counted from zero.** The primitive
computes `first = (page - 1) * pageSize + 1` and disables *Previous* at
`page <= 1`. `/products` and `/audit` both held `useState(0)` and passed it
straight in. On first load the label read **"Showing -24–0 of N"**, and
clicking *Next* moved to offset 25 — so the first page's rows were shown under
a label describing a page that does not exist, and page 1 of the label was
actually page 2 of the data. Fixed in both by counting from a named
`FIRST_PAGE = 1` and subtracting once, where the two conventions meet.

**2. `--space-5` was referenced and never defined.** Carried from the Phase 14
report as fixed there, and worth repeating here because the same class of defect
is what the new focus-ring lint guards: an unresolvable `var()` invalidates the
whole declaration silently.

Neither had a failing test before this phase, and the first would not have been
found by one: every per-page test asserts on rows, and the rows were right.

## 5. Not done

**L685 says "against a live stack" and the workflow tests mock the HTTP
boundary.** Everything above that boundary is real — the route table, the
loaders, the guards, the redirects, the query client and its invalidations — and
the response shapes come from the generated OpenAPI types, so a shape that
drifts breaks the build. What is not proven is that the running backend returns
those shapes at those paths for those permissions. That is an end-to-end
concern, it needs the stack up and seeded, and it belongs with Phase 16's smoke
tests where a live stack already has to exist.

**Contrast between the two themes is unproven by machine.** `tokens.test.ts`
proves both themes define the same vocabulary and override the nine tokens that
cannot be derived; it does not prove the resulting pairs meet WCAG. That needs a
real browser, and Phase 16 is where one appears.

**No test drives the platform realm's own recovery**, because there is none —
carried from Phase 13 as open question 7. A platform operator who loses their
password still needs another operator with database access.

**`/admin/usage` is not paginated.** The endpoint reports `total`, `limit` and
`offset`, and the page renders `Showing n of total` without controls to move.
For an estate of a few hundred tenants the first page is the answer; past that
it is a gap, and the primitive to close it already exists.

**Carried from Phase 14, unchanged:** the two deferred tenant-layout badges
(active model, service state); the 15-minute training cooldown is provisional;
no retention sweep for orphaned artifacts; training concurrency is per tenant
rather than platform-wide; the metric floor is not tenant-configurable; the
training worker takes the in-memory counter default; the reconciler is serial and
scheduled by nothing; `serving_replicas` rows are not swept; no audit retention
or partitioning; `security_events` has no alerting; recovery timing is not
equalised; invitation rows accumulate one per resend and are never swept.
