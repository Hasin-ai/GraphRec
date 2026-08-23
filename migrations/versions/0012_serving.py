"""Serving: what is meant to run, what is actually running, and what was asked.

Eight tables in two groups. The first four are the deployment — desired state,
observed state, the history of every attempt to change it. The last four are the
data plane's record of what it answered.

**Zero or one deployment per tenant** (SRS §5.2.11) is `UNIQUE (tenant_id)` on
`model_deployments`, a plain unique constraint rather than a partial index
because there is no state in which a second row would be legitimate.

**Desired and active are two columns, not one.** `desired_version_id` is what a
tenant asked for; `active_version_id` is what is answering requests. ER-F-06 is
the reason they are separate: a failed activation moves `desired` and leaves
`active` alone, so "the previous version keeps serving" is readable from the row
rather than inferred from the absence of an error. `ck_model_deployments_active_
needs_a_state` ties the second to the state, so a deployment cannot claim to be
`available` with nothing active.

**`epoch` is a counter, not a timestamp.** It is bumped on every change to
desired state, and an inference process polls it to notice drift. A timestamp
would work until two changes landed inside one clock tick, and the failure then
is silent: a replica serving last week's version and reporting itself healthy.

**`deployment_revisions` is where failures live.** BACKEND_PLAN L845 calls it
"the rollback and failed-activation history". A tenant asking why version 8 is
not serving is asking to read this table, so a failed attempt is a row with a
`failure_reason` and not an absence.

**`serving_replicas.ready` is a column beside `status`, not a status value.** A
replica can be `running` and not yet able to answer. Collapsing the two would
make "desired 3 / ready 3" true the moment three containers existed, which is
the exact number the console colours amber (dc.html L1835) and therefore the
exact number that must not lie.

**The data-plane tables are append-only by absent grant**, as ingestion's and
metering's are. `recommendation_requests` gets one narrow `UPDATE` — the
asynchronous write of `latency_ms` and `status` happens after the response has
gone out (BACKEND_PLAN L693), so the row is inserted before the numbers exist.

**`session_hash`, never `session_id`.** The tenant's session identifier is their
customer's, and storing it would put a third party's tracking key in this
database for the sake of a column nothing queries by. The hash supports the
`CHECK` that one of the two identifiers is present, which is what SRS §5.2.12
actually requires.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::DeploymentState` — the console's `deploy` badge
#: group (dc.html L1827). Pinned by `tests/contract/test_migration_literals.py`.
DEPLOYMENT_STATES = (
    "stopped",
    "pending",
    "progressing",
    "degraded",
    "rolling_back",
    "available",
)

#: `graphrec/serving/states.py::ReplicaStatus`.
REPLICA_STATUSES = ("starting", "running", "stopping", "stopped", "failed")

#: `graphrec/serving/states.py::RevisionStatus`.
REVISION_STATUSES = ("pending", "succeeded", "failed")

#: `graphrec/serving/states.py::RevisionKind`.
REVISION_KINDS = ("activation", "rollback", "stop")

#: `graphrec/serving/states.py::Strategy` — ER-F-05.
STRATEGIES = ("personalized", "session", "cold_start", "fallback")

#: `graphrec/serving/states.py::CandidateSource`.
CANDIDATE_SOURCES = ("graph", "popularity", "category", "session")

#: `graphrec/serving/states.py::RequestStatus`.
REQUEST_STATUSES = ("served", "degraded", "refused")

#: `graphrec/serving/states.py::ServingErrorClass`. The closed set
#: `/v1/service-status/errors` renders (dc.html L1842) — a class is a bucket,
#: and a bucket cannot carry a payload.
ERROR_CLASSES = ("unavailable", "validation", "internal")

#: `graphrec/serving/states.py::FeedbackType`.
FEEDBACK_TYPES = ("impression", "click", "conversion")

#: `graphrec/common/enums.py::AuditActor` — who activated a version. The same
#: four values `audit_logs` will carry in Phase 12, spelled here first because
#: activation is auditable before the audit table exists.
ACTOR_TYPES = (
    "tenant_user",
    "tenant_application",
    "system_process",
    "platform_administrator",
)

#: Ceilings, not policy. The plan decides a tenant's real limit; these stop a
#: bug from asking Compose for four thousand containers.
MAX_REPLICAS = 32

TABLES = (
    "recommendation_feedback",
    "recommendation_impressions",
    "recommendation_results",
    "recommendation_requests",
    "model_activation_history",
    "serving_replicas",
    "deployment_revisions",
    "model_deployments",
)


def _in_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    _model_deployments()
    _deployment_revisions()
    _serving_replicas()
    _model_activation_history()
    _recommendation_requests()
    _recommendation_results()
    _recommendation_impressions()
    _recommendation_feedback()
    _indexes()
    _rls_and_grants()


def _model_deployments() -> None:
    """One row per tenant that has ever served, or intends to."""
    op.create_table(
        "model_deployments",
        sa.Column(
            "deployment_id",
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
        # `RESTRICT` on both: a version that a deployment points at is a version
        # that must not vanish from under it. Archiving is what removes a
        # version from service, and archiving refuses while it is active.
        sa.Column(
            "desired_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "active_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'stopped'")),
        sa.Column("desired_replicas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ready_replicas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # XR-F-08's bounds, which `GET /v1/deployment/autoscaling` renders. Held
        # on the deployment rather than derived from the plan on each read, so
        # a plan change does not retroactively rewrite what the reconciler was
        # converging toward while it was converging.
        sa.Column("min_replicas", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("max_replicas", sa.Integer(), nullable=False, server_default=sa.text("1")),
        #: Requests per second per replica the autoscaler aims at.
        sa.Column(
            "target_rps_per_replica",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("50"),
        ),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=True),
        # Bumped on every change to desired state. `bigint` because it is never
        # reset and a tenant retrained hourly for a decade is still nowhere
        # near, whereas `int` invites someone to reason about when it wraps.
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # SRS §5.2.11. Not a partial index: there is no state in which a second
        # deployment for one tenant would be right.
        sa.UniqueConstraint("tenant_id", name="uq_model_deployments_tenant"),
        sa.CheckConstraint(
            f"state IN ({_in_list(DEPLOYMENT_STATES)})", name="ck_model_deployments_state"
        ),
        sa.CheckConstraint(
            f"desired_replicas BETWEEN 0 AND {MAX_REPLICAS}",
            name="ck_model_deployments_desired_replicas",
        ),
        sa.CheckConstraint(
            f"ready_replicas BETWEEN 0 AND {MAX_REPLICAS}",
            name="ck_model_deployments_ready_replicas",
        ),
        sa.CheckConstraint(
            f"min_replicas BETWEEN 0 AND {MAX_REPLICAS} AND max_replicas >= min_replicas "
            f"AND max_replicas <= {MAX_REPLICAS}",
            name="ck_model_deployments_replica_bounds",
        ),
        sa.CheckConstraint(
            "target_rps_per_replica > 0", name="ck_model_deployments_target_rps_positive"
        ),
        # A deployment that says it is available must have something serving,
        # and one with nothing serving cannot be available. The other five
        # states are all legitimate with `active_version_id IS NULL` — including
        # `degraded`, which is what a tenant whose only version failed to load
        # looks like.
        sa.CheckConstraint(
            "(state = 'available') <= (active_version_id IS NOT NULL)",
            name="ck_model_deployments_available_needs_active",
        ),
    )


def _deployment_revisions() -> None:
    """Every attempt to change what is serving, successful or not."""
    op.create_table(
        "deployment_revisions",
        sa.Column(
            "revision_id",
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
            "deployment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_deployments.deployment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "from_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "to_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        # Who asked. Carried on the *attempt* rather than only on the history,
        # because the swap happens in the reconciler minutes later and an
        # activation attributed to `system_process` would lose the one fact
        # ER-F-11 wants. No foreign key, for the reason
        # `model_activation_history` has none.
        sa.Column("requested_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_type", sa.Text(), nullable=False),
        #: The tenant's own words for why, when they gave any.
        sa.Column("reason", sa.Text(), nullable=True),
        #: Approved copy, resolved from the catalogue. Never an exception string
        #: — the same rule the training rail's `failure_reason` follows.
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("deployment_id", "revision", name="uq_deployment_revisions_number"),
        sa.CheckConstraint(
            f"status IN ({_in_list(REVISION_STATUSES)})", name="ck_deployment_revisions_status"
        ),
        sa.CheckConstraint(
            f"kind IN ({_in_list(REVISION_KINDS)})", name="ck_deployment_revisions_kind"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_deployment_revisions_number_positive"),
        sa.CheckConstraint(
            f"requested_by_type IN ({_in_list(ACTOR_TYPES)})",
            name="ck_deployment_revisions_actor",
        ),
        # Settled means dated, both ways. The same biconditional the job queue
        # and the training rail use, for the same reason: a "succeeded" row with
        # no completion time is a row nobody can order by.
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed')) = (completed_at IS NOT NULL)",
            name="ck_deployment_revisions_settled_dated",
        ),
        # A failure explains itself and a success does not pretend to have.
        sa.CheckConstraint(
            "(failure_reason IS NULL) OR (status = 'failed')",
            name="ck_deployment_revisions_failure_reason",
        ),
    )


def _serving_replicas() -> None:
    """One row per serving process, as the driver reports it."""
    op.create_table(
        "serving_replicas",
        sa.Column(
            "replica_id",
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
            "deployment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_deployments.deployment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The driver's own name for the process — a container id under Compose,
        # a pod name under k3s. Unique across the installation, which is what
        # makes the reconciler's upsert idempotent.
        sa.Column("replica_ref", sa.Text(), nullable=False),
        sa.Column(
            "version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("replica_ref", name="uq_serving_replicas_ref"),
        sa.CheckConstraint(
            f"status IN ({_in_list(REPLICA_STATUSES)})", name="ck_serving_replicas_status"
        ),
        # A replica that has ended is not ready, and one that is ready has not
        # ended. Both halves, because the console counts `ready` and a stale
        # `true` on a dead container is capacity the tenant does not have.
        sa.CheckConstraint(
            "NOT (ready AND ended_at IS NOT NULL)", name="ck_serving_replicas_ready_not_ended"
        ),
        sa.CheckConstraint(
            "(status IN ('stopped', 'failed')) = (ended_at IS NOT NULL)",
            name="ck_serving_replicas_terminal_dated",
        ),
    )


def _model_activation_history() -> None:
    """Immutable. Who changed what was serving, when, and why.

    Distinct from `deployment_revisions`, which records *attempts*. This records
    the ones that landed, with an actor — it is the row `/audit` reads and the
    one ER-F-11 requires for activation and rollback.
    """
    op.create_table(
        "model_activation_history",
        sa.Column(
            "activation_id",
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
        sa.Column(
            "from_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "to_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # No foreign key. The actor may be a platform operator, who lives in a
        # different table, or `system`, who lives in none — and a history that
        # broke when a user was deleted would be a history that could be edited
        # by deleting a user.
        sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"actor_type IN ({_in_list(ACTOR_TYPES)})", name="ck_model_activation_history_actor"
        ),
        sa.CheckConstraint(
            "char_length(reason) <= 500", name="ck_model_activation_history_reason_length"
        ),
    )


def _recommendation_requests() -> None:
    """One row per answered request. Short retention by design."""
    op.create_table(
        "recommendation_requests",
        sa.Column(
            "request_id",
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
        #: The caller's own `request_id`, which is their idempotency key for
        #: metering (Ultimate §27) and the key `/feedback/*` references.
        sa.Column("external_request_id", sa.Text(), nullable=False),
        sa.Column(
            "customer_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.customer_id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Hashed, not stored. See the module docstring.
        sa.Column("session_hash", sa.Text(), nullable=True),
        sa.Column(
            "model_version_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.model_version_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column(
            "fallback_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("returned_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'served'")),
        # The two columns `/v1/service-status/errors` renders, and the only two
        # it may. `error_reason` is written from `graphrec.common.error_copy`
        # and never from a caller's input, which is what keeps the panel
        # redacted by construction rather than by review.
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # SRS §5.2.12. A repeat of the same `request_id` is a duplicate, and the
        # metering counter must not move for it.
        sa.UniqueConstraint(
            "tenant_id", "external_request_id", name="uq_recommendation_requests_ref"
        ),
        sa.CheckConstraint(
            "customer_id IS NOT NULL OR session_hash IS NOT NULL",
            name="ck_recommendation_requests_identified",
        ),
        sa.CheckConstraint(
            f"strategy IN ({_in_list(STRATEGIES)})", name="ck_recommendation_requests_strategy"
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(REQUEST_STATUSES)})", name="ck_recommendation_requests_status"
        ),
        sa.CheckConstraint(
            "requested_count > 0 AND returned_count >= 0 AND returned_count <= requested_count",
            name="ck_recommendation_requests_counts",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_recommendation_requests_latency"
        ),
        # `fallback_applied` and `strategy = 'fallback'` are the same fact, and
        # a row where they disagreed would make the fallback rate on
        # `/service-status` depend on which column was counted.
        sa.CheckConstraint(
            "fallback_applied = (strategy = 'fallback')",
            name="ck_recommendation_requests_fallback_agrees",
        ),
        sa.CheckConstraint(
            f"error_class IS NULL OR error_class IN ({_in_list(ERROR_CLASSES)})",
            name="ck_recommendation_requests_error_class",
        ),
        # A row that did not end `served` has to say why, and a row that did
        # must not invent a reason. Without this the errors panel would be a
        # view over whatever happened to be filled in.
        sa.CheckConstraint(
            "(status <> 'served') = (error_class IS NOT NULL)",
            name="ck_recommendation_requests_error_explained",
        ),
        sa.CheckConstraint(
            "(error_class IS NULL) = (error_reason IS NULL)",
            name="ck_recommendation_requests_error_reason",
        ),
    )


def _recommendation_results() -> None:
    """What was returned, in the order it was returned in."""
    op.create_table(
        "recommendation_results",
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_requests.request_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rank_position", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        #: What the model said, before ordering. `NULL` on a fallback lane,
        #: where no model scored anything — zero would be a score.
        sa.Column("model_score", sa.Numeric(12, 6), nullable=True),
        #: What the ordering policy said, which is what determined the rank.
        sa.Column("final_score", sa.Numeric(12, 6), nullable=False),
        sa.Column("candidate_source", sa.Text(), nullable=False),
        # A product appears once per request. Without this a diversity rule with
        # a bug could return the same item at rank 1 and rank 4.
        sa.UniqueConstraint("request_id", "product_id", name="uq_recommendation_results_product"),
        sa.CheckConstraint("rank_position >= 1", name="ck_recommendation_results_rank_positive"),
        sa.CheckConstraint(
            f"candidate_source IN ({_in_list(CANDIDATE_SOURCES)})",
            name="ck_recommendation_results_source",
        ),
    )


def _recommendation_impressions() -> None:
    """What the tenant says they showed."""
    op.create_table(
        "recommendation_impressions",
        sa.Column(
            "impression_id",
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
            "request_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_requests.request_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # A repeat is a `duplicate_confirmed` success, exactly as an event is.
        sa.UniqueConstraint(
            "tenant_id", "external_event_id", name="uq_recommendation_impressions_ref"
        ),
        sa.CheckConstraint("position >= 1", name="ck_recommendation_impressions_position"),
    )


def _recommendation_feedback() -> None:
    """Clicks and conversions. Informational only — ASM-05."""
    op.create_table(
        "recommendation_feedback",
        sa.Column(
            "feedback_id",
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
        sa.Column("external_feedback_id", sa.Text(), nullable=False),
        sa.Column(
            "request_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_requests.request_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "impression_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_impressions.impression_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feedback_type", sa.Text(), nullable=False),
        #: A conversion's value, when the tenant sends one. `NULL` on a click,
        #: because a click has no amount and zero would be an amount.
        sa.Column("value", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # SRS §5.2.14.
        sa.UniqueConstraint(
            "tenant_id", "external_feedback_id", name="uq_recommendation_feedback_ref"
        ),
        sa.CheckConstraint(
            f"feedback_type IN ({_in_list(FEEDBACK_TYPES)})",
            name="ck_recommendation_feedback_type",
        ),
        sa.CheckConstraint("value IS NULL OR value >= 0", name="ck_recommendation_feedback_value"),
    )


def _indexes() -> None:
    # The reconciler's sweep: every deployment whose desired state is not yet
    # reflected. `state` leads because the transitional set is the small one.
    op.create_index("ix_model_deployments_state", "model_deployments", ["state"])
    # `/service-status`'s per-replica table, and the reconciler's observation
    # join. Live replicas only would be a partial index; there are at most a few
    # dozen rows, so the whole index is cheaper to reason about.
    op.create_index(
        "ix_serving_replicas_deployment", "serving_replicas", ["deployment_id", "status"]
    )
    # The revision history, newest first — which is how both the tenant's
    # dialog and the failure investigation read it.
    op.create_index(
        "ix_deployment_revisions_recent",
        "deployment_revisions",
        ["deployment_id", sa.text("revision DESC")],
    )
    op.create_index(
        "ix_model_activation_history_tenant",
        "model_activation_history",
        ["tenant_id", sa.text("occurred_at DESC")],
    )
    # `/v1/metrics/summary` counts a rolling 24 hours per tenant, and the
    # fallback rate is a filter on the same scan.
    op.create_index(
        "ix_recommendation_requests_recent",
        "recommendation_requests",
        ["tenant_id", sa.text("requested_at DESC")],
    )
    op.create_index("ix_recommendation_feedback_request", "recommendation_feedback", ["request_id"])


GRANTS: dict[str, str] = {
    # Desired state, observed state and the counters all move, so this table is
    # the one genuinely mutable thing in the phase.
    "model_deployments": "SELECT, INSERT, UPDATE, DELETE",
    # A revision is opened `pending` and settled once. Column-level `UPDATE`:
    # the versions it names and the reason it was attempted for are what make it
    # a history, and a history that can be edited is not one.
    "deployment_revisions": "SELECT, INSERT, UPDATE (status, failure_reason, completed_at)",
    # The reconciler upserts observations and prunes replicas that are gone, so
    # this one is fully mutable — it is a mirror of the driver, not a record.
    "serving_replicas": "SELECT, INSERT, UPDATE, DELETE",
    # Immutable. ER-F-11.
    "model_activation_history": "SELECT, INSERT",
    # Inserted before the response goes out, completed after it. Nothing else
    # about the row may move — not the strategy, not the version, not the
    # counts, because those are what a tenant attributes a metrics change to.
    "recommendation_requests": "SELECT, INSERT, UPDATE (latency_ms, status, returned_count)",
    "recommendation_results": "SELECT, INSERT",
    "recommendation_impressions": "SELECT, INSERT",
    "recommendation_feedback": "SELECT, INSERT",
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

    # `/admin/status` renders "Serving replicas 7 / 7" across the installation
    # (BACKEND_PLAN L462), so the platform role reads the two counters and the
    # state — and nothing that says what any tenant is serving or how well.
    op.execute(
        "GRANT SELECT (deployment_id, tenant_id, state, desired_replicas, ready_replicas, "
        "last_transition_at) ON model_deployments TO graphrec_platform"
    )
    op.execute(
        """
        CREATE POLICY model_deployments_platform_read ON model_deployments
            FOR SELECT TO graphrec_platform
            USING (true)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS model_deployments_platform_read ON model_deployments")
    op.execute("REVOKE ALL ON model_deployments FROM graphrec_platform")
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
        op.drop_table(table)
