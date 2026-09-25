"""index customer events by shopper for history assembly at serving time

DGSR serving reads one shopper's chronological events per recommendation
request. Without this index every request scanned the tenant's whole event
table.

Revision ID: 0011_event_user_history_index
Revises: 0010_account_setup_tokens
Create Date: 2026-09-12
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0011_event_user_history_index"
down_revision: Union[str, None] = "0010_account_setup_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_customer_events_tenant_user_time "
        "ON customer_events (tenant_id, user_id, occurred_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_customer_events_tenant_user_time")
