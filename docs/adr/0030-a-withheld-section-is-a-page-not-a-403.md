# ADR 0030 — A permission a platform user lacks withholds a section, not the page

**Status:** Accepted
**Phase:** 12
**Date:** 2026-08-24

## Context

The platform realm authorizes per *permission*, not per role: `platform`,
`plan_management`, `platform_scope`, `monitoring`, `audit`. An operator may hold
any subset, and the tenant detail page (dc.html L1436) is composed of three
sections gated by three different permissions — status, plan, and usage.

The obvious implementation checks each permission and returns `403` when one is
missing. It produces a page that shows nothing at all to an operator who was
entitled to two of its three sections, and tells them they are not allowed to
look at this tenant, which is false.

The inverse — showing the section with empty data — is worse. A usage section
rendering zeros is indistinguishable from a tenant who has used nothing, and an
operator settling a billing dispute would act on it.

## Decision

**The route is gated once, on `platform`. Each section carries its own verdict.**

Every section is `{granted, data, reason}`. A held section has `granted: true`
and its data. A withheld section has `granted: false`, `data: null`, and a
sentence naming the permission it needs. The status code is `200` either way.

**The withheld sentence comes from the copy catalogue**
(`WITHHELD_SECTION_COPY`), not from the console and not composed at the point of
refusal. The console never writes its own explanation of an authorization
decision, for the same reason it never writes its own error copy.

**A withheld section costs no query.** The permission is checked before the
lookup, so the data is not fetched and then discarded — the section reveals
nothing and also does not pay for it.

**The reason names the permission, never the data.** "This section requires the
plan-management permission" is admissible; "this tenant is over its event limit
— sign in with plan-management to see by how much" would defeat the point of
having gated it.

**Composition applies to sections, not to routes.** An operator holding only
`audit` still receives `403` from the tenant detail route. A page of three
withheld sections would itself be a confirmation that the tenant exists, which
is gate 4's oracle wearing a different hat.

## Consequences

The response type is wider than the domain result: `Section[T]` is generic and
carries a `payload` property that raises rather than returning `None`, so a
router that reads a withheld section's data fails at the point of the mistake
instead of serialising a null into a field the console will render as a dash.

The console must render three independent states per section rather than one
page-level state. That is more front-end work than a `403` boundary, and it is
the work that makes a partially-permitted operator useful rather than blocked.

Adding a fourth section means adding a fourth permission entry to the copy
catalogue. The catalogue is keyed by permission, so the failure mode of
forgetting is a `KeyError` at construction rather than an empty tooltip in
production.

## Related

- ADR 0029 — the other half of Phase 12: what gets recorded when the answer is
  no.
- dc.html L1436; FRONTEND_BUILD_PROMPT §12.10; `graphrec/domain/platform/tenants.py`.
