"""Resolve a tenant code to an identifier, before any credential exists.

Revision ID: 0003
Revises: 0002
Create Date: Phase 2

Sign-in has a chicken-and-egg problem that RLS makes explicit rather than
creates. The tenant context must be bound from a verified value before any
tenant-owned row can be read — but at sign-in there is no verified value yet,
only a tenant code the caller typed. Reading `tenants` unbound returns nothing,
because `current_setting('app.tenant_id', true)` is NULL and `NULL = anything`
is NULL rather than TRUE. That default-deny is the property we want everywhere
else, so the answer is not to relax it.

The tempting fixes are all worse:

* A policy letting `graphrec_app` read `tenants` with no context bound turns the
  table into an enumerable directory of every customer on the platform.
* Passing `tenant_id` in the sign-in body would make tenant identity
  caller-supplied, which is the one thing the whole design forbids.
* Running sign-in as the owner would hand the login path a role that bypasses
  every policy in the database.

Instead: one `SECURITY DEFINER` function, as narrow as it can be made. It takes
an exact tenant code, returns one `uuid` and nothing else, and is executable only
by `graphrec_app`. It exposes exactly one bit — whether a given exact code exists
— and the API does not relay even that, because a wrong code and a wrong password
answer with the same sentence after the same amount of work.

**The function cannot be owned by the table owner.** `FORCE ROW LEVEL SECURITY`
subjects the owner to its own policies, and `SECURITY DEFINER` does not lift
that — a function owned by `graphrec_owner` would run as a role with no matching
policy and return nothing at all. So the function is owned by `graphrec_lookup`:
a `NOLOGIN` role that exists for this one purpose, holds `SELECT` on exactly
three columns of one table, and has exactly one policy. Nobody can connect as it;
it is reachable only by calling the function.

`SET search_path` is not decoration either. Without it a `SECURITY DEFINER`
function resolves `tenants` against the *caller's* `search_path`, and a caller
who can create a table in a schema earlier on that path substitutes their own
`tenants` — which the function then reads with the definer's privileges.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from psycopg import sql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLE = "graphrec_app"
LOOKUP_ROLE = "graphrec_lookup"
LOOKUP_SCHEMA = "tenant_lookup"
FUNCTION_NAME = f"{LOOKUP_SCHEMA}.resolve_tenant_code"


def _can_manage_roles(conn: sa.Connection) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user")
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()

    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": LOOKUP_ROLE}
    ).scalar()

    if not exists:
        if not _can_manage_roles(conn):
            raise RuntimeError(
                f"the migration role needs CREATEROLE (or superuser) to provision "
                f"{LOOKUP_ROLE!r}, which owns the sign-in tenant-code resolver. "
                "Create it out of band as NOLOGIN and re-run."
            )
        driver = conn.connection.driver_connection
        # NOLOGIN is the point: this role is a privilege container, not an
        # account. There is no password because there is no way to authenticate
        # as it — the only way to act as it is to call the function below.
        driver.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(LOOKUP_ROLE)
            )
        )

    # Changing a function's owner requires the current role to be able to
    # `SET ROLE` to the new owner. PostgreSQL 16 onwards does not grant that
    # implicitly to a CREATEROLE creator, so it is asked for explicitly — and
    # with `INHERIT FALSE`, so the migration role does *not* silently acquire
    # the lookup role's read on `tenants`. Reaching those privileges takes a
    # deliberate `SET ROLE`, which nothing in this codebase does.
    op.execute(f"GRANT {LOOKUP_ROLE} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {LOOKUP_ROLE}")
    # Column-level, not table-level. `tenant_name`, `settings` and
    # `status_reason` are not readable through this path even by accident.
    op.execute(f"GRANT SELECT (tenant_id, tenant_code, status) ON tenants TO {LOOKUP_ROLE}")

    # A schema of its own, owned by the lookup role. The alternative is granting
    # `CREATE ON SCHEMA public` to that role — PostgreSQL requires a function's
    # owner to hold CREATE on the schema it lives in — and a role able to create
    # objects in `public` can shadow names that other code resolves there.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {LOOKUP_SCHEMA} AUTHORIZATION {LOOKUP_ROLE}")

    # One policy, SELECT only, for one role. There is no INSERT, UPDATE or DELETE
    # policy for `graphrec_lookup` anywhere, so the function cannot be repurposed
    # into a write path.
    op.execute("DROP POLICY IF EXISTS tenants_lookup_resolution ON tenants")
    op.execute(
        f"CREATE POLICY tenants_lookup_resolution ON tenants "
        f"FOR SELECT TO {LOOKUP_ROLE} USING (true)"
    )

    # Created *as* the lookup role rather than created and then re-owned. The
    # migration role deliberately does not inherit the lookup role's privileges
    # (`INHERIT FALSE` above), so it holds no CREATE on this schema; `SET ROLE`
    # is the explicit, single-statement way to act as the owner, and it is reset
    # immediately afterwards.
    op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
    # USAGE only, and granted by the schema's owner because only an owner can
    # grant on its own schema. `graphrec_app` may call what is here and may not
    # add to it.
    op.execute(f"GRANT USAGE ON SCHEMA {LOOKUP_SCHEMA} TO {APP_ROLE}")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}(p_tenant_code text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT t.tenant_id
            FROM public.tenants AS t
            WHERE t.tenant_code = upper(btrim(p_tenant_code))
              -- A deleted tenant does not resolve. A code freed by deletion must
              -- not silently authenticate against the account that held it.
              AND t.status <> 'deleted'
            LIMIT 1
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}(text) TO {APP_ROLE}")
    op.execute("RESET ROLE")


def downgrade() -> None:
    conn = op.get_bind()
    # As the lookup role: it owns both the function and the schema, and the
    # migration owner deliberately holds neither USAGE on the schema nor the
    # inherited privileges to act for it. `SET ROLE` is the explicit way, and it
    # is granted `WITH SET TRUE` above for exactly this.
    if conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": LOOKUP_ROLE}
    ).scalar():
        op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(text)")
        op.execute(f"DROP SCHEMA IF EXISTS {LOOKUP_SCHEMA} CASCADE")
        op.execute("RESET ROLE")
    op.execute("DROP POLICY IF EXISTS tenants_lookup_resolution ON tenants")

    # Guarded: `REVOKE ... FROM <role>` errors if the role is absent, and a
    # downgrade must work against a database where an earlier revision of this
    # migration never created it.
    present = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": LOOKUP_ROLE}
    ).scalar()
    if present:
        op.execute(f"REVOKE ALL ON tenants FROM {LOOKUP_ROLE}")
        op.execute(f"REVOKE ALL ON SCHEMA public FROM {LOOKUP_ROLE}")
    # The role itself is left in place: dropping it would fail if anything else
    # in the cluster came to depend on it, and an unprivileged NOLOGIN role is
    # inert.
