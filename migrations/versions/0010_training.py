"""Training: the job the schema itself serialises.

Four tables, and the one that carries the phase's obligation is
`training_jobs`. Everything else here is a record of what a run read, produced
or measured.

**The concurrency rule is an index, not a check in application code.**
ASM-03 allows one training run at a time, and the console says so on the page
itself: *"Global training concurrency is 1."* (dc.html L1646). A
`SELECT … then INSERT` in the request handler cannot enforce that — two requests
arriving in the same millisecond both read no active job and both insert one.
So the rule is a **partial unique index on `tenant_id` over the nine
non-terminal states**: the second insert is refused by PostgreSQL, the handler
catches the violation and answers `409`. There is no window in which it can be
wrong, and no lock held across the check.

`request_ref` gets its own `UNIQUE(tenant_id, request_ref)` for the second
idempotency question, which is a *different* one. The partial index says "not
while another is running"; this one says "not this request twice", and a repeat
is a **success** returning the original job (§17.3) rather than a conflict — the
integration that retried after a timeout did nothing wrong.

**What is deliberately not here.** The plan's `training_jobs` row lists
`snapshot_id` and `model_version_id` alongside `dataset_snapshots.training_job_id
UNIQUE` and `model_versions.training_job_id`. Those are the same edge stored
twice, and a pair of columns that can disagree is a pair of columns that
eventually will. The unique back-references are kept and the forward copies are
dropped; a job's snapshot is `dataset_snapshots WHERE training_job_id = …`, one
row by construction. The same reasoning `jobs.is_cancelling` uses for not
storing a `cancelling` status.

**`stage_index` outlives the run.** A failed or cancelled job still renders its
rail, stopped where it stopped — *"Stopped at building_graph."* (L1707) — and
`state` alone cannot say where that was, because `failed` is not a position on
the rail. So the index is stored at every stage boundary rather than derived
from the state, and the terminal transition does not reset it.

**A snapshot is written once.** SRS §5.2.9 makes it immutable, so
`graphrec_app` holds `SELECT, INSERT` on `dataset_snapshots` and no `UPDATE`.
That decides the order of operations in the worker rather than merely describing
it: the row is inserted *after* the data is materialised and its digest is
known, because there is no second statement available to fill the digest in
later. `training_metrics` is append-only for the ordinary reason — a per-epoch
measurement that can be revised is not a measurement.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::JobState`, generated from the prototype's stage
#: rail (dc.html L632) plus the three states a rail cannot express. Repeated
#: because a migration cannot import application code, and pinned by
#: `tests/contract/test_migration_literals.py`.
TRAINING_STATES = (
    "queued",
    "waiting_for_resources",
    "preparing_data",
    "building_graph",
    "training",
    "evaluating",
    "indexing_embeddings",
    "registering",
    "cancelling",
    "cancelled",
    "failed",
    "succeeded",
)

#: The three that end a run. Everything else is "active" — which is exactly the
#: set the console lets you cancel from (L1688) and exactly the set the partial
#: unique index covers. One definition, two obligations.
TERMINAL_TRAINING_STATES = ("cancelled", "failed", "succeeded")

#: dc.html L632: the nine positions on the rail. `stage_index` is an offset into
#: this list, so its bound is the list's length and not a state count.
STAGE_RAIL_LENGTH = 9

#: The dialog's option lists, L1677-1678. Constrained in the database as well as
#: in the request schema because they size the work: an unbounded window is an
#: unbounded scan and an unbounded epoch count is an unbounded lease.
INTERACTION_WINDOW_DAYS = (30, 90, 180)
MAX_EPOCHS = (10, 20, 40)

#: The only model family CON-01 admits.
MODEL_TYPES = ("DGSR",)

TABLES = ("training_metrics", "dataset_snapshots", "training_jobs", "models")


def _in_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _in_ints(values: Sequence[int]) -> str:
    return ", ".join(str(value) for value in values)


def upgrade() -> None:
    _models()
    _training_jobs()
    _dataset_snapshots()
    _training_metrics()
    _indexes()
    _rls_and_grants()


def _models() -> None:
    """The named thing a version is a version *of*.

    A tenant has one by default and the schema permits more, because
    `model_versions.version_number` is monotonic *per model* (§Phase 10) and a
    tenant that one day trains a second family needs somewhere for its numbering
    to start again. Phase 9 creates exactly one, lazily, on the first request.
    """
    op.create_table(
        "models",
        sa.Column(
            "model_id",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("model_type", sa.Text(), nullable=False),
        # The hyperparameters a run starts from. Stored rather than read from
        # settings so a version registered a year ago can still say what it was
        # trained with after the default has moved.
        sa.Column(
            "default_config", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_models_tenant_name"),
        sa.CheckConstraint(f"model_type IN ({_in_list(MODEL_TYPES)})", name="ck_models_model_type"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="ck_models_name_length"),
    )


def _training_jobs() -> None:
    """One requested run, and the console's whole view of it.

    `job_id` is the queue row that will actually execute it, one-to-one and
    created in the same transaction. Two tables because they answer different
    questions: `jobs` knows about leases, attempts and workers, and
    `training_jobs` knows about windows, epochs and stages. Merging them would
    put `indexing_embeddings` in the same column an event batch writes
    `running` into — the distinction `graphrec/jobs/states.py` exists to keep.
    """
    op.create_table(
        "training_jobs",
        sa.Column(
            "training_job_id",
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
        sa.Column(
            "job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("models.model_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'queued'::text")),
        # The rail position, kept across the terminal transition. See the module
        # docstring; this column is the whole of "Stopped at building_graph."
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # L1683: "waiting to start" — approved copy, not a status string. The
        # console renders it verbatim beside the rail.
        sa.Column(
            "progress_text",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'waiting to start'::text"),
        ),
        # Nullable: a run requested by a scheduled platform process has no
        # tenant user behind it, and SET NULL rather than CASCADE because
        # deleting the person does not delete the history of the run.
        sa.Column(
            "requested_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenant_users.tenant_user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_ref", sa.Text(), nullable=False),
        sa.Column("interaction_window_days", sa.Integer(), nullable=False),
        sa.Column("max_epochs", sa.Integer(), nullable=False),
        # Both are approved copy reaching a console panel (L1696), never an
        # exception message: a traceback out of a training worker can carry a
        # row of the tenant's data and NR-NF-06 forbids that reaching a body.
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        # L1697. Correlates a tenant's failed run with the server-side log
        # without putting anything from that log in front of them.
        sa.Column("error_reference", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("job_id", name="uq_training_jobs_job"),
        # §17.3: the business identifier, not a header. Scoped to the tenant
        # because two tenants choosing `req-1` have not collided.
        sa.UniqueConstraint("tenant_id", "request_ref", name="uq_training_jobs_request_ref"),
        sa.CheckConstraint(
            f"state IN ({_in_list(TRAINING_STATES)})", name="ck_training_jobs_state"
        ),
        sa.CheckConstraint(
            f"stage_index BETWEEN 0 AND {STAGE_RAIL_LENGTH - 1}",
            name="ck_training_jobs_stage_index",
        ),
        sa.CheckConstraint(
            f"interaction_window_days IN ({_in_ints(INTERACTION_WINDOW_DAYS)})",
            name="ck_training_jobs_window",
        ),
        sa.CheckConstraint(
            f"max_epochs IN ({_in_ints(MAX_EPOCHS)})", name="ck_training_jobs_max_epochs"
        ),
        sa.CheckConstraint(
            "char_length(request_ref) BETWEEN 1 AND 120", name="ck_training_jobs_request_ref_length"
        ),
        # A terminal job is finished, and finished means dated. The same pairing
        # `jobs` makes, for the same reason: a `succeeded` row with no
        # `completed_at` renders an em dash in the console's "Completed at"
        # column and nobody can tell whether it is running.
        sa.CheckConstraint(
            f"(state IN ({_in_list(TERMINAL_TRAINING_STATES)})) = (completed_at IS NOT NULL)",
            name="ck_training_jobs_terminal_dated",
        ),
        # A reason is the price of cancelling (L1717) and of failing. Neither
        # may be set on a run that did neither, which is what stops a cancel
        # reason surviving a retry that then succeeds.
        sa.CheckConstraint(
            "(cancel_reason IS NULL) OR (state IN ('cancelling', 'cancelled'))",
            name="ck_training_jobs_cancel_reason",
        ),
        sa.CheckConstraint(
            "(failure_reason IS NULL) OR (state = 'failed')", name="ck_training_jobs_failure_reason"
        ),
    )


def _dataset_snapshots() -> None:
    """What the run read, frozen.

    `uri` and `checksum` describe an object in the store. The row is the
    *record* of that object and is written after it, so the digest is known at
    insert time; there is no `UPDATE` grant to fill it in with afterwards.

    `cutoff_at` matters as much as `window_days`. A run started at 09:41 reads
    events up to a fixed instant, not up to "now" as each of its nine stages
    reaches for the table — otherwise the graph and the evaluation split would
    disagree about which interactions exist, and the leave-last-out target could
    be an event that arrived during training.
    """
    op.create_table(
        "dataset_snapshots",
        sa.Column(
            "snapshot_id",
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
        sa.Column(
            "training_job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("training_jobs.training_job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("sequence_count", sa.Integer(), nullable=False),
        sa.Column("product_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # SRS §5.2.9: one snapshot per run. This is also what makes the forward
        # `training_jobs.snapshot_id` column redundant rather than convenient.
        sa.UniqueConstraint("training_job_id", name="uq_dataset_snapshots_job"),
        sa.CheckConstraint(
            "sequence_count >= 0 AND product_count >= 0 AND event_count >= 0",
            name="ck_dataset_snapshots_counts",
        ),
        sa.CheckConstraint(
            f"window_days IN ({_in_ints(INTERACTION_WINDOW_DAYS)})",
            name="ck_dataset_snapshots_window",
        ),
        # A digest that is not a digest is worse than none: Phase 10 verifies
        # bundles against this shape and a blank would verify trivially.
        sa.CheckConstraint(
            "checksum ~ '^sha256:[0-9a-f]{64}$'", name="ck_dataset_snapshots_checksum"
        ),
    )


def _training_metrics() -> None:
    """The per-epoch curve `GET /v1/training-jobs/{id}/metrics` returns.

    Long and narrow — one row per epoch per measure — rather than a JSONB column
    per epoch, because the console plots one measure across epochs and the
    registry (Phase 10) compares one measure across versions. Both are a
    `WHERE metric_name = …`, and neither is a JSONB path expression over rows
    that could each hold a different set of keys.
    """
    op.create_table(
        "training_metrics",
        sa.Column(
            "metric_id",
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
        sa.Column(
            "training_job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("training_jobs.training_job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        # `numeric` rather than `double precision`. These reach the console as
        # printed figures (L1701 renders them to three places) and a float that
        # round-trips to 0.20619999999999999 in one panel and 0.2062 in another
        # is a defect report nobody can reproduce.
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "training_job_id", "epoch", "metric_name", name="uq_training_metrics_point"
        ),
        # Epoch 0 is the pre-training measurement, which the popularity baseline
        # occupies (ADR 0024): the curve starts from something rather than from
        # the first trained epoch.
        sa.CheckConstraint("epoch >= 0", name="ck_training_metrics_epoch"),
        sa.CheckConstraint(
            "char_length(metric_name) BETWEEN 1 AND 60", name="ck_training_metrics_name_length"
        ),
    )


def _indexes() -> None:
    # The phase's exit criterion, in one statement. Nine states are active; the
    # index covers exactly those, so a tenant with four hundred finished runs
    # carries four hundred rows that this index does not contain.
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_training_jobs_one_active
            ON training_jobs (tenant_id)
            WHERE state NOT IN ({_in_list(TERMINAL_TRAINING_STATES)})
        """
    )
    # The `/training` table, which is ordered newest first and filtered by state
    # (L1668).
    op.execute(
        "CREATE INDEX ix_training_jobs_tenant_requested "
        "ON training_jobs (tenant_id, requested_at DESC)"
    )
    op.execute("CREATE INDEX ix_dataset_snapshots_tenant ON dataset_snapshots (tenant_id)")
    op.execute(
        "CREATE INDEX ix_training_metrics_job_epoch ON training_metrics (training_job_id, epoch)"
    )
    op.execute("CREATE INDEX ix_models_tenant ON models (tenant_id)")


#: Table -> the privileges `graphrec_app` holds. The two absences are the
#: point and each is argued in its table's docstring.
GRANTS: dict[str, str] = {
    "models": "SELECT, INSERT, UPDATE",
    "training_jobs": "SELECT, INSERT, UPDATE",
    # No UPDATE: SRS §5.2.9 makes a snapshot immutable, and the grant is how
    # that is enforced rather than remembered.
    "dataset_snapshots": "SELECT, INSERT",
    # No UPDATE: a measurement is not revised. A re-run is a new job with its
    # own curve.
    "training_metrics": "SELECT, INSERT",
}


def _rls_and_grants() -> None:
    for table, privileges in GRANTS.items():
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
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")

    # `graphrec_platform` gets nothing. The platform tenant detail's training
    # figure is a usage aggregate (dc.html L1440), which metering already
    # exposes; the runs themselves are the tenant's own and no platform screen
    # renders one.


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
        op.drop_table(table)
