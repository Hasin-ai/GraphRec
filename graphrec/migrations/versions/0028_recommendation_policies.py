"""XR-F-04 / XR-NF-02: bounded, versioned diversity and freshness re-ranking rules."""

from alembic import op

revision = "0028_recommendation_policies"
down_revision = "0027_retraining_policies"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
      CREATE TABLE recommendation_policies (
        tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
        version integer NOT NULL DEFAULT 1,
        diversity_enabled boolean NOT NULL DEFAULT false,
        max_per_category integer NOT NULL DEFAULT 3,
        freshness_enabled boolean NOT NULL DEFAULT false,
        freshness_weight numeric(4,3) NOT NULL DEFAULT 0.2,
        freshness_half_life_days integer NOT NULL DEFAULT 30,
        updated_at timestamptz NOT NULL,
        CONSTRAINT ck_recpolicy_version CHECK (version >= 1),
        CONSTRAINT ck_recpolicy_max_per_category CHECK (max_per_category BETWEEN 1 AND 100),
        CONSTRAINT ck_recpolicy_weight CHECK (freshness_weight >= 0 AND freshness_weight <= 0.3),
        CONSTRAINT ck_recpolicy_half_life CHECK (freshness_half_life_days BETWEEN 1 AND 3650)
      )
    """)
    op.execute("ALTER TABLE recommendation_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recommendation_policies FORCE ROW LEVEL SECURITY")
    for verb, clause in (("SELECT", f"USING ({TENANT})"), ("INSERT", f"WITH CHECK ({TENANT})"),
                         ("UPDATE", f"USING ({TENANT}) WITH CHECK ({TENANT})")):
        op.execute(f"CREATE POLICY recommendation_policies_{verb.lower()} ON recommendation_policies FOR {verb} TO graphrec_app {clause}")
    op.execute("GRANT SELECT, INSERT, UPDATE ON recommendation_policies TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP TABLE recommendation_policies")
