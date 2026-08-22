# ADR 0007 — Invitations: a stored digest, a derived seven-day life, one-time return

**Status:** Accepted, with one part flagged as interim
**Phase:** 2
**Date:** 2026-08-22

## Context

The prototype specifies the invitation flow precisely enough to build from: an
administrator invites by email, display name and role (dc.html L1232); the
invited person appears immediately with status `invited` (L1236); they visit
`/invite/accept`, supply an `inv_…` token and set their own authentication
material, "which moves them from invited to active" (L1230, L1043).

What it does not specify is how long an invitation lives, or how the token
reaches the invitee. The SRS is silent too — its only mention of invitation is
the user status vocabulary.

## Decision

**The token is stored as a SHA-256 digest, never in the clear.** A dump of
`invitations` does not let the reader accept anybody's invitation. The token
itself never reaches the database at all: `tenant_lookup.resolve_invitation`
takes the *digest*, so the secret does not appear as a query parameter, in
`pg_stat_statements`, or in a slow-query log.

**Seven days, as a setting.** `invitation_ttl_seconds` defaults to `604_800`. It
is a derived number with no source in either authority. It is a setting rather
than a literal because it is the kind of bound an operator will want to shorten,
and because BUILD_PROMPT §13.22 requires user-facing bounds to be named.

**The role comes from the invitation row, never from the accepting request.**
`AcceptInvitationRequest` carries a token, a password and a confirmation, and
`extra="forbid"` makes anything else a 422. An invitee cannot promote themselves.

**Every refusal is `invitation_invalid`, at 401.** Expired, revoked, already
accepted, unknown, and "the account was locked before it was activated" all
answer identically, because the prototype promises rejection "without disclosing
account details" (L1046). A distinct "already accepted" would disclose that the
account exists and is live.

**The confirmation is compared before anything else.** A mismatch that only the
browser catches is a mismatch a direct API call does not catch at all, and the
account would activate with a password its owner mistyped. Comparing it first
also means a typo does not consume the invitation — the invitee has no way to
mint another one.

## The interim part

`POST /v1/users` returns `invitation_token` in its response body.

Phase 2 has no mail transport, and the console cannot deliver a token it never
sees. Returning it once, to the administrator who minted it, is the honest
interim: it is shown exactly once, it is not retrievable afterwards, and
`test_listing_users_never_exposes_an_invitation_token` pins that it appears
nowhere else.

**This must stop as soon as invitations are delivered out of band.** Email
delivery is one of the four open questions in `docs/adr/README.md` with no
proposed answer. Until it is answered, an administrator can activate an account
they invited, which is a lower bar than the flow intends.

## Consequences

- `invitations` has no `DELETE` grant for any role. An invitation is revoked
  (`revoked_at`), not removed, so "the earlier link stops working" (L1247) is a
  state transition with an audit trail.
- Accepting issues no session. The prototype's form reads "Set and return to
  sign in", and signing in afterwards proves the password just set is the
  password the invitee meant.
- `resend invitation` (L1247) is specified by the prototype and is **not built**.
  It needs the delivery question answered first.
