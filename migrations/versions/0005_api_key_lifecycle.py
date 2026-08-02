"""tenant API-key lifecycle

Revision ID: 0005_api_key_lifecycle
Revises: 0004_usage_ledger
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_api_key_lifecycle"
down_revision: Union[str, None] = "0004_usage_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("hash_version", sa.Integer(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("previous_key_prefix", sa.String(16)),
        sa.Column("previous_key_hash", sa.String(64)),
        sa.Column("previous_hash_version", sa.Integer()),
        sa.Column("grace_expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "name", name="uq_api_keys_tenant_name"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_current_hash"),
        sa.CheckConstraint("hash_version > 0", name="ck_api_keys_hash_version"),
        sa.CheckConstraint(
            "grace_expires_at IS NULL OR previous_key_hash IS NOT NULL",
            name="ck_api_keys_grace_predecessor",
        ),
    )
    op.create_index("ix_api_keys_tenant_created", "api_keys", ["tenant_id", "created_at"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["key_prefix"])
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_keys FORCE ROW LEVEL SECURITY")
    for operation in ("SELECT", "INSERT", "UPDATE"):
        suffix = operation.lower()
        clause = "USING" if operation in {"SELECT", "UPDATE"} else "WITH CHECK"
        op.execute(
            f"""
            CREATE POLICY api_keys_tenant_{suffix} ON api_keys
            FOR {operation} TO graphrec_app
            {clause} (
              tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
            )
            """
        )
    op.execute("GRANT SELECT, INSERT, UPDATE ON api_keys TO graphrec_app")
    op.execute(
        """
        CREATE FUNCTION public.resolve_api_key_candidate(
          p_key_hash text,
          p_hash_version integer
        ) RETURNS TABLE(key_id uuid, tenant_id uuid)
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT key.id, key.tenant_id
          FROM public.api_keys AS key
          JOIN public.tenants AS tenant ON tenant.id = key.tenant_id
          WHERE key.revoked_at IS NULL
            AND (key.expires_at IS NULL OR key.expires_at > CURRENT_TIMESTAMP)
            AND tenant.status = 'active'
            AND (
              (key.key_hash = p_key_hash AND key.hash_version = p_hash_version)
              OR (
                key.previous_key_hash = p_key_hash
                AND key.previous_hash_version = p_hash_version
                AND key.grace_expires_at > CURRENT_TIMESTAMP
              )
            )
          LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.resolve_api_key_candidate(text, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.resolve_api_key_candidate(text, integer) TO graphrec_app")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION public.resolve_api_key_candidate(text, integer) FROM graphrec_app")
    op.execute("DROP FUNCTION IF EXISTS public.resolve_api_key_candidate(text, integer)")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON api_keys FROM graphrec_app")
    for operation in ("update", "insert", "select"):
        op.execute(f"DROP POLICY IF EXISTS api_keys_tenant_{operation} ON api_keys")
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant_created", table_name="api_keys")
    op.drop_table("api_keys")
