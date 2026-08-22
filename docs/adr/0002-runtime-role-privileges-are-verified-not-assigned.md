# ADR 0002 — The runtime role's dangerous attributes are verified, not assigned

**Status:** Accepted
**Phase:** 1
**Date:** 2026-08-22

## Context

Migration `0001` provisions `graphrec_app`, the role every process connects as at
runtime. The isolation model requires it to be a non-owner, non-superuser without
`BYPASSRLS`: those attributes defeat every row-level-security policy the schema
will ever define, `FORCE ROW LEVEL SECURITY` included.

They defeat them *silently*. There is no error, no log line and no failing query.
A cross-tenant test suite run against a `BYPASSRLS` role passes completely and
proves nothing at all.

The obvious implementation is to assert the attributes:

```sql
ALTER ROLE graphrec_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
```

Verifying this against a real PostgreSQL 18 showed that it cannot work.
PostgreSQL only permits a role to change an attribute it holds itself:

- `NOSUPERUSER` and `NOBYPASSRLS` require the caller to be a superuser.
- `NOCREATEDB` requires the caller to hold `CREATEDB`.

The migration owner is deliberately none of those things, so the statement fails
with `InsufficientPrivilege` on any correctly configured deployment. It happens to
succeed when migrations are run as a superuser — which is precisely the
configuration the design is trying to avoid.

## Decision

Set only what a `CREATEROLE` owner is always permitted to set, and **verify** the
rest:

- On create: `CREATE ROLE ... LOGIN NOINHERIT NOCREATEDB NOCREATEROLE`.
- On an existing role: `ALTER ROLE ... LOGIN NOINHERIT` only.
- Then query `pg_roles` for `rolsuper`, `rolbypassrls`, `rolcreaterole` and
  `rolcreatedb`, and raise if any is held. The message names the offending
  attributes and the exact `ALTER ROLE` a superuser should run.

Failing the migration is the correct outcome. A deployment whose runtime role can
read every tenant's rows must not reach the point of serving traffic.

The same property is asserted twice more: as a CI step in the `migrations` job,
and as `tests/isolation/test_runtime_role_privileges.py` in the required merge
gate. Three checks for one property is not redundancy — it is the property that
everything else assumes, and it is invisible when broken.

## Consequences

- The migration owner must hold `CREATEROLE`. This is documented in the README and
  produces an actionable error, not a permission-denied traceback, when absent.
- A pre-existing over-privileged role is a hard failure rather than a silent
  downgrade. Operators must fix it out of band. That is the intended friction.
- Migration `0001` cannot use `DO $$ ... $$` for its conditional role creation: a
  `DO` body is an opaque string to the server, so a bind parameter inside it has
  no resolvable type and psycopg fails with `IndeterminateDatatype`. Interpolating
  the password into that string instead would place a secret one quote away from
  SQL injection. The existence check is therefore an ordinary parameterised query
  and the statement is composed with `psycopg.sql`, which quotes the literal and
  the identifier at the driver.

## Also decided here: no default table grants

`ALTER DEFAULT PRIVILEGES ... GRANT ALL ON TABLES TO graphrec_app` is deliberately
**not** issued. Every table must state its own grant, so a new table is
unreachable at runtime until someone decides what the runtime role may do with it.

This makes the append-only ledgers a positive decision rather than an omission
nobody noticed: `usage_events` and `audit_logs` receive `SELECT, INSERT` and never
`UPDATE` or `DELETE`; `api_keys` never receives `DELETE`.
