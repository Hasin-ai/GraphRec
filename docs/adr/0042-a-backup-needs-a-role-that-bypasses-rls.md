# ADR 0042 — A backup needs a role that bypasses RLS, and says so rather than working around it

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

Every tenant table is `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL
SECURITY`. `FORCE` is what makes the owner subject to the policies too — without
it, `graphrec_owner` reads every tenant's rows and the isolation guarantee has a
hole in it exactly the shape of the role that runs migrations.

`pg_dump` connects as somebody. As `graphrec_owner`, with no
`app.current_tenant_id` set, every tenant table matches no policy row. Depending
on the table and the policy, that is either an error or — much worse — a
successful dump containing zero rows.

There were three ways to make the backup script work:

1. `ALTER TABLE … NO FORCE` around the dump. Works, and turns the isolation
   boundary off for the duration of a scheduled unattended job, on the primary,
   with no guarantee the `FORCE` comes back if the script dies in between.
2. Set `app.current_tenant_id` and dump per tenant. Produces N dumps that cannot
   be restored as one consistent snapshot, and misses every table with no
   `tenant_id`.
3. Require a role that bypasses RLS.

## Decision

**Option 3, required rather than detected.** `scripts/ops/pg_env.sh` exposes
`require_rls_bypass`, and `backup.sh`, `restore.sh` and `restore_drill.sh` all
call it before doing anything. It checks `rolsuper OR rolbypassrls` on the
connected role and exits with the reason if neither holds.
`GRAPHREC_SUPERUSER_DATABASE_URL` is a separate variable from the owner URL, so
the elevated credential is named as such rather than smuggled in.

The refusal is treated as the design working.
`docs/RUNBOOKS.md#restore-from-backup` says so in as many words, and adds: *"Do
not answer it with `ALTER TABLE … NO FORCE`."*

## Consequences

The backup job holds the most powerful credential on the node. That is not a
downgrade — a process that can read every tenant's data is what a backup is —
but it means the timer unit and its environment are as sensitive as the database
itself.

On a managed Postgres where no role has `BYPASSRLS` and no role is superuser,
the scripts refuse and the operator has to use the provider's own snapshot
mechanism. Saying that out loud beats a script that appears to work and writes a
dump with no rows in it — a failure that surfaces at restore time, which is the
one time nobody has spare capacity to debug it.

The same requirement lands on the *verification* side, and that is where it
earns its place: the drill counts rows on both databases, and a drill running as
a role that reads zero rows on each side would compare equal and print PASSED. A
verification step that cannot fail is worse than none.
