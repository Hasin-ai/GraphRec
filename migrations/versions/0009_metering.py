"""Metering: the ledger nobody can edit, and the rollup that summarises it.

Two tables, and the division between them is the whole design.

`usage_events` is the **ledger**. One row per grant of usage — an accepted
event, a served recommendation, a started training job. It is append-only at the
*grant* level: `graphrec_app` holds `SELECT, INSERT` and nothing else, so a
quantity cannot be revised after the fact by application code, by a migration
that forgets, or by anyone holding the application's credentials. That is not a
stylistic preference. Usage is what a tenant is measured against, and a
measurement that can be silently rewritten is not a measurement.

`monthly_usage_aggregates` is the **account** of that ledger for one period. It
is derived, so it *is* updatable: the reconciliation rollup recomputes it from
the ledger and upserts. Recomputing from an immutable source is safe to repeat;
that is why the mutable table is the derived one and never the other way round.

The column that carries the phase's second obligation is
`measurement_status`. SRS NR-F-15 asks for usage "where calculable", and the
console renders a gap as a *status* — "measurement delayed", "not calculable" —
rather than as a zero (dc.html L1818, footnote L1824). A zero is a claim that
nothing happened. A delayed measurement is a claim that we do not yet know.
Conflating them would understate a tenant's usage and overstate their remaining
allowance, which is the one direction a billing-adjacent number must never err
in. So the status is stored, not inferred, and the absence of a row is itself
read as `delayed` rather than as zero.

Note what is *not* here: no Redis. The fast counters are a cache in front of
this ledger, and a cache does not get a schema. If Redis is empty, cold, or
wrong, the answer is recomputed from `usage_events` and the tenant sees the same
number. Losing the cache costs latency; it cannot cost a measurement.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
PLATFORM_ROLE = "graphrec_platform"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::UsageType`, generated from the prototype's usage
#: table (dc.html L709-715). Repeated because a migration cannot import
#: application code, and pinned by `tests/contract/test_migration_literals.py`.
USAGE_TYPES = (
    "events",
    "recommendations",
    "training",
    "products",
    "storage",
    "service_capacity",
)

#: `MeasurementStatus`. Three values, and the two that are not `measured` are
#: the reason the column exists at all.
MEASUREMENT_STATUSES = ("measured", "delayed", "unavailable")

#: Ordered so that a table's dependents are dropped before it.
TABLES = ("monthly_usage_aggregates", "usage_events")


def upgrade() -> None:
    _usage_events()
    _monthly_usage_aggregates()
    _indexes()
    _rls_and_grants()


def _usage_events() -> None:
    """One grant of usage, as it happened, forever.

    `quantity` is `numeric`, not an integer. Five of the six usage types count
    whole things, but `storage` is measured in bytes and future types may be
    fractional; a ledger that has to be migrated to change its arithmetic is a
    ledger that will be migrated wrongly. `numeric` also means the rollup's
    `SUM` is exact — a float would accumulate error across millions of rows and
    make the reconciliation disagree with itself by tiny, unexplainable amounts.

    `idempotency_key` is what makes a retried write safe. The metering call sits
    *inside* the transaction that creates the thing being metered (BUILD_PROMPT
    7.5), so a retry of that transaction re-attempts the grant too. The unique
    constraint turns the second attempt into a no-op instead of double-counting
    a tenant.
    """
    op.create_table(
        "usage_events",
        sa.Column(
            "usage_event_id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("usage_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 4), nullable=False),
        # What this grant was for — a submission id, a job id, a request id.
        # Free text on purpose: it is a breadcrumb for reconciliation, not a
        # foreign key, and it must survive the retention sweep of whatever it
        # points at.
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        # When the usage *happened*, which decides the period it lands in. Not
        # `created_at`: a batch accepted at 23:59:58 and written at 00:00:01
        # belongs to the month it was accepted in.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_usage_events_tenant_idempotency_key"
        ),
        # Non-negative, per BACKEND_PLAN L857. A correction is a later grant of
        # a different kind, not a negative one; allowing negatives here would
        # make the ledger editable by arithmetic after we took away UPDATE.
        sa.CheckConstraint("quantity >= 0", name="ck_usage_events_quantity_non_negative"),
        sa.CheckConstraint(
            "usage_type IN " + _sql_tuple(USAGE_TYPES),
            name="ck_usage_events_usage_type",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 200",
            name="ck_usage_events_idempotency_key_length",
        ),
    )


def _monthly_usage_aggregates() -> None:
    """What the ledger came to, for one tenant, one period, one type.

    The primary key is `(tenant_id, period_start, usage_type)` — SRS §5.2.15 —
    which is also the conflict target the rollup upserts against, so a rollup
    that runs twice produces the same row rather than a second one.

    `period_start` is a `date`, not a timestamp. A monthly period starts at
    midnight UTC on the first, and storing that as a timestamp invites a row at
    `2026-08-01 00:00:00+02` that is a different period wearing the same name.
    """
    op.create_table(
        "monthly_usage_aggregates",
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("usage_type", sa.Text(), nullable=False),
        # Nullable, and that is the point. A row may exist to record that we
        # *tried* to measure and could not — `quantity NULL` with
        # `measurement_status = 'delayed'`. A zero here would be a lie.
        sa.Column("quantity", sa.Numeric(20, 4), nullable=True),
        sa.Column(
            "measurement_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'delayed'::text"),
        ),
        # When the rollup last recomputed this row, which is what
        # `measurement_freshness` on the console is derived from.
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "period_start", "usage_type", name="pk_monthly_usage_aggregates"
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0", name="ck_mua_quantity_non_negative"
        ),
        sa.CheckConstraint("usage_type IN " + _sql_tuple(USAGE_TYPES), name="ck_mua_usage_type"),
        sa.CheckConstraint(
            "measurement_status IN " + _sql_tuple(MEASUREMENT_STATUSES),
            name="ck_mua_measurement_status",
        ),
        # A measured quantity is a number, and a number is a measurement. The
        # two columns cannot disagree, which is what stops a caller writing
        # `quantity = NULL, status = 'measured'` and rendering as a zero
        # downstream.
        sa.CheckConstraint(
            "(measurement_status = 'measured') = (quantity IS NOT NULL)",
            name="ck_mua_measured_iff_quantity",
        ),
    )


def _indexes() -> None:
    # The rollup's read: one tenant, one period, one type, summed. Ordered so
    # the period range is a scan bound rather than a filter.
    op.create_index(
        "ix_usage_events_tenant_type_occurred",
        "usage_events",
        ["tenant_id", "usage_type", "occurred_at"],
    )
    # The trend panel's read: three periods for one tenant, all types at once
    # (dc.html L1818).
    op.create_index(
        "ix_monthly_usage_aggregates_tenant_period",
        "monthly_usage_aggregates",
        ["tenant_id", "period_start"],
    )


def _rls_and_grants() -> None:
    for table in TABLES:
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

    # The exit criterion of this phase, expressed as an absence: no UPDATE and
    # no DELETE on `usage_events`, ever. `tests/metering/test_ledger.py`
    # asserts both raise for `graphrec_app`.
    op.execute(f"GRANT SELECT, INSERT ON usage_events TO {APP_ROLE}")
    # The derived table is recomputed in place, so it gets UPDATE. It does not
    # get DELETE: a period is superseded by a recomputation, never erased.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON monthly_usage_aggregates TO {APP_ROLE}")

    # `/admin/usage` is cross-tenant by design — UC-29 reads "Cross-tenant usage
    # by tenant, period and type, excluding private event payloads" (ROUTES L71).
    # The aggregate is exactly that exclusion made structural: the platform
    # realm can see what a tenant *used*, and has no grant at all on the ledger
    # rows or on `interaction_events` that would tell it what they used it on.
    op.execute(f"GRANT SELECT ON monthly_usage_aggregates TO {PLATFORM_ROLE}")
    op.execute(
        "CREATE POLICY monthly_usage_aggregates_platform_read ON monthly_usage_aggregates "
        f"FOR SELECT TO {PLATFORM_ROLE} USING (true)"
    )


def _sql_tuple(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS monthly_usage_aggregates_platform_read "
        "ON monthly_usage_aggregates"
    )
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON {table} FROM {PLATFORM_ROLE}")
        op.drop_table(table)
