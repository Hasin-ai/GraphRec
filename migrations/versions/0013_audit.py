"""Audit: the history nobody can revise, and the failures nobody can attribute.

Two tables, and — as in Phase 9's metering — the division between them is the
design rather than a filing decision.

`audit_logs` is the **record of intent**: someone asked for something and the
system agreed or refused. Eight actions, four actors, four outcomes. It answers
"who changed this, and when" for a tenant looking at their own account and for a
platform operator looking across the installation. It is append-only in the
strongest sense available to us: `graphrec_app` and `graphrec_platform` are
granted `SELECT, INSERT` and nothing else, so a row cannot be edited by
application code, by a handler that means well, or by anyone holding either
role's password. A history that can be rewritten is not a history.

`security_events` is the **record of trouble**: a severity, an area, a summary
and a reference. It is a separate table and not a severity column on the one
above because the two are read by different people for different reasons
(BACKEND_PLAN L1617). `/admin/audit`'s Failures tab wants "what is going wrong,
how badly, and where", ordered by severity over a window; the audit tab wants
"what did this actor do". Folding them together would give every audit row four
columns it never uses and force the failures view to filter the history to find
the failures.

**`tenant_id` is nullable in both, and that nullability is load-bearing.** A
platform operator suspending a tenant acts *on* a tenant without acting *as*
one; a sign-in refused for an address that matches no user cannot name a tenant
without inventing one. So the column means "the tenant this concerns, if it
concerns one", and the RLS policies below read it that way:

* the tenant policy makes a `NULL` row invisible to every tenant — a tenant's
  audit page can never show a platform action, which is the phase's stated exit
  criterion and SRS §5.2.16's requirement for tenant-facing views specifically;
* the tenant policy nevertheless *accepts* a `NULL` on insert, because the
  application role is the one that has to record an unattributable access
  refusal, and a refusal we cannot store is a refusal nobody will investigate.

Writing something you can never read back is unusual and deliberate. The
alternative — refusing the write — loses exactly the events an attacker most
wants lost.

The last thing here is not a table. `/admin/status` reports availability across
the installation, and availability is computed from `recommendation_requests`.
The platform role is granted five columns of that table: the tenant, when, how
long, whether it was served and whether a fallback was applied. Not the
customer, not the session, not the request or its results. UC-29's "excluding
private event payloads" is enforced by the absent grant rather than by every
future query remembering to exclude them.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
PLATFORM_ROLE = "graphrec_platform"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::AuditActor`. Repeated because a migration cannot
#: import application code; pinned by `tests/contract/test_migration_literals.py`.
ACTOR_TYPES = (
    "tenant_user",
    "tenant_application",
    "system_process",
    "platform_administrator",
)

#: `AuditAction`. Eight, and the set is closed: an action that is not one of
#: these is a mis-spelling, and a mis-spelled action is a row the console's
#: filter will never show anyone.
ACTIONS = (
    "credential",
    "training",
    "activation",
    "rollback",
    "quota",
    "tenant",
    "access",
    "security",
)

#: `AuditOutcome`. `denied` and `cancelled` are distinct from `failed` on
#: purpose: a refusal is not a fault, and a fault is not a withdrawal.
OUTCOMES = ("cancelled", "denied", "failed", "succeeded")

#: `Severity`.
SEVERITIES = ("info", "warning", "error", "critical")

#: `FailureArea`.
AREAS = ("serving", "ingestion", "training", "activation", "capacity")

TABLES = ("security_events", "audit_logs")


def upgrade() -> None:
    _audit_logs()
    _security_events()
    _indexes()
    _rls_and_grants()
    _platform_reads()


def _audit_logs() -> None:
    """One decision, as it was taken, forever.

    `details` is `jsonb` and it is the only free-form column in either table,
    which makes it the only place a secret could be written by accident. The
    schema cannot stop that; `graphrec/domain/audit/record.py` refuses a key
    from a denylist and the tenant-facing read never returns the column at all,
    so a mistake here costs a platform operator seeing something they should not
    rather than a tenant seeing it.

    `correlation_ref` is the request id. It is what turns two rows into one
    story — the credential that was rotated and the access that used it — and it
    is the reason a support conversation does not have to start from timestamps.
    """
    op.create_table(
        "audit_logs",
        sa.Column(
            "audit_log_id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Nullable, and `SET NULL` rather than `CASCADE` on the way out. A
        # deleted tenant's history is exactly the history an investigation
        # needs; erasing it with the tenant would make deletion a way to erase
        # what was done. The rows survive, unattributed.
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        # Free text, not a foreign key: the actor may be a tenant user, a
        # platform user, an API credential or a worker, and those live in four
        # different tables. A constraint here would have to name all four and
        # would break the day a fifth kind of actor appears.
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_ref", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("correlation_ref", sa.Text(), nullable=True),
        sa.Column(
            "details",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_type IN " + _sql_tuple(ACTOR_TYPES), name="ck_audit_logs_actor_type"
        ),
        sa.CheckConstraint("action IN " + _sql_tuple(ACTIONS), name="ck_audit_logs_action"),
        sa.CheckConstraint("outcome IN " + _sql_tuple(OUTCOMES), name="ck_audit_logs_outcome"),
        # A row that names no resource type says nothing useful. The *ref* may
        # be absent — a refused sign-in has no id to point at — but the kind of
        # thing acted on is always known.
        sa.CheckConstraint(
            "length(resource_type) BETWEEN 1 AND 64", name="ck_audit_logs_resource_type_length"
        ),
    )


def _security_events() -> None:
    """What went wrong, how badly, and where — with nothing that says to whom.

    `summary` is prose written by the system, never by a caller and never
    interpolated from a payload. The Failures tab renders it directly, and
    anything a tenant supplied could carry another tenant's data into a platform
    operator's screen or an operator's screen into a log aggregator.

    `reference` is the short, opaque handle the console shows so that a person
    reading the screen and a person reading the logs can agree on which failure
    they mean. It is the same construction `/v1/service-status/errors` uses.
    """
    op.create_table(
        "security_events",
        sa.Column(
            "security_event_id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("area", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN " + _sql_tuple(SEVERITIES), name="ck_security_events_severity"
        ),
        sa.CheckConstraint("area IN " + _sql_tuple(AREAS), name="ck_security_events_area"),
        sa.CheckConstraint(
            "length(summary) BETWEEN 1 AND 500", name="ck_security_events_summary_length"
        ),
    )


def _indexes() -> None:
    """Both reads are "newest first, over a window", so both indexes descend.

    An ascending index would serve these queries by scanning to the end and
    walking backwards, which is fine on a young table and not fine on the one
    table in the system that is never pruned.
    """
    # The tenant's own page, and the platform tab filtered to one tenant.
    op.create_index(
        "ix_audit_logs_tenant_occurred",
        "audit_logs",
        ["tenant_id", sa.text("occurred_at DESC")],
    )
    # The same page filtered by action, which is the only other filter the
    # console offers (BACKEND_PLAN L1204).
    op.create_index(
        "ix_audit_logs_action_occurred",
        "audit_logs",
        ["action", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_security_events_occurred",
        "security_events",
        [sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_security_events_severity_occurred",
        "security_events",
        ["severity", sa.text("occurred_at DESC")],
    )


def _rls_and_grants() -> None:
    """Two policies per table, because reading and writing differ here.

    Everywhere else in this schema the tenant policy is one `FOR ALL` with
    matching `USING` and `WITH CHECK`, because everywhere else a tenant may read
    exactly what it may write. Audit is the exception: the application role must
    be able to record an event it cannot attribute — a sign-in refused for an
    unknown address, a credential presented by nobody — and must never be able
    to read one back. Split policies say that in the schema instead of leaving
    it to a query to remember.
    """
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_read ON {table}
                FOR SELECT TO {APP_ROLE}
                USING (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_write ON {table}
                FOR INSERT TO {APP_ROLE}
                WITH CHECK (
                    tenant_id = current_setting('{TENANT_GUC}', true)::uuid
                    OR tenant_id IS NULL
                )
            """
        )
        # The platform realm never sets `app.tenant_id` — tenant is a filter
        # there, never a scope — so it needs its own policy or RLS denies it
        # everything.
        op.execute(
            f"""
            CREATE POLICY {table}_platform_read ON {table}
                FOR SELECT TO {PLATFORM_ROLE} USING (true)
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_platform_write ON {table}
                FOR INSERT TO {PLATFORM_ROLE} WITH CHECK (true)
            """
        )

        # The exit criterion of this phase, expressed as an absence: no UPDATE
        # and no DELETE on either table, for either role, ever.
        # `tests/audit/test_append_only.py` asserts all four raise.
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {PLATFORM_ROLE}")


def _platform_reads() -> None:
    """What `/admin/status` is allowed to know about serving.

    Availability across the installation is a ratio of served requests to
    refused ones, and computing it needs the request rows. Five columns of them:
    which tenant, when, how long it took, whether it succeeded, and whether a
    fallback was applied. Not `customer_id`, not `session_hash`, not
    `external_request_id`, and nothing at all from `recommendation_results`.

    UC-29 and L1438 require that private event payloads stay out of every
    platform view. Enforcing that with an absent grant rather than with a
    careful `SELECT` list means a future query cannot get it wrong: the column
    is not readable by the role the platform console connects as.
    """
    op.execute(
        "GRANT SELECT (request_id, tenant_id, requested_at, latency_ms, status, "
        f"fallback_applied) ON recommendation_requests TO {PLATFORM_ROLE}"
    )
    op.execute(
        f"""
        CREATE POLICY recommendation_requests_platform_read ON recommendation_requests
            FOR SELECT TO {PLATFORM_ROLE} USING (true)
        """
    )
    # Ready-versus-desired per tenant is on `model_deployments`, which Phase 11
    # already granted. The replica rows themselves are not granted: they name
    # container references, which are an operational detail of one node and not
    # something a console needs to render a capacity number.


def _sql_tuple(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS recommendation_requests_platform_read ON recommendation_requests"
    )
    op.execute(f"REVOKE ALL ON recommendation_requests FROM {PLATFORM_ROLE}")
    for table in TABLES:
        for policy in ("tenant_read", "tenant_write", "platform_read", "platform_write"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON {table} FROM {PLATFORM_ROLE}")
        op.drop_table(table)
