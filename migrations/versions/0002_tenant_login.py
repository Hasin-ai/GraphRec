"""tenant login and refresh-session persistence

Revision ID: 0002_tenant_login
Revises: 0001_registration_slice
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tenant_login"
down_revision: Union[str, None] = "0001_registration_slice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("rotated_from_id", postgresql.UUID(as_uuid=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_users.tenant_id", "tenant_users.id"],
            ondelete="CASCADE",
            name="fk_refresh_sessions_tenant_user",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_refresh_sessions_expiry"),
    )
    op.create_index(
        "ix_refresh_sessions_tenant_user",
        "refresh_sessions",
        ["tenant_id", "user_id", "expires_at"],
    )

    op.execute("ALTER TABLE refresh_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_sessions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY refresh_sessions_tenant_select ON refresh_sessions
        FOR SELECT TO graphrec_app
        USING (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY refresh_sessions_tenant_insert ON refresh_sessions
        FOR INSERT TO graphrec_app
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_users_tenant_update ON tenant_users
        FOR UPDATE TO graphrec_app
        USING (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )

    op.execute("GRANT SELECT, INSERT ON refresh_sessions TO graphrec_app")
    op.execute("GRANT UPDATE (last_authenticated_at, credential_digest, status) ON tenant_users TO graphrec_app")
    op.execute(
        """
        CREATE FUNCTION resolve_login_identities(p_email text)
        RETURNS TABLE (
          user_id uuid,
          tenant_id uuid,
          normalized_email text,
          credential_digest text,
          user_status text,
          tenant_status text,
          user_role text
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
          SELECT
            tu.id,
            tu.tenant_id,
            lower(tu.email::text),
            tu.credential_digest,
            tu.status,
            t.status,
            tu.role
          FROM public.tenant_users AS tu
          JOIN public.tenants AS t ON t.id = tu.tenant_id
          WHERE lower(tu.email::text) = lower(p_email)
          ORDER BY tu.id
          LIMIT 3
        $function$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION resolve_login_identities(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION resolve_login_identities(text) TO graphrec_app")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION resolve_login_identities(text) FROM graphrec_app")
    op.execute("DROP FUNCTION resolve_login_identities(text)")
    op.execute("REVOKE UPDATE (last_authenticated_at) ON tenant_users FROM graphrec_app")
    op.execute("DROP POLICY IF EXISTS tenant_users_tenant_update ON tenant_users")
    op.execute("DROP POLICY IF EXISTS refresh_sessions_tenant_insert ON refresh_sessions")
    op.execute("DROP POLICY IF EXISTS refresh_sessions_tenant_select ON refresh_sessions")
    op.drop_index("ix_refresh_sessions_tenant_user", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
