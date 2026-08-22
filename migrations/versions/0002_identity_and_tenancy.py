"""Identity, tenancy and row-level security.

This is the migration the rest of the system depends on being right. BUILD_PROMPT
calls retrofitting `tenant_id` and RLS "the single most expensive mistake
available in this project", so every tenant-owned table here carries `tenant_id`
from birth, with RLS `ENABLE`d *and* `FORCE`d and both a `USING` and a
`WITH CHECK` clause.

`USING` without `WITH CHECK` is the subtle half. `USING` filters what a statement
can see; `WITH CHECK` constrains what it can write. A policy with only `USING`
lets a tenant `INSERT` a row stamped with someone else's `tenant_id` — and then
never see it again, which makes the bug invisible from the tenant's own console.

Two realms, two database roles:

* `graphrec_app` serves tenant traffic. Its policies resolve `app.tenant_id`,
  set per transaction with `SET LOCAL` from the verified token claim. When that
  setting is absent the comparison is `NULL`, which is not `TRUE`, so the default
  is deny — an unset context returns zero rows rather than every row.
* `graphrec_platform` serves the platform console. It is granted access to the
  seven tables `/admin/*` actually renders and **nothing else**: products, events
  and recommendations are unreachable to it at the grant level, not merely by
  policy. A platform administrator has no business reading a tenant's catalogue,
  and the cheapest way to guarantee that is to never grant it.

The alternative — one role with `OR current_setting('app.platform_actor_id') IS
NOT NULL` bolted onto every tenant policy — was rejected. It weakens every policy
in the database to serve seven admin screens, and it makes the platform path a
clause in a `USING` expression rather than a privilege boundary.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
PLATFORM_ROLE = "graphrec_platform"

#: The GUC the tenant policies resolve. Set with `SET LOCAL` inside the
#: transaction, so it cannot leak to the next checkout of a pooled connection.
TENANT_GUC = "app.tenant_id"

#: The six metered usage types, as the console's quota table renders them
#: (dc.html L725-727). Written once and referenced twice so the two quota tables
#: cannot drift apart from each other.
_USAGE_TYPE_CHECK = (
    "usage_type IN ('events','recommendations','training',"
    "'products','storage','service_capacity')"
)

#: Tables owned by a tenant. Each gets `tenant_id`, RLS, and the same policy.
TENANT_TABLES: tuple[str, ...] = (
    "tenant_users",
    "invitations",
    "tenant_subscriptions",
    "tenant_resource_quotas",
    "quota_overrides",
)


def upgrade() -> None:
    _pricing_plans()
    _tenants()
    _tenant_users()
    _platform_users()
    _invitations()
    _sessions_and_recovery()
    _subscriptions_and_quotas()

    _create_platform_role()
    for table in TENANT_TABLES:
        _enable_tenant_rls(table)
    _enable_tenants_rls()
    for table in ("refresh_sessions", "recovery_tokens"):
        _enable_tenant_rls(table)
    _grant_platform_reads()
    _seed_pricing_plans()


# --------------------------------------------------------------------- tables


def _pricing_plans() -> None:
    """Platform-owned reference data (SRS §5.2.1). Not tenant-scoped.

    Every tenant may read every plan — the console's plan picker shows them all —
    so this table carries no `tenant_id` and no RLS. It is one of the few places
    where the absence of a policy is correct rather than an oversight, which is
    why it is stated here explicitly.
    """
    op.create_table(
        "pricing_plans",
        sa.Column("plan_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_code", sa.Text(), nullable=False, unique=True),
        sa.Column("plan_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_limit", sa.BigInteger(), nullable=False),
        sa.Column("recommendation_limit", sa.BigInteger(), nullable=False),
        sa.Column("training_limit", sa.Integer(), nullable=False),
        sa.Column("product_limit", sa.BigInteger(), nullable=False),
        sa.Column("storage_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "service_limits", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # SRS: "Whether new assignments are allowed". The console renders a
        # closed plan as still assigned to its existing tenants (L1454), so this
        # gates assignment, never membership.
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # SRS §5.2.1: "Limits shall be non-negative." The prototype's own copy
        # for a negative entry is "A negative limit conflicts with the quota
        # model. Enter zero to withhold a usage type entirely." (L1635) — zero is
        # meaningful, so the bound is >= 0, not > 0.
        sa.CheckConstraint("event_limit >= 0", name="ck_pricing_plans_event_limit_non_negative"),
        sa.CheckConstraint(
            "recommendation_limit >= 0", name="ck_pricing_plans_recommendation_limit_non_negative"
        ),
        sa.CheckConstraint(
            "training_limit >= 0", name="ck_pricing_plans_training_limit_non_negative"
        ),
        sa.CheckConstraint(
            "product_limit >= 0", name="ck_pricing_plans_product_limit_non_negative"
        ),
        sa.CheckConstraint(
            "storage_limit_bytes >= 0", name="ck_pricing_plans_storage_limit_non_negative"
        ),
    )
    op.execute(f"GRANT SELECT ON pricing_plans TO {APP_ROLE}")


def _tenants() -> None:
    """The tenant root (SRS §5.2.2).

    Special among the tenant-owned tables: its key column is `tenant_id` itself,
    so the policy compares the primary key rather than a foreign one.
    """
    op.create_table(
        "tenants",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id", pg.UUID(as_uuid=True), sa.ForeignKey("pricing_plans.plan_id"), nullable=True
        ),
        sa.Column("tenant_code", sa.Text(), nullable=False, unique=True),
        sa.Column("tenant_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("settings", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        # The five values are the prototype's, generated into TenantStatus and
        # pinned by LOCKED_VOCABULARIES. Enforced here as a CHECK rather than a
        # PostgreSQL ENUM: adding a value to an ENUM cannot be done inside a
        # transaction on older servers, and a CHECK reads in `\d`.
        sa.CheckConstraint(
            "status IN ('pending','active','suspended','deleting','deleted')",
            name="ck_tenants_status",
        ),
        # SRS §5.2.2: "A Tenant must reference one active Pricing Plan when
        # activated." A pending tenant has none yet, so the FK is nullable and
        # the requirement is expressed as a conditional CHECK instead.
        sa.CheckConstraint(
            "status <> 'active' OR plan_id IS NOT NULL",
            name="ck_tenants_active_requires_plan",
        ),
    )
    # Business name uniqueness is what produces the prototype's registration
    # conflict at L1582 ("A tenant account named “Kelder Tools” already
    # exists"). Case-insensitive, because "kelder tools" is the same business.
    op.execute("CREATE UNIQUE INDEX uq_tenants_name_ci ON tenants (lower(tenant_name))")
    # INSERT is granted so that registration can work, and the policy is what
    # makes that safe. `POST /v1/tenants` generates the new `tenant_id` itself,
    # binds the context to it, and only then inserts — so `WITH CHECK` passes for
    # the row being created and for no other. A caller can create a tenant whose
    # identifier it just minted, and can still see nothing else.
    #
    # No DELETE: SRS §5.2.2 says "Tenant deletion follows a controlled lifecycle
    # rather than immediate removal", which is the `deleting` and `deleted`
    # statuses, not a row disappearing.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenants TO {APP_ROLE}")


def _tenant_users() -> None:
    """SRS §5.2.3. `email` is unique *per tenant*, not globally.

    The prototype is explicit about why: "Email is unique per tenant, so this is
    a conflict rather than a validation error." (L1235) One person may hold an
    account at two tenants, and neither may learn of the other.
    """
    op.create_table(
        "tenant_users",
        sa.Column("tenant_user_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        # Argon2id. Named `credential_digest` after the SRS rather than
        # `password_hash`, and never selected into any response model.
        sa.Column("credential_digest", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="invited"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('tenant_administrator','tenant_developer')", name="ck_tenant_users_role"
        ),
        sa.CheckConstraint(
            "status IN ('invited','active','locked','disabled')", name="ck_tenant_users_status"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_users_email ON tenant_users (tenant_id, lower(email))"
    )
    # Sign-in looks a user up by email before any tenant context exists, so this
    # index must not be tenant-first.
    op.create_index("ix_tenant_users_email", "tenant_users", ["email"])
    # The last-active-administrator rule takes a row lock over this predicate.
    op.execute(
        "CREATE INDEX ix_tenant_users_active_admins ON tenant_users (tenant_id) "
        "WHERE role = 'tenant_administrator' AND status = 'active'"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenant_users TO {APP_ROLE}")


def _platform_users() -> None:
    """The platform realm (BUILD_PROMPT §7.2). Deliberately has no `tenant_id`.

    A platform token carries `perms[]` and no `tid`; a tenant token carries `tid`
    and a `role`. Neither can be mistaken for the other, and the absence of a
    `tenant_id` column here is what makes "a platform user belongs to no tenant"
    a schema fact rather than a convention.

    This table is not readable by `graphrec_app` at all. The tenant realm has no
    reason to enumerate operators.
    """
    op.create_table(
        "platform_users",
        sa.Column("platform_user_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("credential_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('invited','active','locked','disabled')", name="ck_platform_users_status"
        ),
    )
    op.execute("CREATE UNIQUE INDEX uq_platform_users_email ON platform_users (lower(email))")

    op.create_table(
        "platform_user_permissions",
        sa.Column(
            "platform_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.platform_user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", sa.Text(), primary_key=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("granted_by", pg.UUID(as_uuid=True), nullable=True),
        # The five independently grantable permissions, generated from the
        # prototype's PERMS table into PlatformPermission.
        sa.CheckConstraint(
            "permission IN ('platform','plan_management','platform_scope','monitoring','audit')",
            name="ck_platform_user_permissions_value",
        ),
    )


def _invitations() -> None:
    """A pending tenant user, before any credential exists."""
    op.create_table(
        "invitations",
        sa.Column("invitation_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        # Only the digest is stored. The token is shown once, at creation, and is
        # not retrievable afterwards — the same rule the credential secret follows.
        sa.Column("token_digest", sa.Text(), nullable=False, unique=True),
        sa.Column("invited_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "role IN ('tenant_administrator','tenant_developer')", name="ck_invitations_role"
        ),
    )
    op.create_index("ix_invitations_tenant_email", "invitations", ["tenant_id", "email"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON invitations TO {APP_ROLE}")


def _sessions_and_recovery() -> None:
    """Refresh sessions and recovery tokens, for both realms.

    The obvious objection is that these are read *before* a tenant context
    exists — the point of presenting a refresh token is that no access token is
    held yet — and that they therefore cannot live behind the `app.tenant_id`
    policy.

    That objection is wrong, and accepting it would have left two tenant-owned
    tables unprotected. Both token kinds are **signed** (EdDSA, the same keypair
    as the access token) and carry a `tid` claim, so the tenant is known from a
    verified credential before any row is read, exactly as NR-NF-02 requires. The
    context is set from that claim and the lookup happens under the policy.

    A forged `tid` gains nothing: the signature check fails first, and even if it
    did not, narrowing the context to the wrong tenant makes the row invisible
    rather than visible. The claim can only ever restrict the search.

    Platform rows carry `tenant_id IS NULL` and are therefore invisible to the
    tenant role under the same policy — the tenant realm must never be able to
    revoke an operator's session.

    Storing a digest rather than the token means a database read does not yield a
    usable credential.
    """
    for name, extra in (
        (
            "refresh_sessions",
            [
                sa.Column(
                    "issued_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
                sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("user_agent", sa.Text(), nullable=True),
                # Recorded for the session list the console shows. Not used for
                # authorization: a changing address is a travelling user far more
                # often than a stolen token.
                sa.Column("client_address", pg.INET(), nullable=True),
                # Rotation: a refresh token is single-use, and presenting a
                # superseded one is evidence of theft.
                sa.Column("superseded_by", pg.UUID(as_uuid=True), nullable=True),
            ],
        ),
        (
            "recovery_tokens",
            [
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
                sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            ],
        ),
    ):
        op.create_table(
            name,
            sa.Column(f"{name[:-1]}_id", pg.UUID(as_uuid=True), primary_key=True),
            # Exactly one of these is set, enforced below. A row that could name
            # both a tenant user and a platform user is a cross-realm token.
            sa.Column(
                "tenant_user_id",
                pg.UUID(as_uuid=True),
                sa.ForeignKey("tenant_users.tenant_user_id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "platform_user_id",
                pg.UUID(as_uuid=True),
                sa.ForeignKey("platform_users.platform_user_id", ondelete="CASCADE"),
                nullable=True,
            ),
            # Denormalised from tenant_users so that revoking every session for a
            # tenant does not require a join the policy cannot see.
            sa.Column(
                "tenant_id",
                pg.UUID(as_uuid=True),
                sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("token_digest", sa.Text(), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            *extra,
            sa.CheckConstraint(
                "(tenant_user_id IS NOT NULL AND platform_user_id IS NULL"
                " AND tenant_id IS NOT NULL)"
                " OR (platform_user_id IS NOT NULL AND tenant_user_id IS NULL"
                " AND tenant_id IS NULL)",
                name=f"ck_{name}_exactly_one_realm",
            ),
        )
        op.create_index(f"ix_{name}_tenant_user", name, ["tenant_user_id"])
        op.create_index(f"ix_{name}_platform_user", name, ["platform_user_id"])
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {name} TO {APP_ROLE}")


def _subscriptions_and_quotas() -> None:
    """Which plan a tenant holds, and the bounds derived from it."""
    op.create_table(
        "tenant_subscriptions",
        sa.Column("subscription_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id", pg.UUID(as_uuid=True), sa.ForeignKey("pricing_plans.plan_id"), nullable=False
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    # A tenant holds at most one open subscription. Expressed as a partial unique
    # index so the history of closed ones is retained for the audit trail.
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_subscriptions_current "
        "ON tenant_subscriptions (tenant_id) WHERE ended_at IS NULL"
    )

    op.create_table(
        "tenant_resource_quotas",
        sa.Column("quota_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("usage_type", sa.Text(), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            _USAGE_TYPE_CHECK,
            name="ck_tenant_resource_quotas_usage_type",
        ),
        # "Enter zero to withhold a usage type entirely." (L1635)
        sa.CheckConstraint("limit_value >= 0", name="ck_tenant_resource_quotas_non_negative"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_resource_quotas_current "
        "ON tenant_resource_quotas (tenant_id, usage_type) WHERE period_end IS NULL"
    )

    op.create_table(
        "quota_overrides",
        sa.Column("override_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("usage_type", sa.Text(), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=False),
        # The prototype requires a reason and writes it to the audit history
        # (L1420), so it is NOT NULL here rather than validated only in the API.
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _USAGE_TYPE_CHECK,
            name="ck_quota_overrides_usage_type",
        ),
        sa.CheckConstraint("limit_value >= 0", name="ck_quota_overrides_non_negative"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_quota_overrides_reason_not_blank"),
    )

    for table in ("tenant_subscriptions", "tenant_resource_quotas", "quota_overrides"):
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")


# ----------------------------------------------------------------------- RLS


def _enable_tenant_rls(table: str) -> None:
    """`ENABLE` + `FORCE` + `USING` + `WITH CHECK`, on the `tenant_id` column.

    `FORCE` matters because the table owner is exempt from its own policies
    otherwise, and migrations run as the owner. Without it, an owner-run repair
    script silently sees every tenant.

    The consequence, which is deliberate and worth stating plainly: **the owner
    cannot read or write these tables either.** A later data migration that needs
    to touch tenant rows must do one of two things, and both are visible in
    review:

    * loop over tenants, setting `app.tenant_id` for each — correct, and it makes
      a per-tenant backfill explicitly per-tenant; or
    * `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY`, do the work, and restore
      `FORCE` in the same transaction — blunt, but it is a line in a diff rather
      than an ambient privilege.

    What must never happen is granting the owner a blanket `USING (true)` policy
    to make the inconvenience go away. That would return the database to exactly
    the state `FORCE` exists to prevent.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            FOR ALL
            TO {APP_ROLE}
            USING (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
            WITH CHECK (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
        """
    )


def _enable_tenants_rls() -> None:
    """`tenants` compares its own primary key.

    A tenant may read and update its own row (the console's /account page) and
    must not see that any other exists — which is also what makes a foreign
    tenant code return 404 rather than 403.
    """
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenants_self_isolation ON tenants
            FOR ALL
            TO {APP_ROLE}
            USING (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
            WITH CHECK (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
        """
    )


def _create_platform_role() -> None:
    from psycopg import sql

    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": PLATFORM_ROLE}
    ).scalar()
    driver = conn.connection.driver_connection
    if exists:
        driver.execute(
            sql.SQL("ALTER ROLE {role} LOGIN NOINHERIT").format(role=sql.Identifier(PLATFORM_ROLE))
        )
    else:
        import os

        password = os.environ.get("POSTGRES_PLATFORM_PASSWORD", "graphrec_platform_local_only")
        driver.execute(
            sql.SQL(
                "CREATE ROLE {role} LOGIN NOINHERIT NOCREATEDB NOCREATEROLE PASSWORD {password}"
            ).format(role=sql.Identifier(PLATFORM_ROLE), password=sql.Literal(password))
        )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def _grant_platform_reads() -> None:
    """The platform realm reaches exactly the tables `/admin/*` renders.

    Not one table more. `products`, `interaction_events`, `customers` and
    `recommendation_results` arrive in later phases and will receive no grant
    here, so a platform administrator cannot read a tenant's catalogue or its
    customers' behaviour even by mistake — there is no privilege to misuse.

    These tables carry no policy `TO graphrec_platform`, and RLS denies by
    default when no policy matches, so each needs an explicit permissive one.
    """
    op.execute(f"GRANT SELECT, UPDATE ON tenants TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT ON tenant_users TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON pricing_plans TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenant_subscriptions TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenant_resource_quotas TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON quota_overrides TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform_users TO {PLATFORM_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform_user_permissions TO {PLATFORM_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON refresh_sessions TO {PLATFORM_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON recovery_tokens TO {PLATFORM_ROLE}")

    # The platform role legitimately works across tenants, so its policy is
    # unconditional — but only on these tables, and only because the grant list
    # above is the real boundary.
    for table in (
        "tenants",
        "tenant_users",
        "tenant_subscriptions",
        "tenant_resource_quotas",
        "quota_overrides",
        "refresh_sessions",
        "recovery_tokens",
    ):
        op.execute(
            f"CREATE POLICY {table}_platform_access ON {table} "
            f"FOR ALL TO {PLATFORM_ROLE} USING (true) WITH CHECK (true)"
        )


# ---------------------------------------------------------------------- seed


def _seed_pricing_plans() -> None:
    """The three plans, with the prototype's own numbers (D11, dc.html L725-727).

    Seeded in the migration rather than by a script so that a fresh database is
    immediately usable and every environment holds identical plan codes — a
    tenant on GROWTH must mean the same thing everywhere.
    """
    gb = 1024**3
    plans = (
        ("STARTER", "Starter", 1_000_000, 2_000_000, 4, 10_000, 20 * gb, True),
        ("GROWTH", "Growth", 6_000_000, 15_000_000, 8, 50_000, 80 * gb, True),
        # `open:false` in the prototype — closed to new assignments, which is
        # what produces "Plan SCALE is closed to new assignments." (L1454)
        ("SCALE", "Scale", 20_000_000, 60_000_000, 20, 250_000, 400 * gb, False),
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO pricing_plans (plan_id, plan_code, plan_name, event_limit, "
            "recommendation_limit, training_limit, product_limit, storage_limit_bytes, is_active) "
            "VALUES (gen_random_uuid(), :code, :name, :events, :recs, :training, :products, "
            ":storage, :is_active)"
        ),
        [
            {
                "code": code,
                "name": name,
                "events": events,
                "recs": recs,
                "training": training,
                "products": products,
                "storage": storage,
                "is_active": is_active,
            }
            for code, name, events, recs, training, products, storage, is_active in plans
        ],
    )


def downgrade() -> None:
    for table in (
        "recovery_tokens",
        "refresh_sessions",
        "quota_overrides",
        "tenant_resource_quotas",
        "tenant_subscriptions",
        "invitations",
        "platform_user_permissions",
        "platform_users",
        "tenant_users",
        "tenants",
        "pricing_plans",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PLATFORM_ROLE}")
    # The role itself is left in place, for the reason migration 0001 gives.
