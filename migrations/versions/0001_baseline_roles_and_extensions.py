"""Baseline: the runtime role, extensions and schema privileges.

Establishes the privilege separation the whole isolation design rests on
(BUILD_PROMPT §7.1):

* `graphrec_owner` owns every object and runs migrations. It bypasses RLS, which
  is why nothing serves a request as this role.
* `graphrec_app` connects at runtime. It is a non-owner and non-superuser, so
  `FORCE ROW LEVEL SECURITY` binds it. It is granted no privilege by default —
  each table grants explicitly, and the immutable ledgers (`usage_events`,
  `audit_logs`) are granted `SELECT, INSERT` only.

`NOINHERIT` and the absence of `CREATEROLE`/`SUPERUSER` are load-bearing, not
decorative: a superuser bypasses RLS regardless of `FORCE`.

Revision ID: 0001
Revises:
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"


def upgrade() -> None:
    conn = op.get_bind()

    # pgcrypto backs gen_random_uuid(); UUIDv7 is generated in the application
    # (graphrec.common.ids) because PostgreSQL 16 has no uuidv7() of its own.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # Trigram search backs the product and user list filters the console renders.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    _ensure_app_role(conn, _app_password())

    # The runtime role may use the schema but may not create in it: schema
    # changes are a migration's business, and a runtime role that can CREATE can
    # also create a table without RLS.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {APP_ROLE}")
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")

    # Sequences are needed for any serial column the app inserts into.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    # Deliberately NOT granted by default:
    #   ALTER DEFAULT PRIVILEGES ... GRANT ALL ON TABLES TO graphrec_app
    # Every table states its own grant, so a new table is unreachable at runtime
    # until someone decides what the runtime role may do with it. That makes the
    # append-only ledgers a positive decision rather than an omission.


def downgrade() -> None:
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
    )
    # The role itself is left in place: dropping a role that may own objects in
    # another database, or be referenced by a running deployment, is not
    # something a schema downgrade should decide.
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")


def _ensure_app_role(conn: sa.Connection, password: str) -> None:
    """Create `graphrec_app`, or bring an existing one to the required shape.

    `CREATE ROLE` has no `IF NOT EXISTS` and the role may already exist, because
    Compose's init script creates it before the first migration runs. The obvious
    fix — wrapping it in `DO $$ ... $$` — cannot be used: a `DO` body is an
    opaque string to the server, so a bind parameter inside it has no resolvable
    type and psycopg fails with `IndeterminateDatatype`. Interpolating the
    password into that string instead would put a secret one quote away from SQL
    injection.

    So the existence check is an ordinary parameterised query, and the statement
    is composed with `psycopg.sql`, which quotes the literal and the identifier
    at the driver rather than by hand.
    """
    from psycopg import sql

    if not _can_manage_roles(conn):
        raise RuntimeError(
            "the migration role needs CREATEROLE (or superuser) to provision "
            f"{APP_ROLE!r}. Grant it, or create the runtime role out of band and "
            "re-run: this migration will then only adjust its attributes."
        )

    driver = conn.connection.driver_connection
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": APP_ROLE}
    ).scalar()

    if exists:
        # Only the two attributes a CREATEROLE owner is always permitted to
        # change. PostgreSQL requires the caller to *hold* an attribute before it
        # may grant or revoke it, so `ALTER ROLE ... NOCREATEDB` fails outright
        # when the migration owner has no CREATEDB of its own. The dangerous
        # attributes are therefore verified below rather than assigned here.
        statement = sql.SQL("ALTER ROLE {role} LOGIN NOINHERIT").format(
            role=sql.Identifier(APP_ROLE)
        )
    else:
        statement = sql.SQL(
            "CREATE ROLE {role} LOGIN NOINHERIT NOCREATEDB NOCREATEROLE PASSWORD {password}"
        ).format(role=sql.Identifier(APP_ROLE), password=sql.Literal(password))
    driver.execute(statement)

    _assert_runtime_role_is_constrained(conn)


#: Attributes that make the runtime role unfit to serve tenant traffic, and the
#: `pg_roles` column that reports each.
_FORBIDDEN_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("SUPERUSER", "rolsuper"),
    ("BYPASSRLS", "rolbypassrls"),
    ("CREATEROLE", "rolcreaterole"),
    ("CREATEDB", "rolcreatedb"),
)


def _assert_runtime_role_is_constrained(conn: sa.Connection) -> None:
    """Refuse to continue if the runtime role could step outside its tenant.

    SUPERUSER and BYPASSRLS defeat every policy this schema will ever define,
    `FORCE ROW LEVEL SECURITY` included — silently, with no error and no log
    line. CREATEROLE is a path to both. They are checked rather than assigned
    because PostgreSQL only lets a caller change an attribute it holds itself, so
    a migration run by an ordinary owner cannot clear them.

    Failing the migration is the correct outcome. A deployment whose runtime role
    can read every tenant's rows must not reach the point of serving traffic, and
    an unenforced policy produces no symptom until the leak is someone else's
    incident report.
    """
    columns = ", ".join(column for _, column in _FORBIDDEN_ATTRIBUTES)
    row = conn.execute(
        sa.text(f"SELECT {columns} FROM pg_roles WHERE rolname = :name"),
        {"name": APP_ROLE},
    ).one()
    offending = [name for (name, _), held in zip(_FORBIDDEN_ATTRIBUTES, row, strict=True) if held]
    if offending:
        held = " and ".join(offending)
        negated = " ".join(f"NO{name}" for name in offending)
        raise RuntimeError(
            f"{APP_ROLE!r} holds {held}. Row-level security would not constrain it, "
            "so tenant isolation would not hold. Run "
            f"`ALTER ROLE {APP_ROLE} {negated}` as a superuser and re-run this migration."
        )


def _can_manage_roles(conn: sa.Connection) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user")
        ).scalar()
    )


def _app_password() -> str:
    """The runtime role's password, from the environment.

    Falls back to the local development value only; a deployment sets
    POSTGRES_APP_PASSWORD, and `Settings` refuses to start in production while
    the default is still in place.
    """
    import os

    return os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
