"""Resolve a recovery proof to its tenant, before any credential exists.

Revision ID: 0014
Revises: 0013
Create Date: Phase 13

`recovery_tokens` has existed since migration 0002 and nothing has ever written
to it: `POST /v1/auth/recovery` was named in the backend plan (§4 UC-03) and
never built, so `/recover` and `/recover/confirm` were two console routes with
nothing behind them. This migration supplies the one database-side piece the
endpoints need.

It is migration 0004 again, applied to a second table, and for the same reason.
Somebody following a recovery link holds one thing — a `rec_…` proof — and holds
it *before* they can sign in, so there is no verified claim to bind
`app.tenant_id` from and an unbound read of `recovery_tokens` correctly returns
nothing. The alternative of carrying a tenant identifier alongside the proof is
rejected here for the reason 0004 gives at length: it establishes the pattern of
binding the tenant context from a request body.

Same three properties as 0004, and they are worth restating because a reviewer
should be able to check them without reading the other file:

* The function takes the **digest**, never the proof. The secret does not reach
  the database, so it is not in `pg_stat_statements` and not in a slow-query log.
* The grant is **column-level**. Through this path `graphrec_lookup` can read
  `tenant_id` and `token_digest` and nothing else — not `tenant_user_id`, not
  `expires_at`, not `consumed_at`. A caller who somehow reached the function
  learns only where a digest they already hold points.
* The function is a **pure resolver**. Whether the proof is still usable is a
  lifecycle question, `RecoveryToken.is_usable` already answers it, and a second
  copy of that rule in SQL is a copy that drifts. The re-read that follows runs
  bound, under the ordinary policy.

One difference from 0004, and it is a limitation rather than a decision: a
recovery proof issued to a *platform* user has `tenant_id IS NULL`, so this
function returns null for it and cannot be told apart from a proof that does not
exist. Platform operators therefore have no self-service recovery — an operator
account is restored by another operator. That is recorded in the Phase 13 report
rather than papered over with a second code path.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

APP_ROLE = "graphrec_app"
LOOKUP_ROLE = "graphrec_lookup"
LOOKUP_SCHEMA = "tenant_lookup"
FUNCTION_NAME = f"{LOOKUP_SCHEMA}.resolve_recovery_token"


def upgrade() -> None:
    op.execute(f"GRANT SELECT (tenant_id, token_digest) ON recovery_tokens TO {LOOKUP_ROLE}")

    op.execute("DROP POLICY IF EXISTS recovery_tokens_lookup_resolution ON recovery_tokens")
    op.execute(
        f"CREATE POLICY recovery_tokens_lookup_resolution ON recovery_tokens "
        f"FOR SELECT TO {LOOKUP_ROLE} USING (true)"
    )

    # Created *as* the lookup role, so the function's definer is the role whose
    # policy grants the read — `SECURITY DEFINER` on a function owned by the
    # migration runner would run as a superuser-adjacent role and read far more
    # than this is allowed to.
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
            SELECT r.tenant_id
            FROM public.recovery_tokens AS r
            WHERE r.token_digest = p_token_digest
            LIMIT 1
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_NAME}(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_NAME}(text) TO {APP_ROLE}")
    op.execute("RESET ROLE")


def downgrade() -> None:
    conn = op.get_bind()
    op.execute(f"SET LOCAL ROLE {LOOKUP_ROLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(text)")
    op.execute("RESET ROLE")
    op.execute("DROP POLICY IF EXISTS recovery_tokens_lookup_resolution ON recovery_tokens")

    present = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": LOOKUP_ROLE}
    ).scalar()
    if present:
        op.execute(f"REVOKE ALL ON recovery_tokens FROM {LOOKUP_ROLE}")
