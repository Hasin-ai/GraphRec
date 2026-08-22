"""Ingestion: what a tenant sends us, and what we made of it.

Five tables, and the shape of the phase is in how they divide.

`customers` and `interaction_events` are the **facts** — what happened, in the
tenant's own vocabulary. `submissions` and `submission_errors` are the
**account** of how those facts arrived: how many were received, how many were
applied, and which ones were not, with a reason a tenant can act on.

They are separate because they have different lifetimes and different rules. An
interaction event is history: once written it is never corrected, so
`graphrec_app` gets `SELECT, INSERT` on it and nothing else. A submission is a
running report: it is updated as the worker progresses, and it stops changing
when it completes.

`ingest_staging_items` is neither. It is scratch space that exists so that a
batch is validated in bounded memory and then applied by **one** statement per
target table, rather than five thousand statements interleaved with five
thousand validations. Rows arrive there in chunks and leave in the same
transaction that merges them, so the table is empty between submissions.

Three properties this migration is responsible for:

* **The same `event_id` twice yields one row.** `uq_interaction_events_tenant_external`
  is what makes that true, and the merge's `ON CONFLICT DO NOTHING` is what
  turns it into a *success* rather than an error (dc.html L1175).
* **A repeated submission identifier is not applied twice.**
  `uq_submissions_tenant_kind_reference` — "Repeating the same identifier is
  confirmed as a duplicate rather than applied twice" (L1355).
* **Raw payloads are never echoed back.** `submission_errors.reason` is bounded
  and holds approved copy, not the item that failed (L1391).

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::EventType`, generated from the prototype's event
#: form (dc.html L1370). Repeated because a migration cannot import application
#: code, and pinned by `tests/contract/test_migration_literals.py`.
EVENT_TYPES = ("view", "add_to_cart", "purchase", "remove_from_cart")

#: `SubmissionKind`. The console labels these "product sync" and "event batch";
#: the wire and the column carry the machine names (D12).
SUBMISSION_KINDS = ("product_sync", "event_batch")

#: `SubmissionStatus` — the four stages the submission page's rail renders
#: (L1381: received / validating / applying / completed), plus the terminal
#: failure the third seeded submission is in (L691).
SUBMISSION_STATUSES = ("received", "validating", "applying", "completed", "failed")

#: Ordered so that a table's dependents are dropped before it.
TABLES = (
    "ingest_staging_items",
    "submission_errors",
    "interaction_events",
    "submissions",
    "customers",
)


def upgrade() -> None:
    _customers()
    _submissions()
    _interaction_events()
    _submission_errors()
    _staging()
    _indexes()
    _rls_and_grants()


def _customers() -> None:
    """A person, in the tenant's own vocabulary and nobody else's.

    There is no email column, no name and no address. A customer here is an
    identifier the tenant already uses and a record of when we last saw it —
    everything the recommender needs, and nothing that makes this table worth
    stealing. The SRS calls for interaction data, not for a copy of the
    tenant's CRM.
    """
    op.create_table(
        "customers",
        sa.Column(
            "customer_id",
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
        sa.Column("external_customer_id", sa.Text(), nullable=False),
        # Maintained by the merge, and the reason `customers` carries an UPDATE
        # grant while `interaction_events` does not: this is a derived summary
        # of the events, not a fact of its own.
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint(
            "tenant_id", "external_customer_id", name="uq_customers_tenant_external"
        ),
        sa.CheckConstraint(
            "char_length(external_customer_id) BETWEEN 1 AND 120",
            name="ck_customers_external_id_length",
        ),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name="ck_customers_seen_order"),
    )


def _submissions() -> None:
    """The account of one arrival.

    `raw_payload` is the collection as it was submitted, and it is **cleared**
    when the submission finishes. Keeping it would mean retaining a copy of
    every event a tenant ever sent, indefinitely, in a column no product feature
    reads. Clearing it is not a nicety: the payload is the tenant's raw business
    data and the shortest-lived copy of it is the safest one.
    """
    op.create_table(
        "submissions",
        sa.Column(
            "submission_id",
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
        sa.Column("kind", sa.Text(), nullable=False),
        # The identifier the *tenant* chose: a `sync_id` (L1357) or a `batch_id`
        # (L1626). It is the idempotency key, which is why it is unique and why
        # the console calls it "Submitted identifier" (L1390).
        sa.Column("external_reference", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'received'::text")),
        # The five numbers the submission page renders as stats (L1389). Held as
        # columns rather than counted on read: `interaction_events` has no
        # `submission_id`-shaped answer for "skipped", because a skipped item
        # never became a row.
        sa.Column("received_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # `SET NULL`, not `CASCADE`: a job row swept away by retention must not
        # take the tenant's record of what they submitted with it.
        sa.Column(
            "job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("raw_payload", pg.JSONB(), nullable=True),
        # Options that belong to the submission rather than to any item — the
        # sync form's Mode control (L1357) is the only one so far.
        sa.Column("options", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
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
        # Kind is part of the key. A synchronization identifier and a batch
        # identifier are separate namespaces in the prototype — two different
        # forms, two different labels — and colliding them would reject a batch
        # because an unrelated sync happened to reuse the string.
        sa.UniqueConstraint(
            "tenant_id", "kind", "external_reference", name="uq_submissions_tenant_kind_reference"
        ),
        sa.CheckConstraint("kind IN " + str(SUBMISSION_KINDS), name="ck_submissions_kind"),
        sa.CheckConstraint("status IN " + str(SUBMISSION_STATUSES), name="ck_submissions_status"),
        sa.CheckConstraint(
            "char_length(external_reference) BETWEEN 1 AND 120",
            name="ck_submissions_reference_length",
        ),
        sa.CheckConstraint(
            "received_count >= 0 AND accepted_count >= 0 AND updated_count >= 0 "
            "AND skipped_count >= 0 AND failed_count >= 0 AND error_count >= 0",
            name="ck_submissions_counts_non_negative",
        ),
        # Terminal exactly when it is finished. Without this a submission can
        # sit at `completed` with no completion time, and the console's
        # "Processing finished." (L1386) would have nothing to date.
        sa.CheckConstraint(
            "(status IN ('completed', 'failed')) = (completed_at IS NOT NULL)",
            name="ck_submissions_terminal_has_time",
        ),
        # A failure code is meaningless on a submission that did not fail, and a
        # failed submission with no code gives the console nothing to render.
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)",
            name="ck_submissions_failed_has_code",
        ),
    )


def _interaction_events() -> None:
    """History. Written once, never corrected.

    `external_event_id` is the idempotency key (L1622) and the unique constraint
    below is the whole of "the same event twice yields one row". The *second*
    half of that promise — that both submissions are told they succeeded — is
    the merge's `ON CONFLICT DO NOTHING` counting the conflict as a duplicate
    rather than a failure.
    """
    op.create_table(
        "interaction_events",
        sa.Column(
            "event_id",
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
        sa.Column("external_event_id", sa.Text(), nullable=False),
        sa.Column(
            "customer_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.customer_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        # The tenant's clock, not ours. `received_at` is ours, and the two are
        # kept apart because a training split by `occurred_at` must reflect when
        # the interaction happened, not when the batch was uploaded.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(12, 2), nullable=True),
        sa.Column("context", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Which arrival this came from. Nullable because a single `POST /v1/events`
        # is not a submission and has no report to belong to.
        sa.Column(
            "submission_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("submissions.submission_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id", "external_event_id", name="uq_interaction_events_tenant_external"
        ),
        sa.CheckConstraint(
            "char_length(external_event_id) BETWEEN 1 AND 120",
            name="ck_interaction_events_external_id_length",
        ),
        sa.CheckConstraint("event_type IN " + str(EVENT_TYPES), name="ck_interaction_events_type"),
        sa.CheckConstraint(
            "value IS NULL OR value >= 0", name="ck_interaction_events_value_non_negative"
        ),
    )


def _submission_errors() -> None:
    """Capped samples, and only ever a safe reason.

    "Errors identify the offending item and a safe reason. Raw payloads are
    never echoed back." (L1391). `reason` is bounded at 300 characters, which is
    long enough for every string in the approved item-reason vocabulary and far
    too short to smuggle a payload through.

    Capped because a batch of 5,000 items can fail 5,000 times and a tenant
    reading a screen needs the first hundred, not all of them. The submission's
    `failed_count` remains exact; `error_count` is how many samples were kept.
    """
    op.create_table(
        "submission_errors",
        sa.Column(
            "submission_error_id",
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
            "submission_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("submissions.submission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The position in the submitted collection, which is what makes the
        # samples renderable in the order the tenant sent them.
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # The tenant's own identifier for the offending item — `SKU-9004`,
        # `ev-33810`, or the literal `batch` when the whole collection failed
        # (L689-L691).
        sa.Column("item_reference", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "submission_id", "ordinal", name="uq_submission_errors_submission_ordinal"
        ),
        sa.CheckConstraint(
            "char_length(item_reference) BETWEEN 1 AND 200",
            name="ck_submission_errors_reference_length",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 300", name="ck_submission_errors_reason_length"
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_submission_errors_ordinal_non_negative"),
    )


def _staging() -> None:
    """Scratch space, so that validation and application are separable.

    The alternative is to validate and apply item by item, which means 5,000
    round trips and a half-applied batch if the four-thousandth one fails. With
    a staging table the handler validates in chunks — bounded memory, whatever
    the bound turns out to be — and then applies the whole validated set with
    one statement per target table, inside one transaction.

    Rows are inserted and deleted in that same transaction, so this table is
    empty whenever nobody is mid-merge. It carries a `DELETE` grant for exactly
    that reason, and it is the only ingestion table that does.
    """
    op.create_table(
        "ingest_staging_items",
        sa.Column(
            "staging_item_id",
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
            "submission_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("submissions.submission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # The item after validation and normalisation, not as submitted. What
        # the merge reads is a shape the merge itself defines.
        sa.Column("item", pg.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "submission_id", "ordinal", name="uq_ingest_staging_items_submission_ordinal"
        ),
    )


def _indexes() -> None:
    for table in TABLES:
        op.execute(f"CREATE INDEX ix_{table}_tenant_id ON {table} (tenant_id)")

    # The sequence read. Training builds a per-customer ordered history, and
    # this is the index that makes it a range scan rather than a sort of the
    # tenant's entire event table.
    op.execute(
        "CREATE INDEX ix_interaction_events_customer_sequence "
        "ON interaction_events (tenant_id, customer_id, occurred_at)"
    )
    # The dataset-snapshot cut: everything a tenant sent within a window.
    op.execute(
        "CREATE INDEX ix_interaction_events_tenant_occurred "
        "ON interaction_events (tenant_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_interaction_events_tenant_product "
        "ON interaction_events (tenant_id, product_id)"
    )
    # What the submission page reads, and the alias route's lookup.
    op.execute(
        "CREATE INDEX ix_submissions_tenant_created ON submissions (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_submission_errors_submission ON submission_errors (submission_id, ordinal)"
    )
    op.execute(
        "CREATE INDEX ix_ingest_staging_items_submission "
        "ON ingest_staging_items (submission_id, ordinal)"
    )


#: Table -> the privileges `graphrec_app` holds on it. The absences are the
#: point, and each one is a decision recorded in the table's own docstring.
GRANTS: dict[str, str] = {
    "customers": "SELECT, INSERT, UPDATE",
    # No UPDATE and no DELETE. An interaction event is a historical fact; a
    # correction to one is a different event, not an edit of this one. The same
    # reasoning the BUILD_PROMPT applies to `usage_events` and `audit_logs`.
    "interaction_events": "SELECT, INSERT",
    "submissions": "SELECT, INSERT, UPDATE",
    # No UPDATE: a reported failure is not revised. If a later run disagrees it
    # is a later submission, with its own errors.
    "submission_errors": "SELECT, INSERT",
    "ingest_staging_items": "SELECT, INSERT, DELETE",
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

    # `graphrec_platform` gets nothing here, as it gets nothing on `products`.
    # The tenant counts the platform console shows come from metering, which is
    # an aggregate the platform realm is entitled to; the events themselves are
    # the tenant's own business data and there is no platform screen for them.


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
        op.drop_table(table)
