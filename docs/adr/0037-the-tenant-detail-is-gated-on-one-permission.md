# ADR 0037 — `/admin/tenants/:tenantId` is gated on one permission, not three

**Status:** Accepted
**Phase:** 15
**Date:** 2026-08-24

## Context

Every other platform route maps to exactly one of §8's five permissions, and
its loader checks that one. `/admin/tenants/:tenantId` does not fit: the page
shows three sections whose permissions differ — status needs `platform`, plan
needs `plan_management`, usage needs `platform_scope` — and the five are
granted independently, so an operator holding `platform` and nothing else is a
normal account rather than a misconfiguration.

Three gatings were available:

1. Require all three. Simple, and wrong: it turns away an operator who is
   entitled to see the tenant because they are not entitled to see its price.
2. Require none, and let the sections speak. Also wrong: an operator with only
   `audit` would reach a page addressed by tenant id and get three refusals,
   having already confirmed the id names a real tenant.
3. Require the one that governs the *page* — the tenant record itself.

## Decision

**The route's loader requires `platform`, and only `platform`.** The plan and
usage sections are gated by the server, per section, and return `200` with
`granted: false` and a `reason` rather than failing the request.

The console renders a withheld section as its heading and the server's
sentence. It composes no explanation of its own — a section that says "you do
not have permission" in the console's words is the console guessing at a rule
it does not own, and the guess is wrong the moment the rule changes.

This is ADR 0030's decision (`a withheld section is a page, not a 403`) applied
to the one route where three permissions meet. That ADR settled the response
shape on the server; this one settles which permission the *route* is gated on,
which the server could not decide because the server has no routes.

## Consequences

An operator holding `platform` alone gets the tenant list, every tenant's page,
and its status controls — including suspension, which is the most consequential
thing on the page. That is the intent: `platform` is the tenant-administration
permission, and the sections it does not open are commercial and measurement
data rather than administrative controls.

The workflow test for the platform role runs with exactly this grant. It
asserts both halves: the suspension goes through, and the plan section renders
the server's reason instead of 403ing the page out from under an operator who
belongs there.

If a fourth section is ever added, the question is not "does this need its own
route gate" but "which permission does the server put on the section". The
route gate stays `platform` as long as the page is addressed by a tenant id and
`platform` is what entitles an operator to know that tenant exists.
