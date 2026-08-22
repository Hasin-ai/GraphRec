"""The three `SECURITY DEFINER` resolvers, and the blast radius they carry.

Migrations 0003, 0004 and 0005 punch three deliberate holes in default-deny:
sign-in has to find a tenant from a code, invitation acceptance has to find one
from a token digest, and API authentication has to find one from a credential
prefix — and none of those callers has a verified credential yet. Each hole is
one function owned by a `NOLOGIN` role with column-level `SELECT` and a single
`SELECT` policy.

The third is the widest, because it runs on every authenticated API request
rather than once per sign-in, and it is therefore the one whose grants are worth
re-reading.

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
    "tenant_lookup.resolve_api_key_prefix",
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
        # Three columns on `api_keys`, and `key_hash` is deliberately not among
        # them. The resolver says which tenant owns a prefix; the secret is
        # verified afterwards, inside that tenant's context, against the row
        # read under its own policy. A resolver that could read the digest would
        # be a resolver that could be made to leak it.
        ("api_keys", "tenant_id", "SELECT"),
        ("api_keys", "visible_prefix", "SELECT"),
        ("api_keys", "previous_visible_prefix", "SELECT"),
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
    assert commands == {
        ("tenants", "SELECT"),
        ("invitations", "SELECT"),
        ("api_keys", "SELECT"),
    }


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


@pytest.mark.parametrize("resolver", RESOLVERS)
def test_the_platform_role_cannot_call_a_resolver(platform_engine, resolver: str) -> None:
    """The holes are for the pre-credential paths, not for the platform realm.

    Parametrised rather than looped so that a resolver added later without an
    `EXECUTE` decision fails on its own line. A fresh connection per case
    because the first refusal aborts the transaction.
    """
    with platform_engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError) as caught:
        conn.execute(sa.text(f"SELECT {resolver}('anything')"))
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


# ------------------------------------------------------- the credential resolver


def test_a_credential_is_unreadable_without_a_bound_context(
    as_tenant, two_tenants, owner_engine
) -> None:
    """The same shape as the invitation case, on the hottest of the three paths.

    An unbound `SELECT` on `api_keys` is the shortcut the resolver replaces. If
    it ever returns a row, the resolver has stopped being the only way in and
    every authenticated request has become a cross-tenant read waiting to
    happen.
    """
    key_id = uuid.uuid4()
    prefix = f"gr_live_{key_id.hex[:4].upper()}"
    as_tenant(
        two_tenants["alpha"],
        "INSERT INTO api_keys (key_id, tenant_id, name, visible_prefix, key_hash, "
        "hash_version, scopes, expires_at) VALUES (:k, :t, 'Isolation probe', :p, "
        "'\\x00'::bytea, 1, ARRAY['events:write'], now() + interval '90 days') "
        "RETURNING key_id",
        k=key_id,
        t=two_tenants["alpha"],
        p=prefix,
    )
    try:
        assert as_tenant(None, "SELECT key_id FROM api_keys") == []
        assert (
            as_tenant(
                two_tenants["beta"],
                "SELECT key_id FROM api_keys WHERE visible_prefix = :p",
                p=prefix,
            )
            == []
        )
        # The resolver answers, and answers with the owning tenant rather than
        # the caller's. The prefix is not a secret — it is printed in the
        # console and in logs — so answering discloses nothing; what it must not
        # do is answer with more than the tenant.
        resolved = as_tenant(
            two_tenants["beta"],
            "SELECT tenant_lookup.resolve_api_key_prefix(:p) AS tid",
            p=prefix,
        )[0].tid
        assert resolved == two_tenants["alpha"]
    finally:
        # No role holds DELETE on `api_keys` either, for the same reason: a
        # credential that acted is part of the audit trail.
        with owner_engine.begin() as conn, _force_lifted(conn, "api_keys"):
            conn.execute(sa.text("DELETE FROM api_keys WHERE key_id = :k"), {"k": key_id})


def test_the_credential_resolver_reveals_nothing_for_an_unknown_prefix(
    as_tenant, two_tenants
) -> None:
    result = as_tenant(
        two_tenants["alpha"],
        "SELECT tenant_lookup.resolve_api_key_prefix(:p) AS tid",
        p=f"gr_live_{uuid.uuid4().hex[:4].upper()}",
    )
    assert result[0].tid is None


def test_no_role_may_delete_a_credential(owner_engine) -> None:
    """BUILD_PROMPT, verbatim: *"`api_keys` gets no `DELETE`."*

    Asserted against the grant rather than against behaviour, because a
    behavioural test passes for as long as nothing happens to try it. Revocation
    is `revoked_at`; a row that can be deleted is a row that can be deleted to
    hide something.
    """
    with owner_engine.connect() as conn:
        holders = {
            row.grantee
            for row in conn.execute(
                sa.text(
                    "SELECT grantee FROM information_schema.table_privileges "
                    "WHERE table_name = 'api_keys' AND privilege_type = 'DELETE'"
                )
            )
        }
    # The owner holds it implicitly and is never in the request path; no granted
    # role may.
    assert holders - {"graphrec_owner"} == set(), f"DELETE on api_keys granted to {holders}"
