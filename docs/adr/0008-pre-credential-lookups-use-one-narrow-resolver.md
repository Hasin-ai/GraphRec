# ADR 0008 — Pre-credential lookups go through one narrow `SECURITY DEFINER` resolver

**Status:** Accepted
**Phase:** 2
**Date:** 2026-08-22

## Context

Two routes must find a tenant-owned row *before* the caller has any verified
credential:

- **Sign-in** holds a tenant code the caller typed, and must turn it into a
  `tenant_id` before `app.tenant_id` can be bound.
- **Invitation acceptance** holds an `inv_…` token, and the invitee has no
  account at all yet.

Under default-deny both reads correctly return nothing. That default is the
property the whole design rests on, so it is not relaxed.

The alternatives, and why each is worse:

- **A policy letting `graphrec_app` read `tenants` with no context bound.** This
  turns the table into an enumerable directory of every customer on the platform.
- **Passing `tenant_id` in the request body.** This makes tenant identity
  caller-supplied, which BUILD_PROMPT forbids outright. It would even be *safe*
  in the invitation case, because the digest lookup that follows fails for a
  guessed tenant — but it establishes a pattern, and the next person to copy it
  will not be looking up a high-entropy secret.
- **Running these routes as the owner.** Hands the unauthenticated login path a
  role that bypasses every policy in the database.

## Decision

One `SECURITY DEFINER` function per lookup, made as narrow as PostgreSQL allows,
and pinned by tests.

**Owned by a dedicated role, not by the table owner.** `FORCE ROW LEVEL SECURITY`
subjects the owner to its own policies and `SECURITY DEFINER` does not lift that,
so a function owned by `graphrec_owner` would run as a role no policy names and
return nothing. The functions are owned by `graphrec_lookup`: `NOLOGIN`,
`NOINHERIT`, no `CREATEDB`, no `CREATEROLE`, no `BYPASSRLS`. Nobody can connect
as it. The only way to act as it is to call one of its two functions.

**Column-level grants, never table-level.** `graphrec_lookup` holds `SELECT` on
`tenants(tenant_id, tenant_code, status)` and `invitations(tenant_id,
token_digest)`, and on nothing else in the database.

**One `SELECT` policy per table, and no others.** There is no `INSERT`, `UPDATE`
or `DELETE` policy naming `graphrec_lookup` anywhere, so neither function can be
rewritten into a write path that runs unconstrained.

**A schema of its own.** `tenant_lookup`, owned by `graphrec_lookup`. PostgreSQL
requires a function's owner to hold `CREATE` on the schema; granting that on
`public` would let the role shadow names other code resolves there.

**`SET search_path = pg_catalog, public`.** Without it, a `SECURITY DEFINER`
function resolves `tenants` against the *caller's* `search_path`, and a caller
able to create a table earlier on that path substitutes their own — which the
function then reads with the definer's privileges.

**`EXECUTE` revoked from `PUBLIC`, granted only to `graphrec_app`.** The platform
role cannot call either function.

**Each function answers one question and returns one `uuid`.**
`resolve_tenant_code` excludes deleted tenants, so a code freed by deletion does
not authenticate against the account that held it. `resolve_invitation` is a pure
resolver: it does *not* decide whether the invitation is still open, because
expiry, revocation and prior acceptance are lifecycle rules already expressed by
`Invitation.is_open`, and a second copy in SQL is the copy that drifts. The
re-read that follows runs bound, under the ordinary policy.

## Consequences

- Exactly one bit leaks per function: whether an exact tenant code exists, and
  whether an exact digest exists. The API relays neither — a wrong tenant code
  and a wrong password answer with the same sentence after the same amount of
  work, because sign-in still pays for a dummy Argon2id verification when the
  code does not resolve.
- Every one of the constraints above is asserted in
  `tests/isolation/test_lookup_resolvers.py`, so a later "make it easier" edit —
  a table-level grant, a second policy, `EXECUTE` to `PUBLIC`, a dropped
  `search_path` — fails rather than ships.
- The functions must be created *and dropped* with `SET LOCAL ROLE
  graphrec_lookup`. The migration role is granted the lookup role `WITH INHERIT
  FALSE, SET TRUE`, so it can act as it deliberately but never acquires its
  reads by accident. Getting this wrong made `alembic downgrade` fail with
  `permission denied for schema tenant_lookup`, which is why the down/up cycle
  is a CI job.
- Adding a third pre-credential lookup means a third function, a third
  column-level grant and a third set of tests. That cost is the point.
