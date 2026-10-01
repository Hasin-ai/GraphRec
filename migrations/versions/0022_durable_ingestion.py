"""Retain bounded sync/batch outcomes and client request IDs."""

from alembic import op

revision = "0022_durable_ingestion"
down_revision = "0021_account_recovery"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE event_batches ADD COLUMN request_id varchar(128)")
    op.execute("ALTER TABLE event_batches ADD COLUMN payload_hash varchar(64)")
    op.execute("ALTER TABLE event_batches ADD COLUMN outcomes jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("CREATE UNIQUE INDEX uq_event_batches_tenant_request ON event_batches(tenant_id, request_id) WHERE request_id IS NOT NULL")
    op.execute("""
      CREATE TABLE catalog_syncs (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        request_id varchar(128),
        payload_hash varchar(64),
        status varchar(32) NOT NULL,
        accepted_count integer NOT NULL,
        created_count integer NOT NULL,
        updated_count integer NOT NULL,
        skipped_count integer NOT NULL,
        rejected_count integer NOT NULL,
        outcomes jsonb NOT NULL DEFAULT '[]'::jsonb,
        created_at timestamptz NOT NULL
      )
    """)
    op.execute("CREATE UNIQUE INDEX uq_catalog_syncs_tenant_request ON catalog_syncs(tenant_id, request_id) WHERE request_id IS NOT NULL")
    op.execute("CREATE INDEX ix_catalog_syncs_tenant_created ON catalog_syncs(tenant_id, created_at)")
    op.execute("ALTER TABLE catalog_syncs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog_syncs FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY catalog_syncs_select ON catalog_syncs FOR SELECT TO graphrec_app USING ({TENANT})")
    op.execute(f"CREATE POLICY catalog_syncs_insert ON catalog_syncs FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute("GRANT SELECT, INSERT ON catalog_syncs TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP TABLE catalog_syncs")
    op.execute("DROP INDEX uq_event_batches_tenant_request")
    op.execute("ALTER TABLE event_batches DROP COLUMN outcomes")
    op.execute("ALTER TABLE event_batches DROP COLUMN payload_hash")
    op.execute("ALTER TABLE event_batches DROP COLUMN request_id")
