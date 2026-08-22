"""The claim function, and the blast radius it carries.

Migration 0006 punches a fourth hole in default-deny, and it is a different
shape from the three in `test_lookup_resolvers.py`. Those resolve one tenant
from something the caller already presented. This one *chooses* a tenant: a
worker serves every tenant and cannot bind `app.tenant_id` before it claims,
because which tenant it is working for is the answer the claim produces.

So the hole is wider by construction, and these tests are what keep it from
getting wider still. The three properties that matter:

  * the queue role can see enough to schedule and nothing more — never
    `payload`, which is where a tenant's data actually lives;
  * the claim returns two identifiers and no content, so the widened read
    cannot become a widened *disclosure*;
  * nothing else in the cluster can call it.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

pytestmark = [pytest.mark.isolation, pytest.mark.db]

QUEUE_ROLE = "graphrec_queue"
QUEUE_SCHEMA = "job_queue"
FUNCTIONS = ("claim", "expired_leases")

#: Exactly what a scheduler needs to order and time a queue. Written out rather
#: than derived, so that adding a column to the grant has to be done here too.
SCHEDULING_COLUMNS = {
    "job_id",
    "tenant_id",
    "job_type",
    "status",
    "priority",
    "run_after",
    "created_at",
    "started_at",
    "lease_expires_at",
}
LEASE_COLUMNS = {"status", "lease_owner", "lease_expires_at", "started_at", "updated_at"}


def test_the_queue_role_cannot_log_in(owner_engine) -> None:
    """A privilege container, not an account. There is no password to leak."""
    with owner_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
                "rolinherit FROM pg_roles WHERE rolname = :r"
            ),
            {"r": QUEUE_ROLE},
        ).one()
    assert not row.rolcanlogin
    assert not row.rolsuper
    assert not row.rolbypassrls
    assert not row.rolcreaterole
    assert not row.rolcreatedb
    # NOINHERIT: holding the role does not silently confer it. `SET ROLE` is
    # deliberate and shows up in a migration diff; inheritance would not.
    assert not row.rolinherit


def test_the_queue_role_never_sees_a_payload(owner_engine) -> None:
    """The single most important assertion in this file.

    A job's `payload` is the tenant's own data — a file key, a product list, a
    set of identifiers. The scheduler has no use for any of it, and a role that
    reads every row in the table must not be able to read that column.
    """
    with owner_engine.connect() as conn:
        readable = {
            row.column_name
            for row in conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE table_name = 'jobs' AND grantee = :r AND privilege_type = 'SELECT'"
                ),
                {"r": QUEUE_ROLE},
            )
        }
    assert "payload" not in readable
    assert "progress" not in readable
    assert "failure_reason" not in readable
    assert readable == SCHEDULING_COLUMNS


def test_the_queue_role_may_write_only_the_lease(owner_engine) -> None:
    """It moves a job to `running` and stamps who holds it. It does not decide
    outcomes: `attempt`, `failure_code` and `completed_at` are the tenant-bound
    session's to write, under that tenant's own policy."""
    with owner_engine.connect() as conn:
        writable = {
            row.column_name
            for row in conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE table_name = 'jobs' AND grantee = :r AND privilege_type = 'UPDATE'"
                ),
                {"r": QUEUE_ROLE},
            )
        }
    assert writable == LEASE_COLUMNS
    assert "attempt" not in writable, "the retry budget is not the scheduler's to spend"
    assert "payload" not in writable


def test_the_queue_role_holds_no_table_level_grant(owner_engine) -> None:
    """A table-level `SELECT` would quietly include every column added later.

    Which is how a `payload` exclusion decided once stops holding the first time
    somebody adds a column and re-runs a convenience grant.
    """
    with owner_engine.connect() as conn:
        table_level = {
            row.privilege_type
            for row in conn.execute(
                sa.text(
                    "SELECT privilege_type FROM information_schema.table_privileges "
                    "WHERE grantee = :r"
                ),
                {"r": QUEUE_ROLE},
            )
        }
    assert table_level == set()


def test_the_queue_policies_are_select_and_update_only(owner_engine) -> None:
    """No INSERT and no DELETE, anywhere, for this role.

    A `SECURITY DEFINER` function rewritten into a write path would otherwise run
    as a role that every tenant policy in the database ignores.
    """
    with owner_engine.connect() as conn:
        commands = {
            (row.tablename, row.cmd)
            for row in conn.execute(
                sa.text("SELECT tablename, cmd FROM pg_policies WHERE :r = ANY(roles)"),
                {"r": QUEUE_ROLE},
            )
        }
    assert commands == {("jobs", "SELECT"), ("jobs", "UPDATE")}


def test_the_queue_role_reaches_no_table_but_jobs(owner_engine) -> None:
    """It is granted on one table and named by one table's policies.

    `jobs` is the only place a scheduler has business being. If a later
    migration gives it a second table, that is a decision, and it should have to
    be made here.
    """
    with owner_engine.connect() as conn:
        tables = {
            row.table_name
            for row in conn.execute(
                sa.text(
                    "SELECT DISTINCT table_name FROM information_schema.column_privileges "
                    "WHERE grantee = :r"
                ),
                {"r": QUEUE_ROLE},
            )
        }
    assert tables == {"jobs"}


def test_only_the_app_role_may_claim(owner_engine) -> None:
    """`EXECUTE` to PUBLIC would expose the hole to every role in the cluster."""
    with owner_engine.connect() as conn:
        for name in FUNCTIONS:
            grantees = {
                row.grantee
                for row in conn.execute(
                    sa.text(
                        "SELECT grantee FROM information_schema.routine_privileges "
                        "WHERE specific_schema = :s AND routine_name = :n"
                    ),
                    {"s": QUEUE_SCHEMA, "n": name},
                )
            }
            assert "PUBLIC" not in grantees, f"{name} is executable by PUBLIC"
            assert grantees <= {"graphrec_app", QUEUE_ROLE}, f"{name} grantees: {grantees}"


def test_the_queue_functions_are_security_definer_and_owned_by_the_queue_role(owner_engine) -> None:
    """Owned by the queue role rather than by the migration owner.

    The owner can read every column of every table. A `SECURITY DEFINER`
    function owned by it would run with that reach, and the column-level grants
    above would be decorative.
    """
    with owner_engine.connect() as conn:
        rows = {
            row.proname: row
            for row in conn.execute(
                sa.text(
                    "SELECT p.proname, p.prosecdef, p.proconfig, r.rolname AS owner "
                    "FROM pg_proc AS p "
                    "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                    "JOIN pg_roles AS r ON r.oid = p.proowner "
                    "WHERE n.nspname = :s"
                ),
                {"s": QUEUE_SCHEMA},
            )
        }
    assert set(rows) == set(FUNCTIONS), f"unexpected functions in {QUEUE_SCHEMA}: {set(rows)}"
    for name, row in rows.items():
        assert row.prosecdef, f"{name} is not SECURITY DEFINER"
        assert row.owner == QUEUE_ROLE, f"{name} is owned by {row.owner}"
        # Without a pinned search_path a caller can substitute their own
        # `public.jobs` and have it read with the definer's privileges.
        assert row.proconfig is not None, f"{name} does not pin a search_path"
        assert any(entry.startswith("search_path=") for entry in row.proconfig)


def test_the_platform_role_cannot_claim(platform_engine) -> None:
    """The platform realm observes jobs. It does not run them.

    Its own read of `jobs` goes through `jobs_platform_access`, which is
    `SELECT` and does not include `payload` either.
    """
    with platform_engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError) as caught:
        conn.execute(sa.text("SELECT * FROM job_queue.claim('intruder', NULL, 60)"))
    assert "permission denied" in str(caught.value).lower()


def test_the_platform_role_cannot_read_a_payload(platform_engine) -> None:
    with platform_engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError) as caught:
        conn.execute(sa.text("SELECT payload FROM jobs"))
    assert "permission denied" in str(caught.value).lower()


def test_a_claim_returns_identifiers_and_nothing_else(owner_engine) -> None:
    """Read off the declared return type, not off a row.

    A signature that grew a `payload` column would be a cross-tenant disclosure
    on every claim, and it would pass every test that only ever looks at rows
    from a queue it seeded itself.
    """
    with owner_engine.connect() as conn:
        signatures = {
            row.proname: (row.args, row.result)
            for row in conn.execute(
                sa.text(
                    "SELECT p.proname, "
                    "pg_catalog.pg_get_function_arguments(p.oid) AS args, "
                    "pg_catalog.pg_get_function_result(p.oid) AS result "
                    "FROM pg_proc AS p "
                    "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = :s"
                ),
                {"s": QUEUE_SCHEMA},
            )
        }
    assert signatures["claim"][1] == "TABLE(claimed_job_id uuid, claimed_tenant_id uuid)"
    assert signatures["expired_leases"][1] == ("TABLE(expired_job_id uuid, expired_tenant_id uuid)")
    for name, (args, result) in signatures.items():
        assert "payload" not in result, f"{name} returns a payload"
        assert "jsonb" not in result, f"{name} returns tenant content"
        # And nothing tenant-scoped goes *in* either: a claim filtered by
        # tenant would be a scheduler taking instructions about whose work to
        # prefer from whoever called it.
        assert "tenant" not in args, f"{name} takes a tenant argument"


def test_no_role_may_delete_a_job(owner_engine) -> None:
    """A job is a record of what a tenant asked for and what happened.

    Same reasoning as `api_keys` (BUILD_PROMPT §7.4): the row that explains a
    charge, or a missing recommendation, must still be there when somebody asks.
    """
    with owner_engine.connect() as conn:
        deleters = {
            row.grantee
            for row in conn.execute(
                sa.text(
                    "SELECT grantee FROM information_schema.table_privileges "
                    "WHERE table_name = 'jobs' AND privilege_type = 'DELETE'"
                )
            )
        }
    assert deleters <= {"graphrec_owner"}, f"DELETE on jobs is granted to {deleters}"


def test_jobs_enforces_rls_against_its_own_owner(owner_engine) -> None:
    """`ENABLE` alone exempts the table owner. `FORCE` is what makes the policy
    a property of the table rather than of who happens to be connected."""
    with owner_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'jobs' AND relkind = 'r'"
            )
        ).one()
    assert row.relrowsecurity
    assert row.relforcerowsecurity


def test_an_unbound_session_sees_no_jobs(as_tenant) -> None:
    """Default-deny: `current_setting('app.tenant_id', true)` is NULL, the
    policy's `USING` is NULL, and NULL is not true."""
    assert as_tenant(None, "SELECT job_id FROM jobs") == []


def test_a_bound_session_cannot_insert_for_another_tenant(as_tenant, two_tenants) -> None:
    """`WITH CHECK`. Without it the tenant column is a request parameter."""
    with pytest.raises(sa.exc.ProgrammingError) as caught:
        as_tenant(
            two_tenants["alpha"],
            "INSERT INTO jobs (job_id, tenant_id, job_type, payload) "
            "VALUES (:j, :t, 'training', '{}'::jsonb)",
            j=uuid.uuid4(),
            t=two_tenants["beta"],
        )
    assert "row-level security" in str(caught.value).lower()
