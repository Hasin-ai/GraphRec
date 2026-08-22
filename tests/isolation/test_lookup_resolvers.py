"""The two `SECURITY DEFINER` resolvers, and the blast radius they carry.

Migrations 0003 and 0004 punch two deliberate holes in default-deny: sign-in has
to find a tenant from a code, and invitation acceptance has to find one from a
token digest, and neither caller has a credential yet. Each hole is one function
owned by a `NOLOGIN` role with column-level `SELECT` and a single `SELECT` policy.

These tests pin the size of the hole. They are the reason a later "make it
easier" edit — a table-level grant, a second policy, `EXECUTE` to `PUBLIC` —
fails rather than ships.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests.isolation.conftest import _force_lifted

pytestmark = [pytest.mark.isolation, pytest.mark.db]

LOOKUP_ROLE = "graphrec_lookup"
RESOLVERS = (
    "tenant_lookup.resolve_tenant_code",
    "tenant_lookup.resolve_invitation",
)


def test_the_lookup_role_cannot_log_in(owner_engine) -> None:
    """It is a privilege container, not an account. There is no password to leak."""
    with owner_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                "FROM pg_roles WHERE rolname = :r"
            ),
            {"r": LOOKUP_ROLE},
        ).one()
    assert not row.rolcanlogin
    assert not row.rolsuper
    assert not row.rolbypassrls
    assert not row.rolcreaterole
    assert not row.rolcreatedb


def test_the_lookup_role_holds_only_column_level_selects(owner_engine) -> None:
    """A table-level grant would make the next resolver able to read everything."""
    with owner_engine.connect() as conn:
        table_level = conn.execute(
            sa.text(
                "SELECT table_name, privilege_type FROM information_schema.table_privileges "
                "WHERE grantee = :r"
            ),
            {"r": LOOKUP_ROLE},
        ).all()
        column_level = {
            (row.table_name, row.column_name, row.privilege_type)
            for row in conn.execute(
                sa.text(
                    "SELECT table_name, column_name, privilege_type "
                    "FROM information_schema.column_privileges WHERE grantee = :r"
                ),
                {"r": LOOKUP_ROLE},
            )
        }
    assert table_level == [], f"{LOOKUP_ROLE} holds table-wide privileges: {table_level}"
    assert {privilege for _, _, privilege in column_level} == {"SELECT"}
    assert column_level == {
        ("tenants", "tenant_id", "SELECT"),
        ("tenants", "tenant_code", "SELECT"),
        ("tenants", "status", "SELECT"),
        ("invitations", "tenant_id", "SELECT"),
        ("invitations", "token_digest", "SELECT"),
    }


def test_the_lookup_policies_are_select_only(owner_engine) -> None:
    """No INSERT, UPDATE or DELETE policy names the lookup role anywhere.

    Without this, a `SECURITY DEFINER` function could be rewritten into a write
    path that runs as a role exempt from every tenant policy in the database.
    """
    with owner_engine.connect() as conn:
        commands = {
            (row.tablename, row.cmd)
            for row in conn.execute(
                sa.text("SELECT tablename, cmd FROM pg_policies WHERE :r = ANY(roles)"),
                {"r": LOOKUP_ROLE},
            )
        }
    assert commands == {("tenants", "SELECT"), ("invitations", "SELECT")}


def test_only_the_app_role_may_execute_a_resolver(owner_engine) -> None:
    """`EXECUTE` to PUBLIC would expose the hole to every role in the cluster."""
    with owner_engine.connect() as conn:
        for name in RESOLVERS:
            grantees = {
                row.grantee
                for row in conn.execute(
                    sa.text(
                        "SELECT grantee FROM information_schema.routine_privileges "
                        "WHERE specific_schema = 'tenant_lookup' AND routine_name = :n"
                    ),
                    {"n": name.split(".", 1)[1]},
                )
            }
            assert "PUBLIC" not in grantees, f"{name} is executable by PUBLIC"
            assert grantees <= {"graphrec_app", LOOKUP_ROLE}, f"{name} grantees: {grantees}"


def test_the_resolvers_pin_their_search_path(owner_engine) -> None:
    """Without this a caller can substitute their own `tenants` table.

    A `SECURITY DEFINER` function resolves unqualified names against the
    *caller's* `search_path`, and runs the result with the definer's privileges.
    """
    with owner_engine.connect() as conn:
        for name in RESOLVERS:
            # Looked up by name rather than cast through `regprocedure`: the
            # cast needs USAGE on the schema, and the migration owner
            # deliberately does not hold it.
            config = conn.execute(
                sa.text(
                    "SELECT p.proconfig FROM pg_proc AS p "
                    "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'tenant_lookup' AND p.proname = :n"
                ),
                {"n": name.split(".", 1)[1]},
            ).scalar_one()
            assert config is not None, f"{name} does not pin a search_path"
            assert any(entry.startswith("search_path=") for entry in config)


def test_the_platform_role_cannot_call_a_resolver(app_engine, platform_engine) -> None:
    """The hole is for the sign-in path, not for the platform realm."""
    with platform_engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError) as caught:
        conn.execute(sa.text("SELECT tenant_lookup.resolve_tenant_code('ANY')"))
    assert "permission denied" in str(caught.value).lower()


def test_an_invitation_is_unreadable_without_a_bound_context(
    as_tenant, two_tenants, owner_engine
) -> None:
    """The resolver exists precisely because this returns nothing — and it must.

    An unbound `SELECT` on `invitations` is the shortcut the resolver replaces.
    If this ever returns a row, the resolver has stopped being the only way in.
    """
    invitation_id = uuid.uuid4()
    digest = f"digest-{invitation_id.hex}"
    as_tenant(
        two_tenants["alpha"],
        "INSERT INTO invitations (invitation_id, tenant_id, email, role, token_digest, "
        "expires_at) VALUES (:i, :t, 'invitee@example.com', 'tenant_developer', :d, "
        "now() + interval '7 days') RETURNING invitation_id",
        i=invitation_id,
        t=two_tenants["alpha"],
        d=digest,
    )
    try:
        assert as_tenant(None, "SELECT invitation_id FROM invitations") == []
        assert (
            as_tenant(
                two_tenants["beta"],
                "SELECT invitation_id FROM invitations WHERE token_digest = :d",
                d=digest,
            )
            == []
        )
        # The resolver, however, answers — and answers with the owning tenant,
        # not the caller's. That is the whole point, and it is safe because
        # possession of the digest is the proof.
        resolved = as_tenant(
            two_tenants["beta"],
            "SELECT tenant_lookup.resolve_invitation(:d) AS tid",
            d=digest,
        )[0].tid
        assert resolved == two_tenants["alpha"]
    finally:
        # No role holds DELETE on `invitations` — an invitation is revoked, not
        # removed — so teardown is the owner with `FORCE` briefly lifted, the
        # same escape hatch the fixtures use and for the same reason.
        with owner_engine.begin() as conn, _force_lifted(conn, "invitations"):
            conn.execute(
                sa.text("DELETE FROM invitations WHERE invitation_id = :i"),
                {"i": invitation_id},
            )


def test_the_resolver_reveals_nothing_for_an_unknown_digest(as_tenant, two_tenants) -> None:
    result = as_tenant(
        two_tenants["alpha"],
        "SELECT tenant_lookup.resolve_invitation(:d) AS tid",
        d=f"digest-{uuid.uuid4().hex}",
    )
    assert result[0].tid is None
