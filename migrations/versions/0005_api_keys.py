"""API credentials.

One table. The interesting parts are what it does *not* store and what no role
is allowed to do to it.

The secret is never stored. What is stored is `HMAC-SHA-256(pepper, secret)`
alongside the `hash_version` that names which pepper produced it, so the pepper
can be rotated without invalidating every credential at once (SRS §5.2.4,
BACKEND_PLAN §17). HMAC rather than Argon2id is deliberate and is the opposite
of the password decision: an API credential is a 256-bit random value with no
guessing surface, and it is verified on every single request, so a deliberately
slow KDF would buy nothing and cost latency on the hot path.

No `DELETE` grant to any role. Revocation is `revoked_at`, not removal — a
credential that was used to submit events is part of the audit trail, and a row
that can be deleted is a row that can be deleted to hide something.

Rotation happens in place, on the same `key_id`, because the console's rotate
dialog mutates the row it was opened on (dc.html L1150). It issues a new prefix
and a new secret, and moves the outgoing pair into the `previous_*` columns so
that a caller mid-deploy is not cut off. See ADR 0010 for why the grace window
defaults to zero and is opt-in.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "graphrec_app"
PLATFORM_ROLE = "graphrec_platform"
LOOKUP_ROLE = "graphrec_lookup"
LOOKUP_SCHEMA = "tenant_lookup"
FUNCTION_NAME = f"{LOOKUP_SCHEMA}.resolve_api_key_prefix"
TENANT_GUC = "app.tenant_id"


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column(
            "key_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # Shown in the console's table so a person can tell two credentials
        # apart without ever seeing a secret (dc.html L1126). Globally unique,
        # not per-tenant: it is the lookup key on the authentication path, and a
        # prefix that could name two rows in different tenants would force the
        # verifier to disambiguate using something the caller supplied.
        sa.Column("visible_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("hash_version", sa.Integer(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        # The outgoing credential during a rotation grace window. All four move
        # together or not at all, which the CHECK below enforces.
        sa.Column("previous_visible_prefix", sa.Text(), nullable=True),
        sa.Column("previous_key_hash", sa.LargeBinary(), nullable=True),
        sa.Column("previous_hash_version", sa.Integer(), nullable=True),
        sa.Column("previous_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotation_reason", sa.Text(), nullable=True),
        # Written on the authentication path, so it is deliberately coarse: the
        # verifier updates it at most once a minute per credential rather than
        # on every request, because a write per request would make the hot path
        # a write path. Phase 3 records the value; the throttle lands with the
        # rate limiter in Phase 7.
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_api_keys_name_length"),
        # A credential with no scope authorizes nothing, which the console
        # refuses to create (dc.html L1137). Enforced here too: the API is not
        # the only way rows arrive.
        sa.CheckConstraint(
            "cardinality(scopes) BETWEEN 1 AND 12",
            name="ck_api_keys_scopes_cardinality",
        ),
        sa.CheckConstraint(
            "(previous_visible_prefix IS NULL) = (previous_key_hash IS NULL) "
            "AND (previous_key_hash IS NULL) = (previous_hash_version IS NULL) "
            "AND (previous_hash_version IS NULL) = (previous_expires_at IS NULL)",
            name="ck_api_keys_previous_is_all_or_nothing",
        ),
    )
    op.execute("CREATE UNIQUE INDEX uq_api_keys_visible_prefix ON api_keys (visible_prefix)")
    # Partial, because the column is NULL except during a grace window. It is
    # what makes an outgoing prefix resolvable, and it is unique for the same
    # reason the live one is.
    op.execute(
        "CREATE UNIQUE INDEX uq_api_keys_previous_visible_prefix "
        "ON api_keys (previous_visible_prefix) WHERE previous_visible_prefix IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_api_keys_tenant_id ON api_keys (tenant_id)")

    _enable_tenant_rls("api_keys")

    # No DELETE. Revocation sets `revoked_at`; the row stays.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON api_keys TO {APP_ROLE}")
    # The platform realm reads credentials for the tenant-detail screen
    # (Phase 12) and must never mint one. SELECT only, and no policy of its own
    # here — the platform policy is added in 0002's pattern below.
    op.execute(f"GRANT SELECT ON api_keys TO {PLATFORM_ROLE}")
    op.execute(
        f"CREATE POLICY api_keys_platform_access ON api_keys "
        f"FOR SELECT TO {PLATFORM_ROLE} USING (true)"
    )
    _resolver()


def _resolver() -> None:
    """Resolve a visible prefix to the tenant that owns it, and nothing else.

    The third instance of the pattern in ADR 0008, and the one with the widest
    blast radius, because this runs on every authenticated API request rather
    than once per sign-in.

    Column-level `SELECT` on exactly three columns. `key_hash` is *not* among
    them: this function says which tenant a prefix belongs to, and verification
    of the secret happens afterwards, inside that tenant's context, against the
    row read under its own policy. A resolver that could read the digest would
    be a resolver that could be made to leak it.

    The prefix alone is not a secret — it is printed in the console and in logs
    — so the fact that this function answers for a valid prefix discloses
    nothing. What it must not do is answer with more than the tenant.
    """
    op.execute(
        f"GRANT SELECT (tenant_id, visible_prefix, previous_visible_prefix) "
        f"ON api_keys TO {LOOKUP_ROLE}"
    )
    op.execute("DROP POLICY IF EXISTS api_keys_lookup_resolution ON api_keys")
    op.execute(
        f"CREATE POLICY api_keys_lookup_resolution ON api_keys "
        f"FOR SELECT TO {LOOKUP_ROLE} USING (true)"
    )

    op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}(p_prefix text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT k.tenant_id
            FROM public.api_keys AS k
            WHERE k.visible_prefix = p_prefix
               OR k.previous_visible_prefix = p_prefix
            LIMIT 1
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}(text) TO {APP_ROLE}")
    op.execute("RESET ROLE")


def _enable_tenant_rls(table: str) -> None:
    """The same four statements as every other tenant-owned table.

    Copied rather than imported: a migration that reaches into another
    migration's helpers stops being a standalone description of one change.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            FOR ALL TO {APP_ROLE}
            USING (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
            WITH CHECK (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
        """
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Dropped as the lookup role, which owns the function and holds the USAGE
    # on its schema that the migration owner deliberately lacks. Same reasoning
    # as 0003 and 0004; see either for the full note.
    op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(text)")
    op.execute("RESET ROLE")

    op.execute("DROP POLICY IF EXISTS api_keys_lookup_resolution ON api_keys")
    op.execute("DROP POLICY IF EXISTS api_keys_platform_access ON api_keys")
    op.execute("DROP POLICY IF EXISTS api_keys_tenant_isolation ON api_keys")

    present = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": LOOKUP_ROLE}
    ).scalar()
    if present:
        op.execute(f"REVOKE ALL ON api_keys FROM {LOOKUP_ROLE}")

    op.drop_table("api_keys")
