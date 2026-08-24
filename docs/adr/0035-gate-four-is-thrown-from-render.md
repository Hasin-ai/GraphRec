# ADR 0035 — Gate 4 is thrown from render, not banner-ed in place

**Status:** Accepted
**Phase:** 14
**Date:** 2026-08-24

## Context

`docs/BUILD_PROMPT.md` §13 is a hard constraint: a foreign resource must answer
`/404`, never `/403`, so that a caller cannot use the difference between the two
to learn that an identifier names something real in somebody else's tenant.

The backend already does this — `GET /v1/users/{id}` runs no `tenant_id`
predicate, so another tenant's user simply returns no row and becomes the same
404 an invented UUID gets. The console then has to preserve the property.

Gates 1–3 are route loaders, so their refusals already reach the route's
`errorElement` and render as pages. Gate 4 is different: whether a resource
exists is only known once its query resolves, and by then the route has
rendered. `QueryState` — the component wrapping every query in the console —
was catching *every* failure and rendering an inline banner. On a detail page
that meant a foreign product rendered a page frame with "could not load" inside
it, which is a third answer distinguishable from both 403 and 404.

## Decision

**`QueryState` rethrows `ApiError` 403 and 404 from render.** React Router
catches a throw from render exactly as it catches a throw from a loader, so the
same `RouteErrorBoundary` that renders gate 1–3 refusals renders this one, and
the result is the real `/404` page inside the tenant shell.

**Only 403 and 404.** Every other failure — a 500, a timeout, a network drop —
still renders in place. A detail page whose side panel fails should degrade to a
page with a broken panel, not to an error page that loses the part which
worked. The narrowness is the design: wide enough that gate 4 works, narrow
enough that a transient failure does not evacuate the page.

**The error is rethrown as it arrived**, not repackaged into a `Response`.
`RouteErrorBoundary` reads `ApiError` directly; a `Response` is what a loader
throws and is not what the boundary recognises outside one.

## Consequences

A detail route needs no gate-4 code of its own. `/products/:productId`,
`/users/:userId`, `/models/:versionId`, `/training/:jobId` and
`/submissions/:submissionId` all inherit the behaviour from the component they
already use to render loading and empty states.

Two tests pin it, one per realm of the mistake: a foreign product and a foreign
user each assert `heading "Not found"` **and** that the identifier they asked
for is absent from the DOM — because a 404 page that quotes the id back is a
disclosure wearing the right status code.

A component that renders a query outside `QueryState` does not get this, and
would have to throw for itself. Nothing in the console currently does.
