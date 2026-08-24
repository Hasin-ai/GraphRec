# ADR 0036 — A superseded invitation is revoked, never deleted

**Status:** Accepted
**Phase:** 14
**Date:** 2026-08-24

## Context

`POST /v1/users/{id}:resend-invitation` cannot resend anything: the first token
was never stored, only its digest, for the same reason a credential secret is
shown once. So "resend" is necessarily "issue a fresh one", and the old
invitation has to stop working in the same transaction — an administrator who
resends believes the previous link is dead, and a link that still opens the
account is one sitting in whichever chat log the first attempt was pasted into.

The implementation written in Phase 12 did this with `DELETE FROM invitations`.
It had never been executed: the runtime role holds `SELECT, INSERT, UPDATE` on
that table and no `DELETE` (migration 0002), so every call returned a 500 with
`permission denied for table invitations` underneath it. The first test to call
the endpoint found it immediately.

That left two ways forward — grant `DELETE`, or stop deleting.

## Decision

**Stop deleting. The superseded row is marked `revoked_at` instead.**

The grant is correct as written and the code was wrong. An invitation row is the
record that somebody was invited, by whom, on a particular day; an administrator
investigating how an account came to exist needs the superseded attempts as much
as the one that worked. Deleting them erases the part of the story that explains
why there were three.

`Invitation.is_open()` already treats a revoked row as closed, so the old token
stops working in the same statement that records why — no second mechanism, and
nothing for the accept path to learn.

**The runtime role keeps no `DELETE` on `invitations`.** A grant added to make
one call site work would also be available to the next one.

## Consequences

Resending twice leaves two revoked rows and one open one, which is the honest
representation of what happened.

The table grows by one row per resend and is never swept. At the rate a human
administrator presses a button this is not a retention problem; if it ever
becomes one it belongs in the same retention sweep as the audit trail, which is
already a recorded gap.

Pinned by a test that reissues, then presents the *first* token to
`POST /v1/invitations:accept` and asserts `invitation_invalid`, then accepts on
the second and asserts the account went active. Both halves matter: an
implementation that revoked nothing passes the second assertion alone.
