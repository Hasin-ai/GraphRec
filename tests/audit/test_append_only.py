"""The history is written once. Nothing in the running system can edit it.

Append-only here is not a convention, a trigger, or a promise in a docstring: it
is the *absence of a grant*. `UPDATE` and `DELETE` were never given to either
runtime role, so a rewrite is refused by the database before any application
code is consulted — which is the only version of this rule that survives a
handler being written in a hurry by someone who has not read this file.

The tests come in pairs on purpose. One asks the catalogue what the grants are;
the other actually tries the statement and reads the error. The catalogue check
localises a regression to the migration that caused it; the live attempt is the
one that would catch a grant restored somewhere the catalogue check does not
look — a `GRANT ... ON ALL TABLES`, say, in a later migration.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from psycopg import errors as pg_errors

ROLES = ("graphrec_app", "graphrec_platform")
TABLES = ("audit_logs", "security_events")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("table", TABLES)
def test_neither_runtime_role_may_update_or_delete_history(owner_engine, role, table) -> None:
    """The grant that would allow a rewrite does not exist for either role."""
    with owner_engine.connect() as conn:
        privileges = {
            privilege: conn.execute(
                sa.text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": role, "table": table, "privilege": privilege},
            ).scalar_one()
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }
    assert privileges["INSERT"], f"{role} cannot write to {table}"
    assert not privileges["UPDATE"], f"{role} can rewrite {table}"
    assert not privileges["DELETE"], f"{role} can erase rows from {table}"
    assert not privileges["TRUNCATE"], f"{role} can erase all of {table}"


def test_the_tenant_role_is_refused_when_it_tries_to_edit_its_own_history(
    audit_app_engine, audited_tenants
) -> None:
    """Not "no rows updated" — refused, by the grant, before the row is found."""
    tenant_id = audited_tenants["left"]["tenant_id"]
    with audit_app_engine.connect() as conn, conn.begin():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        with pytest.raises(sa.exc.ProgrammingError) as caught:
            conn.execute(sa.text("UPDATE audit_logs SET outcome = 'succeeded'"))
    assert isinstance(caught.value.orig, pg_errors.InsufficientPrivilege)


def test_the_platform_role_is_refused_when_it_tries_to_erase_a_failure(
    audit_platform_engine,
) -> None:
    """An operator embarrassed by a failure cannot make it not have happened."""
    with (
        audit_platform_engine.connect() as conn,
        conn.begin(),
        pytest.raises(sa.exc.ProgrammingError) as caught,
    ):
        conn.execute(sa.text("DELETE FROM security_events"))
    assert isinstance(caught.value.orig, pg_errors.InsufficientPrivilege)


def test_a_tenant_can_insert_a_row_it_cannot_then_edit(audit_app_engine, audited_tenants) -> None:
    """The whole shape of the grant, in one transaction: write, read, refuse.

    Worth asserting together because "append-only" is two facts that could each
    be true while the pair is useless — a role that cannot write leaves no
    history, and a role that can rewrite leaves no *evidence*.
    """
    tenant_id = audited_tenants["left"]["tenant_id"]
    reference = uuid.uuid4().hex[:8]
    with audit_app_engine.connect() as conn, conn.begin():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text(
                "INSERT INTO audit_logs (tenant_id, occurred_at, actor_type, action, "
                "resource_type, resource_ref, outcome) VALUES (:tid, now(), 'tenant_user', "
                "'credential', 'api_key', :ref, 'succeeded')"
            ),
            {"tid": tenant_id, "ref": reference},
        )
        found = conn.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE resource_ref = :ref"),
            {"ref": reference},
        ).scalar_one()
        assert found == 1

        with pytest.raises(sa.exc.ProgrammingError):
            conn.execute(
                sa.text("UPDATE audit_logs SET resource_ref = 'edited' WHERE resource_ref = :ref"),
                {"ref": reference},
            )
