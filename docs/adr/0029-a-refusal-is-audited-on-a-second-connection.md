# ADR 0029 — A refused action is audited on a second connection

**Status:** Accepted
**Phase:** 12
**Date:** 2026-08-24

## Context

ER-F-11 requires an audit row for each of eight actions, and an investigation
cares most about the attempts that were *refused*: the credential rotation by
someone who should not have had the console open, the fourth suspension attempt
against an account, the sign-in for an address that belongs to no tenant.

A success is straightforward. The row belongs in the transaction that performed
the thing being recorded, so that "the action happened" and "the audit row
exists" are one fact rather than two facts that usually agree.

A refusal is not, and the obstacle is mechanical rather than philosophical. A
refusal raises a `GraphRecError`; the raise unwinds the request's
`session.begin()`; and the rollback takes every statement in that transaction
with it — including the row explaining why the request was refused. Writing a
refusal into the transaction that is about to roll back produces no row at all.

Three ways out were available.

1. **Catch, write, re-raise inside the same transaction.** Does not work: the
   transaction is already doomed, and in the database-error case PostgreSQL has
   already aborted it and will refuse the `INSERT` outright.
2. **Buffer refusals in memory and flush them after the response.** Keeps one
   connection per request, and loses every buffered row if the process dies —
   which is disproportionately likely to be exactly when the interesting
   refusals happened.
3. **Write the refusal on a second connection, in its own short transaction,
   committed immediately.**

## Decision

**Refusals are written on a second connection** (`AuditTrail.refused`), and
successes stay in the request's transaction (`AuditTrail.action`).

**An audit write never converts a refusal into a fault.** `refused` swallows its
own exceptions after logging them. If the audit table is unreachable, the tenant
still receives their 409 with the approved copy. What they must never receive is
a 500 produced by the machinery that was supposed to be watching.

**The machine code goes into `details`, never the resolved copy.** The copy is
product wording that changes; the code is the stable thing a support query
filters on, and it is already what the response carries.

## Consequences

**A refusal row can outlive the request that produced it.** If a handler refuses
one thing and then fails for an unrelated reason, the refusal is still recorded.
A history that occasionally records an attempt that was refused twice, once
spuriously, is strictly better than one that silently drops refusals.

**A denied request costs a connection from the pool.** That is the cheap
direction: refusals are rare relative to successes, and the alternative is a
security-relevant blind spot on every denied request. It does mean a burst of
refusals — a credential-stuffing attempt, say — costs pool capacity at the
moment the installation is under stress. If that becomes real, the fix is a
small dedicated pool for the audit writer, not a return to in-transaction
writes.

**Ordering between a refusal and neighbouring successes is not guaranteed.** The
refusal commits before the request finishes; a success in the same request
commits after. Both carry `occurred_at`, and the audit page orders by it, so
the visible ordering is by time rather than by commit. Nothing reads the audit
table for causality.

**The second connection is bound to the tenant before it writes.** Otherwise RLS
would refuse the insert, or — worse, if the policy had been written with `IS NOT
DISTINCT FROM` — accept it unattributed. A refusal for an unknown tenant is
written with `tenant_id IS NULL` deliberately, which makes it visible to the
platform audit page and invisible to every tenant's own.

## Related

- ADR 0020 — the counter moves inside the creating transaction, for the opposite
  reason: a usage counter that survives a rollback overcharges someone.
- `graphrec/domain/audit/trail.py`; ER-F-11; SRS §5.2.16.
