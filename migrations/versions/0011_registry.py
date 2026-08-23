"""The registry: seven states, one active version, and a row that outlives its bytes.

Two tables. `model_versions` carries the lifecycle (ADR 0027) and
`model_evaluation_metrics` carries the numbers the lifecycle is decided by.

**One active version per tenant is a partial unique index**, for the reason
Phase 9's one-active-run rule is: `SELECT` then `INSERT` has a window and an
index does not. Activation is Phase 11, but the constraint lands here with the
table it constrains — a rule added later is a rule that was absent while rows
were being written.

**A version is immutable after registration except for its status.** That is not
a convention: `graphrec_app` holds `UPDATE (status, failure_note, archived_at)`
and nothing else. Metrics, digest, embedding dimension and the training job that
produced them cannot be edited by the application at all, so "this version was
trained on that snapshot and scored these numbers" is a claim the database
enforces rather than one the service remembers to honour.

**Archiving keeps the row and deletes the bytes.** `archived_at` is set,
`artifact_uri` is left pointing at an object that is no longer there, and the
metrics stay queryable — a tenant comparing this month against last month is
comparing numbers, not artifacts. `ck_model_versions_archived_dated` ties the
timestamp to the state so the two cannot drift.

**`split` includes `baseline`.** It is not a data split, and calling it one is a
small abuse of the column name. The alternative is a second table holding four
numbers per version, joined on every detail read, to record the popularity
ranker's score on the *same* held-out rows. The column answers "which evaluation
produced this number", the values are constrained, and the detail endpoint's
three-way comparison (XR-F-10) is one query because of it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::ModelVersionStatus` — D8, ADR 0027. Repeated
#: because a migration cannot import application code, and pinned by
#: `tests/contract/test_migration_literals.py`.
VERSION_STATUSES = (
    "registered",
    "archived",
    "eligible",
    "retired",
    "rejected",
    "failed_deployment",
    "active",
)

#: The states from which `:archive` is allowed (BACKEND_PLAN L1168). Not a
#: constraint — the rollback-target rule makes `retired` conditional and a check
#: constraint cannot see another row — but the vocabulary is pinned here so the
#: service and the schema name the same set.
ARCHIVABLE_STATUSES = ("registered", "rejected", "retired")

#: Which evaluation produced a number. `test` is the held-out split a version is
#: judged on, `validation` is the per-epoch split the training loop early-stops
#: on, and `baseline` is the popularity ranker over the same held-out rows.
METRIC_SPLITS = ("validation", "test", "baseline")

TABLES = ("model_evaluation_metrics", "model_versions")


def _in_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    _model_versions()
    _model_evaluation_metrics()
    _indexes()
    _rls_and_grants()


def _model_versions() -> None:
    """One trained artifact, its provenance, and where it is in its life."""
    op.create_table(
        "model_versions",
        sa.Column(
            "model_version_id",
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
            "model_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("models.model_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Monotonic per model, not per tenant: a tenant that one day trains a
        # second family gets "version 1" again rather than "version 38".
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        # `RESTRICT`, not `CASCADE`. A version is the record of what a training
        # run produced; deleting the run must not silently delete the artifact
        # a tenant may be serving from.
        sa.Column(
            "training_job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("training_jobs.training_job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("dataset_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        # The digest of the bundle, not of the manifest. The manifest carries a
        # copy of it and the load path checks both, because a manifest that
        # vouched for itself would vouch for anything.
        sa.Column("artifact_digest", sa.Text(), nullable=False),
        # What the bundle expects its inputs to look like. Phase 11 refuses a
        # bundle whose contract does not match the features it can supply, which
        # is the failure the prototype's `v-4` panel narrates (L704).
        sa.Column(
            "feature_contract", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        # A denormalised copy of the headline four, for the list page. The rows
        # in `model_evaluation_metrics` are the record; this is the column the
        # `/models` table sorts and renders without a join per row.
        sa.Column("metrics", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Why this version will not serve — the floor's verdict on `rejected`,
        # the loader's reason on `failed_deployment`. Approved copy, resolved
        # from a code, never an exception string (NR-NF-06).
        sa.Column("failure_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "model_id", "version_number", name="uq_model_versions_number"
        ),
        # One version per training run. A second registration of the same run is
        # a retry of the `registering` stage, and it must find the row it wrote
        # rather than write a second one — the same obligation `dataset_snapshots`
        # has for the same reason.
        sa.UniqueConstraint("training_job_id", name="uq_model_versions_job"),
        sa.CheckConstraint(
            f"status IN ({_in_list(VERSION_STATUSES)})", name="ck_model_versions_status"
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_model_versions_number_positive"),
        sa.CheckConstraint("embedding_dim BETWEEN 1 AND 4096", name="ck_model_versions_dim"),
        sa.CheckConstraint(
            "artifact_digest ~ '^sha256:[0-9a-f]{64}$'", name="ck_model_versions_digest"
        ),
        # `archived` is the only state that destroys anything, so it is the only
        # one that may carry the timestamp saying when.
        sa.CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="ck_model_versions_archived_dated",
        ),
        # A note explains a refusal. A version that is serving has nothing to
        # explain, and a stale note beside an active version is worse than none.
        sa.CheckConstraint(
            "(failure_note IS NULL) OR (status IN ('rejected', 'failed_deployment', 'archived'))",
            name="ck_model_versions_failure_note",
        ),
    )


def _model_evaluation_metrics() -> None:
    """The numbers behind the verdict, one row each.

    Append-only by absent grant, for the reason `training_metrics` is: a measure
    that can be revised after the decision it justified is not evidence.
    """
    op.create_table(
        "model_evaluation_metrics",
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
            "model_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        # `numeric`, not `double precision`. A metric that renders differently
        # depending on which process read it is a metric a tenant will ask about.
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "model_version_id", "split", "metric_name", name="uq_model_evaluation_metrics_point"
        ),
        sa.CheckConstraint(
            f"split IN ({_in_list(METRIC_SPLITS)})", name="ck_model_evaluation_metrics_split"
        ),
        sa.CheckConstraint(
            "char_length(metric_name) BETWEEN 1 AND 64",
            name="ck_model_evaluation_metrics_name_length",
        ),
    )


def _indexes() -> None:
    # The phase's rule. Partial on `tenant_id` over the single state that may
    # serve: two activations racing produce one active version and one refusal,
    # and no lock is held across the check.
    op.execute(
        "CREATE UNIQUE INDEX uq_model_versions_one_active "
        "ON model_versions (tenant_id) WHERE status = 'active'"
    )
    # The `/models` table: a tenant's versions, newest first, optionally by
    # status. One index serves both because the filter is the leading column
    # after the tenant.
    op.create_index(
        "ix_model_versions_tenant_status",
        "model_versions",
        ["tenant_id", "status", sa.text("version_number DESC")],
    )
    op.create_index(
        "ix_model_evaluation_metrics_version",
        "model_evaluation_metrics",
        ["model_version_id", "split"],
    )


GRANTS: dict[str, str] = {
    # Column-level `UPDATE`. Everything else about a version is fixed at
    # registration, and the grant is what makes "immutable except status" true
    # rather than aspirational — a service that tried to correct a digest would
    # be refused by PostgreSQL, not by a code review.
    "model_versions": "SELECT, INSERT, UPDATE (status, failure_note, archived_at)",
    "model_evaluation_metrics": "SELECT, INSERT",
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

    # `graphrec_platform` reads the count of active versions for the platform
    # status page (dc.html L1440) and nothing else, so it gets `SELECT` on the
    # lifecycle columns only. Not the digest, not the metrics: what a tenant's
    # model scores is the tenant's business.
    op.execute(
        "GRANT SELECT (model_version_id, tenant_id, model_id, version_number, status, created_at) "
        "ON model_versions TO graphrec_platform"
    )
    op.execute(
        """
        CREATE POLICY model_versions_platform_read ON model_versions
            FOR SELECT TO graphrec_platform
            USING (true)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS model_versions_platform_read ON model_versions")
    op.execute("REVOKE ALL ON model_versions FROM graphrec_platform")
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
        op.drop_table(table)
