"""Cross-tenant reads and writes — the required merge gate.

BUILD_PROMPT: *"Never weaken tenant isolation to make something work. If
isolation and a feature conflict, the feature is wrong."* These tests are how
that sentence is kept true after the person who wrote it has moved on.

Every test connects as `graphrec_app`, the role that actually serves traffic.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

pytestmark = [pytest.mark.isolation, pytest.mark.db]

#: Every tenant-owned table, and the column a policy filters on. New tables are
#: added here; `test_every_tenant_table_is_protected` fails if one is not.
TENANT_TABLES: tuple[str, ...] = (
    "tenants",
    "tenant_users",
    "invitations",
    "tenant_subscriptions",
    "tenant_resource_quotas",
    "quota_overrides",
    "refresh_sessions",
    "recovery_tokens",
)


# ------------------------------------------------------------------- reads


def test_a_tenant_sees_only_its_own_row(as_tenant, two_tenants) -> None:
    rows = as_tenant(two_tenants["alpha"], "SELECT tenant_id FROM tenants")
    assert [r.tenant_id for r in rows] == [two_tenants["alpha"]]


def test_a_tenant_cannot_read_another_tenants_users(as_tenant, two_tenants) -> None:
    rows = as_tenant(two_tenants["alpha"], "SELECT tenant_user_id, tenant_id FROM tenant_users")
    assert {r.tenant_id for r in rows} == {two_tenants["alpha"]}
    assert two_tenants["beta_user"] not in {r.tenant_user_id for r in rows}


def test_naming_a_foreign_row_directly_returns_nothing(as_tenant, two_tenants) -> None:
    """The case that matters: the attacker already knows the identifier.

    Guessing is not the threat — an identifier leaks through a log, a support
    ticket or a shared screenshot. A `WHERE` clause naming a known foreign row
    must still return zero rows, which is what turns this into a 404 at the API
    rather than a 403.
    """
    rows = as_tenant(
        two_tenants["alpha"],
        "SELECT tenant_user_id FROM tenant_users WHERE tenant_user_id = :uid",
        uid=two_tenants["beta_user"],
    )
    assert rows == []


def test_an_aggregate_cannot_count_foreign_rows(as_tenant, two_tenants) -> None:
    """A count is a read. `SELECT count(*)` is the cheapest existence oracle."""
    total = as_tenant(two_tenants["alpha"], "SELECT count(*) AS n FROM tenants")[0].n
    assert total == 1


def test_no_tenant_context_returns_no_rows(as_tenant, two_tenants) -> None:
    """Default deny.

    With the GUC unset, `tenant_id = NULL` is `NULL`, which is not `TRUE`. The
    policy therefore matches nothing. This is the property that makes forgetting
    to bind a context an empty result instead of a full table scan across every
    tenant in the system.
    """
    assert as_tenant(None, "SELECT tenant_id FROM tenants") == []
    assert as_tenant(None, "SELECT tenant_user_id FROM tenant_users") == []


def test_an_unknown_tenant_context_returns_no_rows(as_tenant, two_tenants) -> None:
    assert as_tenant(uuid.uuid4(), "SELECT tenant_id FROM tenants") == []


# ------------------------------------------------------------------ writes


def test_a_tenant_cannot_insert_a_row_owned_by_another(as_tenant, two_tenants) -> None:
    """This is what `WITH CHECK` is for, and why `USING` alone is not enough.

    With only a `USING` clause the insert succeeds and the row becomes invisible
    to its author — a bug that never appears in the tenant's own console and is
    found, if ever, by the victim.
    """
    with pytest.raises(sa.exc.ProgrammingError) as caught:
        as_tenant(
            two_tenants["alpha"],
            "INSERT INTO tenant_users (tenant_user_id, tenant_id, email, display_name, "
            "credential_digest, role, status) VALUES (:uid, :tid, 'x@example.test', 'X', "
            "'digest', 'tenant_developer', 'active')",
            uid=uuid.uuid4(),
            tid=two_tenants["beta"],
        )
    assert "row-level security" in str(caught.value).lower()


def test_a_tenant_cannot_move_a_row_to_another_tenant(as_tenant, two_tenants) -> None:
    """Re-stamping `tenant_id` on an owned row is an exfiltration primitive."""
    with pytest.raises(sa.exc.ProgrammingError) as caught:
        as_tenant(
            two_tenants["alpha"],
            "UPDATE tenant_users SET tenant_id = :beta WHERE tenant_user_id = :uid",
            beta=two_tenants["beta"],
            uid=two_tenants["alpha_user"],
        )
    assert "row-level security" in str(caught.value).lower()


def test_an_update_cannot_reach_a_foreign_row(as_tenant, two_tenants, platform_engine) -> None:
    """A blind `UPDATE` affects zero rows rather than someone else's.

    Note that this one does not raise. `USING` filters the row out before the
    update is considered, so the statement succeeds having changed nothing —
    which is the correct behaviour, and is why the assertion checks the victim's
    row afterwards rather than trusting the absence of an exception.
    """
    affected = as_tenant(
        two_tenants["alpha"],
        "UPDATE tenant_users SET display_name = 'owned' WHERE tenant_user_id = :uid "
        "RETURNING tenant_user_id",
        uid=two_tenants["beta_user"],
    )
    assert affected == []

    # Read back as the platform role, not the owner: `FORCE` fences the owner out
    # of `tenant_users` too, and the platform realm is the only one entitled to
    # look across tenants.
    with platform_engine.connect() as conn:
        name = conn.execute(
            sa.text("SELECT display_name FROM tenant_users WHERE tenant_user_id = :uid"),
            {"uid": two_tenants["beta_user"]},
        ).scalar_one()
    assert name != "owned"


def test_a_delete_cannot_reach_a_foreign_row(as_tenant, two_tenants) -> None:
    """`tenant_users` carries no DELETE grant at all; disabling is not deletion."""
    with pytest.raises(sa.exc.ProgrammingError) as caught:
        as_tenant(
            two_tenants["alpha"],
            "DELETE FROM tenant_users WHERE tenant_user_id = :uid",
            uid=two_tenants["beta_user"],
        )
    assert "permission denied" in str(caught.value).lower()


def test_registration_cannot_mint_a_tenant_it_is_not_bound_to(as_tenant) -> None:
    """`INSERT` on `tenants` is granted, and `WITH CHECK` is what makes it safe.

    Registration works by minting a `tenant_id`, binding the context to it and
    inserting. This asserts the other half: bound to one identifier, a caller
    cannot create a row under a different one. Without this, the INSERT grant
    added for registration would let any authenticated connection manufacture
    tenants at will.
    """
    bound = uuid.uuid4()
    with pytest.raises(sa.exc.ProgrammingError) as caught:
        as_tenant(
            bound,
            "INSERT INTO tenants (tenant_id, plan_id, tenant_code, tenant_name, status) "
            "SELECT :other, plan_id, :code, :name, 'active' FROM pricing_plans "
            "WHERE plan_code = 'GROWTH'",
            other=uuid.uuid4(),
            code=f"FRG-{bound.hex[:8]}",
            name=f"Forged {bound.hex[:8]}",
        )
    assert "row-level security" in str(caught.value).lower()


# ------------------------------------------------------------------ realms


def test_the_tenant_role_cannot_read_platform_users(as_tenant, two_tenants) -> None:
    """Cross-realm access is refused at the grant, not by a policy.

    A tenant has no business enumerating platform operators, so the privilege was
    never granted. A policy could be edited; a missing grant has to be added
    deliberately.
    """
    with pytest.raises(sa.exc.ProgrammingError) as caught:
        as_tenant(two_tenants["alpha"], "SELECT platform_user_id FROM platform_users")
    assert "permission denied" in str(caught.value).lower()


def test_the_tenant_role_cannot_read_platform_permissions(as_tenant, two_tenants) -> None:
    with pytest.raises(sa.exc.ProgrammingError):
        as_tenant(two_tenants["alpha"], "SELECT permission FROM platform_user_permissions")


def test_a_tenant_cannot_see_a_platform_session(
    as_tenant, two_tenants, platform_engine, owner_engine
) -> None:
    """Platform sessions carry `tenant_id IS NULL`, so no tenant policy matches.

    The tenant realm must never be able to enumerate — let alone revoke — an
    operator's session.
    """
    session_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    with platform_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_users (platform_user_id, email, display_name, "
                "credential_digest) VALUES (:pid, :email, 'Operator', 'digest')"
            ),
            {"pid": operator_id, "email": f"op-{session_id.hex[:8]}@platform.test"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO refresh_sessions (refresh_session_id, platform_user_id, "
                "token_digest, expires_at) VALUES (:s, :pid, :digest, now() + interval '1 day')"
            ),
            {"s": session_id, "pid": operator_id, "digest": f"digest-{session_id.hex}"},
        )
    try:
        rows = as_tenant(two_tenants["alpha"], "SELECT * FROM refresh_sessions")
        assert rows == []
    finally:
        with owner_engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM platform_users WHERE platform_user_id = :pid"),
                {"pid": operator_id},
            )


# ------------------------------------------------------- the structural gate


def test_every_tenant_table_is_protected(owner_engine) -> None:
    """The test that catches the table somebody adds in Phase 6 and forgets.

    Asserted from `pg_class` and `pg_policies` rather than by reading the
    migration, so it holds whatever a later migration does. `FORCE` is checked
    separately from `ENABLE`: without it the owner — which is what a repair
    script or a data migration runs as — silently sees every tenant.
    """
    with owner_engine.connect() as conn:
        flags = {
            row.relname: (row.relrowsecurity, row.relforcerowsecurity)
            for row in conn.execute(
                sa.text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
                )
            )
        }
    for table in TENANT_TABLES:
        enabled, forced = flags[table]
        assert enabled, f"{table} is tenant-owned but row-level security is not ENABLEd"
        assert forced, f"{table} has RLS ENABLEd but not FORCEd; the owner would bypass it"


def test_every_tenant_policy_has_both_using_and_with_check(owner_engine) -> None:
    """`USING` filters reads; `WITH CHECK` constrains writes. Both, or neither works."""
    with owner_engine.connect() as conn:
        policies = list(
            conn.execute(
                sa.text(
                    "SELECT tablename, policyname, qual, with_check FROM pg_policies "
                    "WHERE schemaname = 'public' AND 'graphrec_app' = ANY(roles)"
                )
            )
        )
    covered = {p.tablename for p in policies}
    missing = set(TENANT_TABLES) - covered
    assert not missing, f"no graphrec_app policy on {sorted(missing)}"

    for policy in policies:
        assert policy.qual, f"{policy.policyname} has no USING clause"
        assert policy.with_check, (
            f"{policy.policyname} has no WITH CHECK clause: a tenant could insert a row "
            "stamped with another tenant's id and then never see it again"
        )


def test_no_tenant_policy_is_permissive_to_everyone(owner_engine) -> None:
    """A policy applied `TO PUBLIC` would cover the platform role as well."""
    with owner_engine.connect() as conn:
        rows = list(
            conn.execute(
                sa.text(
                    "SELECT tablename, policyname, roles FROM pg_policies "
                    "WHERE schemaname = 'public'"
                )
            )
        )
    for row in rows:
        named = [r.lower() for r in row.roles]
        assert "-" not in named, f"{row.policyname} on {row.tablename} applies to PUBLIC"
        assert "public" not in named, f"{row.policyname} on {row.tablename} applies to PUBLIC"
