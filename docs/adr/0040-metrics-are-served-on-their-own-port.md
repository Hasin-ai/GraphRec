# ADR 0040 — Metrics are served on their own port, not on the API

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

§24 asks for six named alerts. None of them can fire without an exposition
endpoint, and the endpoint has to be reachable by Prometheus on N1 and by
nothing else.

The default answer is `GET /metrics` on the API, and it has one real advantage:
it needs no second listener, no second port and no second firewall rule. It also
puts the exposition on the public surface, where its protection becomes a route
that somebody must remember to guard — in a codebase whose whole authorization
story is five ordered gates, adding a route that deliberately sits outside them
is a special case, and special cases are what get forgotten during a refactor.

The exposition is not innocuous. `graphrec_serving_replicas` is labelled by
`tenant_id`, so an unguarded `/metrics` is a list of every tenant on the
platform and how large each one is.

## Decision

**A separate listener, `METRICS_PORT=9464`, started by
`graphrec/observability/exposition.py` and bound to the node's WireGuard address
in every Compose file.** Prometheus scrapes it across the tunnel. There is no
route on 443 that reaches it, so there is nothing on the public surface to
protect and nothing to forget.

`METRICS_ENABLED=false` exists for tests, where every app built by a fixture
would otherwise try to bind the same port.

The server is a module-level singleton: one metrics listener per process is true
by definition, and threading a handle through five entrypoints would buy
nothing. A second call is a no-op rather than a port conflict.

## Consequences

Five entrypoints each start it, which is five call sites rather than one piece
of middleware. That is the cost of the workers having no HTTP server at all —
the job worker, the training worker and the reconciler are not FastAPI
applications, and a metrics endpoint mounted on an app they do not have is not
an option.

The listener is a plain `prometheus_client` thread, not an ASGI app, so it has
none of the request logging, request ids or error envelope the rest of the
platform has. It is the right trade for an endpoint whose only client is a
scraper, and it means a fault in it looks like a scrape timeout rather than a
log line — which is what `TargetDown` is for.

`METRICS_ENABLED=false` is a way to run the platform blind. It is documented in
`.env.example` as being for tests, and nothing stops a deployment from setting
it. There is no alert for "the alert pipeline is switched off"; `TargetDown`
fires on a target that is scraped and failing, not on a target that never
appeared.
