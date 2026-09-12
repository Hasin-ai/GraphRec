"""one-time account setup tokens for invited tenant users

Password setup previously accepted any email address and overwrote that
account's credential, which allowed account takeover. Setup now requires a
single-use, expiring token that is issued to the registrant (or reissued by an
operator) and stored only as a SHA-256 hash.

Revision ID: 0010_account_setup_tokens
Revises: 0009_domain_rls_platform
Create Date: 2026-09-11
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0010_account_setup_tokens"
down_revision: Union[str, None] = "0009_domain_rls_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
RESOLVER = "public.resolve_account_setup_token(text)"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE account_setup_tokens (
          id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
          user_id uuid NOT NULL,
          token_hash varchar(64) NOT NULL,
          created_at timestamptz NOT NULL,
          expires_at timestamptz NOT NULL,
          used_at timestamptz,
          revoked_at timestamptz,
          CONSTRAINT uq_account_setup_tokens_hash UNIQUE (token_hash),
          CONSTRAINT fk_account_setup_tokens_tenant_user
            FOREIGN KEY (tenant_id, user_id)
            REFERENCES tenant_users (tenant_id, id) ON DELETE CASCADE,
          CONSTRAINT ck_account_setup_tokens_expiry CHECK (expires_at > created_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_account_setup_tokens_tenant_user "
        "ON account_setup_tokens (tenant_id, user_id)"
    )

    op.execute("ALTER TABLE account_setup_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE account_setup_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY account_setup_tokens_tenant_select ON account_setup_tokens
        FOR SELECT TO graphrec_app USING ({TENANT_PREDICATE})
        """
    )
    op.execute(
        f"""
        CREATE POLICY account_setup_tokens_tenant_insert ON account_setup_tokens
        FOR INSERT TO graphrec_app WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute(
        f"""
        CREATE POLICY account_setup_tokens_tenant_update ON account_setup_tokens
        FOR UPDATE TO graphrec_app
        USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute("GRANT SELECT, INSERT ON account_setup_tokens TO graphrec_app")
    op.execute("GRANT UPDATE (used_at, revoked_at) ON account_setup_tokens TO graphrec_app")

    # The setup endpoint is public, so it cannot know the tenant before the token
    # is resolved. Lookup is only possible by the hash of an unguessable token.
    op.execute(
        """
        CREATE FUNCTION public.resolve_account_setup_token(p_token_hash text)
        RETURNS TABLE (
          token_id uuid,
          tenant_id uuid,
          user_id uuid,
          normalized_email text,
          user_status text,
          user_role text,
          has_credential boolean,
          tenant_status text,
          expires_at timestamptz,
          used_at timestamptz,
          revoked_at timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
          SELECT
            st.id,
            st.tenant_id,
            st.user_id,
            lower(tu.email::text),
            tu.status::text,
            tu.role::text,
            tu.credential_digest IS NOT NULL,
            t.status::text,
            st.expires_at,
            st.used_at,
            st.revoked_at
          FROM public.account_setup_tokens AS st
          JOIN public.tenant_users AS tu
            ON tu.tenant_id = st.tenant_id AND tu.id = st.user_id
          JOIN public.tenants AS t ON t.id = st.tenant_id
          WHERE st.token_hash = p_token_hash
        $function$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {RESOLVER} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RESOLVER} TO graphrec_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {RESOLVER}")
    op.execute("DROP TABLE IF EXISTS account_setup_tokens")
