"""Resolve an invitation token to its tenant, before any credential exists.

Revision ID: 0004
Revises: 0003
Create Date: Phase 2

Accepting an invitation has the same shape as signing in, and the same problem.
The invitee holds one thing — an `inv_…` token — and holds it *before* they have
an account, so there is no verified claim to bind `app.tenant_id` from, and an
unbound read of `invitations` correctly returns nothing.

The obvious shortcut is to carry the tenant identifier alongside the token, or
inside it, and bind from that. It would even be safe in this one case, because
the digest lookup afterwards would fail for a tenant the caller guessed. But it
establishes the pattern of binding the context from a request body, and the next
person to copy it will not be looking up a high-entropy secret. So: the same
arrangement as migration 0003, extended to one more table.

The function is a pure resolver. It answers "which tenant does this exact digest
belong to" and nothing else — it does not decide whether the invitation is still
open. Expiry, revocation and prior acceptance are lifecycle questions, they are
already answered by `Invitation.is_open`, and a second copy of that rule in SQL
is a copy that drifts. The re-read that follows runs bound, so the domain sees
the row under the ordinary policy.

It takes the *digest*, never the token. The token itself never reaches the
database — not as a parameter, not in `pg_stat_statements`, not in a log of slow
queries.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "graphrec_app"
LOOKUP_ROLE = "graphrec_lookup"
LOOKUP_SCHEMA = "tenant_lookup"
FUNCTION_NAME = f"{LOOKUP_SCHEMA}.resolve_invitation"


def upgrade() -> None:
    # Column-level again: `email`, `role` and `invited_by` are not readable
    # through this path. A caller who somehow reached the function could learn
    # only that a digest they already hold exists, and where it points.
    op.execute(f"GRANT SELECT (tenant_id, token_digest) ON invitations TO {LOOKUP_ROLE}")

    op.execute("DROP POLICY IF EXISTS invitations_lookup_resolution ON invitations")
    op.execute(
        f"CREATE POLICY invitations_lookup_resolution ON invitations "
        f"FOR SELECT TO {LOOKUP_ROLE} USING (true)"
    )

    op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}(p_token_digest text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT i.tenant_id
            FROM public.invitations AS i
            WHERE i.token_digest = p_token_digest
            LIMIT 1
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}(text) TO {APP_ROLE}")
    op.execute("RESET ROLE")


def downgrade() -> None:
    conn = op.get_bind()
    # Dropped *as* the lookup role, for the same reason it was created that way:
    # the function belongs to that role, in a schema the migration owner holds no
    # USAGE on. `DROP ... IF EXISTS` still needs to resolve the name, and
    # resolving it needs the schema.
    op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(text)")
    op.execute("RESET ROLE")
    op.execute("DROP POLICY IF EXISTS invitations_lookup_resolution ON invitations")

    present = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": LOOKUP_ROLE}
    ).scalar()
    if present:
        op.execute(f"REVOKE ALL ON invitations FROM {LOOKUP_ROLE}")
