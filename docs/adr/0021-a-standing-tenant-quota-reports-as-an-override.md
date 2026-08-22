# ADR 0021 — A standing tenant quota reports on the wire as an override

**Status:** Accepted
**Phase:** 7
**Gate:** none.

## Context

Three tables can set a limit — `quota_overrides`, `tenant_resource_quotas` and
`pricing_plans` — and they resolve in that order. BACKEND_PLAN L1195 gives the
wire field two values: `plan` and `override`.

## Decision

`tenant_resource_quotas` reports as `override`. There is no third value.

## Consequences

* From the tenant's side the two are the same fact: a limit that is not the one
  their plan states. The distinction between "a platform administrator granted
  this in response to a request" and "this tenant has a standing figure for the
  period" is real in our schema and has no meaning on their usage page.
* Adding a third value would ask the console to render a word for it, which
  means writing copy the prototype does not have, for a distinction the tenant
  cannot act on differently.
* The cost: a support conversation that needs to know *which* mechanism set a
  tenant's limit cannot learn it from the API. That is a platform-console
  question, and the platform console reads the tables directly.
* `quotas.py` records the reasoning where the branch is, so the next reader does
  not restore the third value as a bug fix.
