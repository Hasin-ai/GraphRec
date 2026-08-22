# ADR 0010 — Rotation grace is opt-in, and defaults to none

**Status:** Accepted.
**Phase:** 3
**Date:** 2026-08-22

## Context

Two of the governing authorities ask for different things, and both are right
about their own realm.

The console prototype, which BUILD_PROMPT calls an executable specification,
states plainly in its rotate dialog (`GraphRec Console.dc.html` L1145):

> Rotation issues a new secret and invalidates the current one. Requests still
> using the old secret will fail authentication.

BUILD_PROMPT's Phase 3 exit criterion says the opposite:

> **Done when:** the secret is returned exactly once, a rotated key's
> predecessor still verifies during grace, and cross-tenant access is blocked.

and `.env` already carries `MAX_API_KEY_GRACE_SECONDS=86400`, so a grace window
was anticipated by the configuration as well.

The conflict is real but narrow. The prototype is describing what a person
clicking that button gets. BUILD_PROMPT is describing what a fleet of servers
mid-deploy needs, which is a window in which both secrets work while instances
roll. A credential rotated from the console has one holder who is standing right
there; a credential rotated by an integrator's pipeline may have forty.

## Decision

**`grace_seconds` defaults to `0` and is opt-in.** `RotateCredentialRequest`
declares it with a default of zero, so a console rotation — which sends no such
field, because the dialog has no such control — invalidates the predecessor
immediately and makes L1145 literally true rather than approximately true.

**A caller who asks for a window gets one, capped at
`MAX_API_KEY_GRACE_SECONDS`.** Out-of-range values are refused rather than
clamped: silently shortening a window an integrator asked for would cut them off
mid-deploy at a moment they did not choose, which is the exact failure the
window exists to prevent.

**The window is carried in four `previous_*` columns that move together.** The
prefix, the digest, the hash version and the expiry, under
`ck_api_keys_previous_is_all_or_nothing`. A partially-populated predecessor
would be a credential that could be looked up but not verified, or verified
against a digest with no expiry — which is a permanent second live secret.

**A rotation with no grace clears them explicitly.** Not left over from a
previous rotation. Two rotations inside one open window must leave one live
secret, not three; `test_a_second_rotation_does_not_extend_the_first_window`
pins it.

**Revocation clears them too.** A revoked credential that still authenticated
through its grace window would contradict the console's own promise that
revocation is immediate (L1157).

**The grace secret carries the credential's current scopes, not the ones it had
when it was minted.** Otherwise removing a scope during rotation would not take
effect until a window the *caller* chose had closed.

**Success on a grace secret is reported as such.** `VerifiedCredential` carries
`used_grace_secret`, so the response can carry a deprecation signal and the
audit trail can record it. A silent success tells an integrator nothing until
the window shuts, at which point the information arrives as an outage.

## Consequences

- One credential can have two live secrets for a bounded, caller-chosen,
  server-capped period. That is a deliberate widening of the authentication
  surface, and it is why the window is bounded, explicit, cleared on revoke, and
  visible in the response rather than implicit.
- `visible_prefix` and `previous_visible_prefix` are each globally unique, and
  the resolver matches either. A prefix therefore resolves to exactly one
  tenant for as long as it resolves to anything at all.
- The console needs no new control, and its existing copy needs no rewrite. That
  matters under BUILD_PROMPT's rule that prototype strings are requirements: the
  alternative resolution — a grace window on by default — would have made L1145
  false and required editing the specification to match the implementation.
- `grace_expires_at` is surfaced on the credential view while a window is open,
  so the console can show that one is running even though it cannot start one.

## Alternatives rejected

**Grace on by default.** Matches BUILD_PROMPT's phrasing most directly, and is
what most credential systems do. Rejected because it would make the prototype's
copy wrong for every console user in order to serve the API caller, and because
a security-relevant widening that nobody asked for is the wrong default.

**No grace at all.** Matches the prototype exactly and is the smaller surface.
Rejected because it fails a named Phase 3 exit criterion, and because the
alternative it forces on an integrator — rotate, then race to redeploy — is how
credentials end up never being rotated.

**Rotation as a new row rather than in place.** Would give grace for free: the
old credential simply expires on its own schedule. Rejected because the console
rotates the row the dialog was opened on and expects the credential to keep its
identity, its name and its place in the list (L1150). A rotation that produced a
second row would double the list every time anyone rotated anything.
