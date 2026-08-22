# ADR 0006 — Registration mints the tenant id, binds the context, then inserts

**Status:** Accepted
**Phase:** 2
**Date:** 2026-08-22

## Context

`tenants` carries `ENABLE` + `FORCE ROW LEVEL SECURITY` with a policy keyed on
`current_setting('app.tenant_id', true)`. That gives default-deny: with no
context bound, `tenant_id = NULL` evaluates to `NULL`, which is not `TRUE`, so
nothing is visible and nothing may be written.

Registration has to create the very first row for a tenant that does not exist
yet, so there is no context to bind — and `FORCE` means the migration owner is
subject to the policies too, so "run it as the owner" is not an escape either.
This surfaced first in a test fixture, which is the cheapest possible place for
it to surface.

The tempting answers were all worse:

- Grant the owner a blanket `USING (true)` policy. This is the one that must
  never happen: it re-establishes a role that reads every tenant, which is the
  exact condition `FORCE` exists to remove.
- `ALTER TABLE tenants NO FORCE` for the duration of registration. A window in
  which the policy is off, on the request path, under concurrency.
- Register through a `SECURITY DEFINER` function. A write path running as a role
  no policy constrains, reachable from an unauthenticated endpoint.

## Decision

Registration mints the `tenant_id` in application code, binds `app.tenant_id` to
that value with `SET LOCAL`, and *then* inserts. `WITH CHECK` passes for exactly
that row and for no other, because the row's `tenant_id` and the bound context
are the same value by construction.

`graphrec_app` therefore holds `SELECT, INSERT, UPDATE` on `tenants` — and no
`DELETE`, because SRS §5.2.2 makes tenant removal a lifecycle transition rather
than a row disappearing.

The `INSERT` grant is only safe because of `WITH CHECK`, so the property is
pinned by a test that fails if the clause is removed:
`test_registration_cannot_mint_a_tenant_it_is_not_bound_to` binds one identifier
and attempts to insert a row carrying a different one. Removing `WITH CHECK`
from `tenants_self_isolation` was verified to make that test fail.

## Consequences

- No role in the system reads across tenants except `graphrec_platform`, which
  is what the platform realm is for.
- Test fixtures cannot seed two tenants in one transaction, because a
  transaction is bound to one tenant. They seed one at a time, through the
  runtime path. This is the constraint working, not an awkwardness to route
  around, and the fixture proves on the way past that a tenant can be created
  under RLS at all.
- Test *teardown* is the one legitimate escape hatch: `_force_lifted` lifts
  `FORCE`, deletes, and restores it in a single transaction. It lives in a
  `finally` in a fixture and nowhere else. Migration `0002` documents the same
  procedure for data migrations, which are the other case that needs it.
