# ADR 0031 — Gate 2 exempts exactly one read

**Status:** Accepted
**Phase:** 13
**Date:** 2026-08-24

## Context

Gate 2 refuses every tenant-realm request when the tenant is not operable, with
`403 auth/tenant_not_active`, and the console answers that refusal by sending
the reader to `/account/tenant-status`. FRONTEND_BUILD_PROMPT §7 says that page
"states the tenant's lifecycle position and that a Platform Administrator
controls the transition".

It cannot. The lifecycle position lives on the tenant row, the only endpoint
that returns it is `GET /v1/tenant`, and that endpoint was behind gate 2. A
member of a suspended tenant would be redirected to a page whose single query is
refused by the gate that redirected them — a loop with nothing readable in it.

The alternatives are all worse than they look. Putting the status in the sign-in
response makes it stale the moment the platform acts. Putting it in the JWT does
the same and adds a claim nobody may safely cache. Rendering the page from the
`403` body alone means the page can say "not active" and nothing else — not
which state, not why, and not the platform's own sentence about it.

## Decision

**`GET /v1/tenant` runs gate 1 and skips gate 2. Nothing else does.**

`docs/BUILD_PROMPT.md` L372 already anticipated this: *403 `tenant_not_active`
on everything **except** `/v1/auth/*` and `GET /v1/tenant`*. The implementation
makes the exemption a named dependency, `current_tenant_principal_any_state`,
rather than a flag on a shared one — so every route that takes it says so in its
signature and the exemption is greppable.

The width of the exemption is the decision, and it is narrow:

- **Gate 1 is unchanged.** No session, no answer. A token naming another tenant
  still resolves to nothing under RLS.
- **The disabled-account check is unchanged.** A locked user of a suspended
  tenant is refused, not shown a status page.
- **It is a read.** Nothing that writes may use it.
- **It returns the tenant's own row and no resource.** Products, credentials,
  jobs and users all stay behind gate 2, which is what suspending a tenant is
  *for*.

## Consequences

A suspended tenant's members can see their organisation's name, code, plan,
status and status reason. All five are facts about their own organisation that
they already knew or were told; none of them is another tenant's.

The exemption is pinned by a test that asserts **both halves**
(`tests/authz/test_gate_order.py`): `/v1/tenant` answers `200` for a suspended
tenant, and `/v1/me`, `/v1/products`, `/v1/api-keys`, `/v1/training-jobs` and
`/v1/usage` all still answer `403 tenant_not_active` for the same token. A
future route that quietly adopts the exempt dependency does not break that test,
which is why the second half enumerates paths rather than counting them — the
list is a floor, and widening the exemption means editing this ADR.
