# ADR 0045 — The deploy is ordered, and smoke-tested between nodes

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

Three nodes, one release. Deploying them in parallel is faster and is wrong in a
specific way: N1 runs the migrations, and N2's training worker and N3's
inference replicas both read the schema those migrations produce. Started
together, the workers connect to a database mid-migration, fail their first
query, and restart — `restart: always` turns that into a crash loop that clears
itself once N1 finishes, so the deploy "succeeds" after several minutes of
errors that look like a real fault.

The second question is what happens when a node comes up broken. Without a check
between steps, a bad image is rolled onto all three before anything notices, and
the rollback is three deploys rather than one.

## Decision

**Ordered, with a smoke test between each step, and the order is §9.1's:**

1. **N1 — control, migrations first.** The migration container runs to
   completion before anything reads the schema
   (`test_migrations_run_before_anything_reads_the_schema`). Smoke: the control
   API answers `/readyz`.
2. **N3 — serving.** Then a separate step tells the reconciler to roll the
   replicas, because N3's Compose file does not contain the inference
   containers: the reconciler owns those, one project per tenant, and a deploy
   that skipped this leaves the whole serving fleet on the previous image with
   nothing saying so (ADR 0046). Smoke: a recommendation is served.
3. **N2 — training.** Last, because it is the only node whose unavailability
   queues work rather than dropping it. Smoke: the worker claims a lease.

Each step is `needs:` the one before, so a failed smoke test stops the deploy
where it is rather than after it.

## Consequences

A deploy is as slow as the sum of three nodes plus three smoke tests, not as
slow as the slowest node. For an estate this size that is minutes, and it buys
the property that a broken release is discovered on one node instead of three.

**A stopped deploy leaves a split estate**, and that is the trade being made
explicitly. If N3's smoke fails, N1 is on the new release and N2 and N3 are on
the old one. This is survivable only because the plan requires migrations to be
one release backward-compatible — the new schema must serve the old code. That
requirement is a review discipline and nothing in CI checks it, which is
recorded as not met in `docs/PRODUCTION_READINESS.md`. It is the single
assumption this ordering rests on.

Rollback is re-running the workflow at an earlier tag, which repeats the same
order. It does *not* reverse migrations: a rollback that ran `alembic downgrade`
unattended would drop columns the previous release does not need and the next
one does. Reversing a migration is a runbook, done by a person, with the backup
in reach.
