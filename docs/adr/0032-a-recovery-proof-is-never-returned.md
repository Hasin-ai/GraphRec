# ADR 0032 — A recovery proof is never returned in a response

**Status:** Accepted
**Phase:** 13
**Date:** 2026-08-24

## Context

Phase 13's public routes include `/recover` and `/recover/confirm`, and neither
had a backend. Building the console screens against nothing would have produced
two forms that cannot work, so the endpoints were built:
`POST /v1/auth/recovery` and `POST /v1/auth/recovery:confirm`, against the
already-existing and until-now-unused `recovery_tokens` table.

The project has no mail transport, and the ADR index has carried "SMTP, or an
administrator CLI that prints the recovery link?" as an open question since
Phase 3. `docs/BUILD_PROMPT.md` L90 answers it: an administrator CLI.

That leaves one genuinely tempting shortcut. Invitation tokens *are* returned in
the response body — `POST /v1/invitations` hands the token to the administrator
who created the invitation, who then passes it on. Doing the same for recovery
would make the console flow trivial to build and to demonstrate.

## Decision

**The recovery endpoint returns one fixed sentence and never the proof.**

The asymmetry with invitations is the point, and it is not about the token: it
is about who is asking.

- An invitation is requested by an **authenticated administrator who chose the
  recipient**. Handing them the token gives them something they already had the
  authority to create.
- A recovery is requested by an **anonymous stranger who typed an address**.
  Handing them the token *is* the account takeover.

So:

1. `POST /v1/auth/recovery` answers `202` with the same `detail` for a real
   account, a fictional one, a locked one, and an unknown organisation code.
   Nothing in the body, the status or the headers varies.
2. **Neither path writes an audit row.** A row written only on the real path is
   the same disclosure moved to a place the reader cannot see but an operator
   can.
3. Delivery goes to `scripts/recovery_token.py` (the sanctioned CLI) or, absent
   that, to a deliberately alarming `WARNING` from `graphrec.common.delivery`
   that names itself as unfit for anything real.
4. The proof is stored as a digest, exactly as credentials are. The table holds
   nothing that can be presented.
5. `POST /v1/auth/recovery:confirm` compares the password confirmation **before**
   it resolves the token, so a typo cannot consume a single-use proof — and the
   console therefore does not duplicate that comparison client-side.
6. A successful recovery **revokes every refresh session** for the account. A
   password change that leaves the thief's session running is not a recovery.

Timing is deliberately not equalised. Doing it properly means constant-time work
on both paths including the argon2 verification, and doing it badly is worse
than not doing it; the answer is rate limiting at the edge, and it is written
down rather than implied.

## Consequences

**Platform operators have no self-service recovery.** A platform user's rows
carry `tenant_id IS NULL`, and the `tenant_lookup.resolve_recovery_token`
resolver returns a tenant id — so the resolver cannot see them and the endpoint
cannot serve them. Their recovery is another operator with database access. This
is a real gap, recorded here rather than discovered later.

The console's `/recover` screen renders the server's `detail` and nothing
conditional, and a test compares the rendering for a real address against the
rendering for an invented one **character for character**. Any future branch on
whether the account exists shows up there as a diff.
