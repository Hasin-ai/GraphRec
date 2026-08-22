"""The catalog, and the one place eligibility is decided.

Two tables and one function. The function is the point of the migration.

**Eligibility is derived, never stored** (BACKEND_PLAN §3.5). The console shows
a `served` / `ineligible` badge with a sentence explaining why; the serving path
filters candidates by the same rule; and the partial index the serving path
walks has to agree with both. Three call sites, and a fourth the day someone
writes a report.

Written three times in three languages, those drift, and the drift is silent:
the catalogue screen says a product is served, the recommender never returns it,
and nothing errors. So the rule is written **once**, in SQL, as an `IMMUTABLE`
function returning the *reason* a product is excluded — `NULL` when it is not:

    product_ineligibility(is_active, availability, deleted_at) IS NULL

That expression is the index predicate, the serving filter, and the projection
the API reads its badge from. They cannot disagree, because there is nothing to
keep in agreement.

Returning a reason rather than a boolean is what lets the API render "Out of
stock — excluded from serving" (dc.html L683) without a second rule deciding
which explanation applies. The function decides; Python only looks the wording
up.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
PLATFORM_ROLE = "graphrec_platform"
TENANT_GUC = "app.tenant_id"

#: `graphrec/common/enums.py::Availability`, generated from the prototype's
#: `seed()` products[].avail. Repeated here because a migration cannot import
#: application code, and pinned by `tests/contract/test_migration_literals.py`.
AVAILABILITY = ("in_stock", "low_stock", "out_of_stock")

#: The ineligibility codes the function can return. `graphrec/catalog/eligibility.py`
#: maps each to the prototype's wording.
INELIGIBILITY_CODES = ("product_removed", "product_inactive", "product_out_of_stock")


def upgrade() -> None:
    _categories()
    _products()
    _eligibility()
    _indexes()
    _rls_and_grants()


def _categories() -> None:
    op.create_table(
        "product_categories",
        sa.Column(
            "category_id",
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
        # The tenant's own identifier for the category. The console's filter
        # renders category names ("Hardware", "Timber"), and a tenant that
        # renames a category must not thereby create a second one.
        sa.Column("external_category_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # `nullable=False` on both, as on every other table. A server default
        # without it leaves the column optional, and an explicit NULL written
        # by a caller would give a category no creation time at all.
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
            "tenant_id", "external_category_id", name="uq_product_categories_tenant_external"
        ),
        sa.CheckConstraint(
            "char_length(external_category_id) BETWEEN 1 AND 120",
            name="ck_product_categories_external_id_length",
        ),
        # L1614 reports "category exceeds 120 characters" as a per-item sync
        # failure, so 120 is the product's bound and not an arbitrary one.
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name="ck_product_categories_name_length"
        ),
    )


def _products() -> None:
    op.create_table(
        "products",
        sa.Column(
            "product_id",
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
        # "The external identifier is your own product identifier and is unique
        # within this tenant. It is also the idempotency key for later updates."
        # (dc.html L1320) — so it is the addressable identity on the wire, and
        # `product_id` never appears in a URL.
        sa.Column("external_product_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "category_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("product_categories.category_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("brand", sa.Text(), nullable=True),
        # numeric(12,2): money, and never a float. BACKEND_PLAN §14.
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "availability", sa.Text(), nullable=False, server_default=sa.text("'in_stock'::text")
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Disabling is a state change, not a removal: "The record is retained and
        # can be re-enabled by an update." (L1340). `deleted_at` exists for the
        # tenant-deletion path in the reconciler, and is not what `:disable`
        # writes.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "external_product_id", name="uq_products_tenant_external"),
        sa.CheckConstraint(
            "char_length(external_product_id) BETWEEN 1 AND 120",
            name="ck_products_external_id_length",
        ),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 500", name="ck_products_title_length"),
        # L1614: "price is not a positive decimal". Zero is allowed — a free item
        # is a real catalogue entry — but a negative price is not a price.
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_products_price_non_negative"),
        sa.CheckConstraint("availability IN " + str(AVAILABILITY), name="ck_products_availability"),
        # A reason is required for disabling and is written to the audit history
        # (L1340). Enforced here as well as in the service, because a route added
        # later that forgets is a route that silently loses the explanation.
        sa.CheckConstraint(
            "is_active OR disabled_reason IS NOT NULL", name="ck_products_disabled_has_reason"
        ),
        sa.CheckConstraint(
            "(disabled_reason IS NULL) = (disabled_at IS NULL)",
            name="ck_products_disabled_reason_has_time",
        ),
        sa.CheckConstraint(
            "disabled_reason IS NULL OR char_length(disabled_reason) BETWEEN 4 AND 500",
            name="ck_products_disabled_reason_length",
        ),
    )


def _eligibility() -> None:
    """The single definition. See the module docstring.

    `IMMUTABLE` because a partial index predicate requires it, and it is honestly
    immutable: the answer depends on the three arguments and nothing else. In
    particular it does not consult `now()`, which is why `deleted_at` is compared
    against NULL rather than against the clock — an index whose predicate moved
    with time would be wrong the moment it was built.
    """
    op.execute(
        """
        CREATE OR REPLACE FUNCTION product_ineligibility(
            p_is_active boolean, p_availability text, p_deleted_at timestamptz
        )
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        -- Deliberately not STRICT. `deleted_at` is NULL for every live
        -- product, and a strict function would return NULL for all of
        -- them — which reads as "eligible" by accident rather than by
        -- decision, and would make the index predicate `NULL IS NULL`.
        CALLED ON NULL INPUT
        SET search_path = pg_catalog, public
        AS $$
            SELECT CASE
                -- Ordered, and the order is a decision. A product that is both
                -- inactive and out of stock is reported as inactive, because
                -- that is the state the tenant chose and the one they can act
                -- on; stock is a fact about the world.
                WHEN p_deleted_at IS NOT NULL THEN 'product_removed'
                WHEN NOT p_is_active           THEN 'product_inactive'
                WHEN p_availability = 'out_of_stock' THEN 'product_out_of_stock'
                ELSE NULL
            END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION product_ineligibility(boolean, text, timestamptz) FROM PUBLIC"
    )
    for role in (APP_ROLE, PLATFORM_ROLE):
        op.execute(
            f"GRANT EXECUTE ON FUNCTION product_ineligibility(boolean, text, timestamptz) TO {role}"
        )


def _indexes() -> None:
    # The eligibility index, read on the hot path (BACKEND_PLAN §14). Its
    # predicate is the function, so the index and the badge cannot disagree.
    op.execute(
        "CREATE INDEX ix_products_eligible ON products (tenant_id) "
        "WHERE product_ineligibility(is_active, availability, deleted_at) IS NULL"
    )
    op.execute("CREATE INDEX ix_products_tenant_id ON products (tenant_id)")
    # What the console's list orders by, and what its category filter narrows on.
    op.execute("CREATE INDEX ix_products_tenant_updated ON products (tenant_id, updated_at DESC)")
    op.execute(
        "CREATE INDEX ix_products_tenant_category ON products (tenant_id, category_id) "
        "WHERE category_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_product_categories_tenant_id ON product_categories (tenant_id)")


def _rls_and_grants() -> None:
    for table in ("products", "product_categories"):
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
        # No DELETE. `:disable` sets a flag and keeps the row (L1340), and a
        # product that has been recommended is referred to by interaction events
        # and by recommendation results that outlive it.
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")

    # The platform realm renders seven tables and `products` is not one of them
    # (migration 0002). A platform administrator has no route to a tenant's
    # catalogue and therefore gets no grant — the count that `/admin/tenants`
    # shows comes from `usage_events`, not from here.


def downgrade() -> None:
    for table in ("products", "product_categories"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")
    # The index depends on the function, so the table goes first.
    op.drop_table("products")
    op.drop_table("product_categories")
    op.execute("DROP FUNCTION IF EXISTS product_ineligibility(boolean, text, timestamptz)")
