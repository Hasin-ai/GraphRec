# ADR 0011 — PostgreSQL is the broker, and a claim is a `SECURITY DEFINER` function

**Status:** Accepted — confirmed by instruction to proceed
**Phase:** 4
**Date:** 2026-08-22

## Context

D2 asks whether background work runs on a message broker — RabbitMQ with Celery
behind a transactional outbox — or on the database that already holds the work.

Everything the platform enqueues is created by a transaction that also writes
rows: a bulk upsert writes a submission, a training run writes a model version.
With a broker, those two writes are in different systems, and the gap between
them is a bug that only appears under failure: the transaction commits and the
publish fails, so a submission exists that nothing will ever process; or the
publish succeeds and the transaction rolls back, so a worker is handed a job
whose subject was never created. The standard repair is a transactional outbox —
a table, plus a relay process that reads it and publishes. Which is to say: a
job table plus a poller, and then RabbitMQ *as well*.

The load makes the choice easier rather than harder. ASM-03 puts the platform at
tens of jobs a day, not thousands a second. `FOR UPDATE SKIP LOCKED` is not a
compromise at that volume; it is comfortably the right tool, and it stops being
one somewhere around four orders of magnitude further on.

The real design problem is not the broker. It is that **a worker cannot bind
`app.tenant_id` before it claims, because which tenant it is working for is the
answer the claim produces.** Every other read in the system happens after a
verified credential names a tenant. This one happens before, and it must scan
every tenant's rows to do its job.

## Decision

**PostgreSQL is the broker.** A `jobs` table; a claim by `FOR UPDATE SKIP
LOCKED`; enqueue in the same transaction as the work that caused it, so the two
cannot disagree.

**The claim is one `SECURITY DEFINER` function, `job_queue.claim`,** owned by
`graphrec_queue`: `NOLOGIN`, `NOINHERIT`, not superuser, no `BYPASSRLS`. This is
the ADR 0008 pattern applied to a fourth hole, and it is the widest of the four,
so the boundaries are drawn tighter:

- **Column-level grants only.** `SELECT` on nine scheduling columns and `UPDATE`
  on five lease columns. `payload` is in neither. A scheduler orders and times
  work; it has no use for the tenant's data, and a role that reads every row in
  the table must not be able to read the column where that data lives.
- **The function returns two identifiers.** `claimed_job_id` and
  `claimed_tenant_id`, and nothing else. The worker then opens a *tenant-bound*
  session and loads the job through the tenant's own policy, exactly as a
  request handler would. So the widened read cannot become a widened disclosure:
  the only thing that crosses the boundary is the answer to "whose turn is it".
- **No tenant argument.** The scheduler does not take instructions about whose
  work to prefer from whoever called it.
- **`SELECT` and `UPDATE` policies only,** and no `DELETE` grant to anyone. A
  job is the record of what a tenant asked for and what happened to it.

**Fair share is least-in-flight-first.** Rank each tenant's *live* jobs — queued
and running, running ranked first — and take the lowest-ranked queued row in the
system. Priority orders a tenant's own work and never jumps another tenant's
queue, so one tenant's ten-thousand-row backlog cannot starve another tenant's
single job.

**Leases, not acknowledgements.** A claim stamps `lease_owner` and
`lease_expires_at`; a heartbeat on a separate connection renews it; a sweeper in
*every* worker requeues what has lapsed. No leader election, because the sweep is
idempotent under contention and a designated sweeper is a single point whose
death leaves expired leases unswept.

**Cancellation is cooperative,** observed only at a `JobContext.stage()`
boundary the handler nominates. Nothing interrupts a handler mid-write.

## Consequences

The queue is visible to `psql`, backed up with the database, and restored
consistently with the rows it refers to. Enqueue-and-work is one transaction and
the outbox problem does not arise. One fewer service to run, secure and monitor.

Against that: the claim polls rather than listens, so a job waits up to
`job_poll_interval_seconds` (2s) when the queue was empty. At tens of jobs a day
that latency is invisible, and it removes a `LISTEN`/`NOTIFY` dependency with its
own reconnection handling. The claim also runs on the primary, which is the same
database serving requests — at this volume that is a rounding error, and if it
ever stops being one the fix is a replica for reads, not a broker.

The pattern does not scale to thousands of jobs a second. If it ever needs to,
`JobQueue` is the seam: `enqueue`/`claim`/`heartbeat`/`fail` is a small enough
interface to reimplement, and the handler contract does not mention PostgreSQL.

## Two things the tests found, recorded because they will be rediscovered

**A predicate in a subquery is not re-checked.** When a locked row is released by
a committing holder, PostgreSQL's EvalPlanQual re-reads the new version and
re-checks only the *locking query's own level* qualification. A `status =
'queued'` test that lives only in a subquery is evaluated once, against a stale
snapshot, and the row is claimed twice — which is precisely the failure
`SKIP LOCKED` exists to prevent, defeated by where the predicate was written. The
claim therefore repeats `status` and `run_after` in the outer `WHERE` and guards
the final `UPDATE` as well.

**Ranking only queued rows starves the wrong tenant.** A claimed job vacates its
rank, so the backlogged tenant is promoted back to rank 1 every round and takes
every slot. Ranking over live jobs — queued *and* running — is what makes it fair.
Both failures are quiet: the queue drains, nobody errors, and the only symptom
is a tenant whose job takes an hour.

## Related

- ADR 0008 — the resolver pattern this extends, and the reasoning about
  `SECURITY DEFINER` ownership under `FORCE ROW LEVEL SECURITY`.
- Migration `0006_jobs.py`; `tests/isolation/test_queue_role.py` pins the size of
  the hole.
