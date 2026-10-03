"""Normalize tenant-owned external shopper identities for events and requests."""

from alembic import op

revision = "0026_customers"
down_revision = "0025_result_feedback_tenant_fk"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
      CREATE TABLE customers (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        external_id text NOT NULL,
        created_at timestamptz NOT NULL,
        CONSTRAINT uq_customers_tenant_external UNIQUE (tenant_id, external_id)
      )
    """)
    op.execute("""
      INSERT INTO customers (id, tenant_id, external_id, created_at)
      SELECT gen_random_uuid(), tenant_id, user_id, min(created_at)
      FROM customer_events WHERE user_id IS NOT NULL
      GROUP BY tenant_id, user_id
    """)
    op.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customers FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY customers_select ON customers FOR SELECT TO graphrec_app USING ({TENANT})")
    op.execute(f"CREATE POLICY customers_insert ON customers FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute("GRANT SELECT, INSERT ON customers TO graphrec_app")
    op.execute("""
      ALTER TABLE customer_events ADD CONSTRAINT fk_customer_event_customer
      FOREIGN KEY (tenant_id, user_id) REFERENCES customers(tenant_id, external_id)
    """)
    op.execute("ALTER TABLE recommendation_records ADD COLUMN external_customer_id text")
    op.execute("""
      ALTER TABLE recommendation_records ADD CONSTRAINT fk_recommendation_record_customer
      FOREIGN KEY (tenant_id, external_customer_id) REFERENCES customers(tenant_id, external_id)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE recommendation_records DROP CONSTRAINT fk_recommendation_record_customer")
    op.execute("ALTER TABLE recommendation_records DROP COLUMN external_customer_id")
    op.execute("ALTER TABLE customer_events DROP CONSTRAINT fk_customer_event_customer")
    op.execute("DROP TABLE customers")
