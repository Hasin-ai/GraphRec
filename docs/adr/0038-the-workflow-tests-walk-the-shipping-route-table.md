# ADR 0038 — The workflow tests walk the shipping route table

**Status:** Accepted
**Phase:** 15
**Date:** 2026-08-24

## Context

§14 asks for one full workflow per role. Every other test in the console builds
the routes it needs — `renderGuarded` mounts one path behind one loader — which
is right for a test about one page, and blind to a whole category of mistake:

* a route registered under the wrong layout, so its gates never run;
* a loader given the wrong permission, so `/admin/audit` opens for an operator
  who holds `monitoring`;
* a mutation that never invalidates the list it changed;
* a redirect that points at a route which is not registered.

None of those fail a per-page test. All of them are exactly what a workflow
crossing three pages would hit.

`createRouter` returned a `createBrowserRouter`, which a test cannot drive: it
reads `window.history` and the tests need a memory router.

## Decision

**`router.tsx` exports `routeTable(queryClient)`, and `createRouter` is a
one-line wrapper around it.** The workflow tests import the same array the
browser is handed and mount it under `createMemoryRouter`.

**The fetch mock is a state machine, not a table of responses.** Half of what
these tests check is that the console re-reads after it writes; a mock that
returned the same list before and after a POST would make a missing
`invalidateQueries` look correct.

**An unexpected request throws** rather than falling back to a 200 or a 404. A
request the workflow did not intend is a page fetching something it should not,
and it should surface as a failure rather than as a silent success.

## Consequences

There is one route table. A workflow test that walked a second, test-only table
would be testing a console that does not ship, and the guards are *on* the
table.

`renderRoutes` takes an optional `QueryClient` so a test can pass the same
client the loaders were built with — otherwise a page re-fetches what its own
guard just cached, and the assertion about invalidation becomes ambiguous.

The three tests are slower than the per-page ones (roughly 1.3 s together) and
that is the correct trade. They are the only tests that would catch a route
registered in the wrong place.

`/` and `/admin` gained `element`s they will never render: both loaders always
redirect. React Router warns that a data route without an element renders a
null `<Outlet />`, and the warning is right — if either loader ever stops
redirecting, the result is a blank page, which is the failure mode nobody
reports. Each now renders a `LoadingAnnouncement` instead.
