"""The runtime role's privileges — the floor the whole isolation model stands on.

Every later isolation test asks "does this policy filter rows correctly?". This
one asks the prior question: *is the policy enforced at all?*

A role holding SUPERUSER or BYPASSRLS ignores every policy in the database,
`FORCE ROW LEVEL SECURITY` included. It does so silently: no error, no log line,
no failing query. A cross-tenant test suite written against such a role passes
completely and proves nothing. So this file runs first in the required gate, and
its failure message says which attribute to revoke.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

pytestmark = [pytest.mark.isolation, pytest.mark.db]

APP_ROLE = "graphrec_app"


@pytest.fixture(scope="module")
def role_attributes(owner_engine) -> sa.Row[tuple[bool, bool, bool, bool, bool]]:
    with owner_engine.connect() as connection:
        row = connection.execute(
            sa.text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit "
                "FROM pg_roles WHERE rolname = :name"
            ),
            {"name": APP_ROLE},
        ).one_or_none()
    if row is None:
        pytest.fail(
            f"{APP_ROLE!r} does not exist. Run `alembic upgrade head`; the runtime role "
            "is created by migration 0001, not by hand."
        )
    return row


def test_runtime_role_is_not_a_superuser(role_attributes) -> None:
    assert (
        not role_attributes.rolsuper
    ), "a superuser bypasses row-level security unconditionally; no policy would apply"


def test_runtime_role_cannot_bypass_rls(role_attributes) -> None:
    assert (
        not role_attributes.rolbypassrls
    ), "BYPASSRLS makes every USING clause advisory; cross-tenant reads would succeed"


def test_runtime_role_cannot_create_roles_or_databases(role_attributes) -> None:
    """CREATEROLE is a route back to both of the above."""
    assert not role_attributes.rolcreaterole
    assert not role_attributes.rolcreatedb


def test_runtime_role_does_not_inherit_privileges(role_attributes) -> None:
    """NOINHERIT — membership in a group must not silently confer its rights."""
    assert not role_attributes.rolinherit


def test_runtime_role_cannot_create_tables(owner_engine) -> None:
    """A role that can CREATE can create a table with no policy on it.

    That is the whole attack: the table is tenant-blind from birth, and nothing
    in the schema review ever sees it.
    """
    with owner_engine.connect() as connection:
        can_create = connection.execute(
            sa.text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"),
            {"role": APP_ROLE},
        ).scalar()
    assert (
        can_create is False
    ), "the runtime role may create in `public`; schema changes belong to migrations"


def test_runtime_role_may_use_the_schema(owner_engine) -> None:
    """The counterpart: revoking too much is a different outage, not a safer one."""
    with owner_engine.connect() as connection:
        can_use = connection.execute(
            sa.text("SELECT has_schema_privilege(:role, 'public', 'USAGE')"),
            {"role": APP_ROLE},
        ).scalar()
    assert can_use is True


def test_no_table_is_granted_to_the_runtime_role_by_default(owner_engine) -> None:
    """Migration 0001 deliberately sets no default table grants.

    Every table must state its own, so a new table is unreachable at runtime
    until someone decides what the runtime role may do with it — and the
    append-only ledgers (`usage_events`, `audit_logs`, never UPDATE or DELETE)
    are a positive decision rather than an omission nobody noticed.
    """
    with owner_engine.connect() as connection:
        defaults = connection.execute(
            sa.text(
                "SELECT count(*) FROM pg_default_acl d "
                "WHERE d.defaclobjtype = 'r' "
                "AND array_to_string(d.defaclacl, ',') LIKE :pattern"
            ),
            {"pattern": f"%{APP_ROLE}=%"},
        ).scalar()
    assert defaults == 0, (
        "a default table grant exists; new tables would become readable at runtime "
        "before anyone wrote a policy for them"
    )
