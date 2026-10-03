"""Persist ranked served products as tenant-owned result rows."""

from alembic import op

revision = "0024_recommendation_results"
down_revision = "0023_model_deployments"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
      CREATE TABLE recommendation_results (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL,
        request_id varchar(128) NOT NULL,
        external_product_id varchar(100) NOT NULL,
        rank_position integer NOT NULL,
        model_score numeric,
        final_order_score numeric,
        candidate_source varchar(48) NOT NULL,
        strategy varchar(48) NOT NULL,
        created_at timestamptz NOT NULL,
        CONSTRAINT fk_recommendation_result_request FOREIGN KEY (tenant_id, request_id)
          REFERENCES recommendation_records(tenant_id, request_id) ON DELETE CASCADE,
        CONSTRAINT fk_recommendation_result_product FOREIGN KEY (tenant_id, external_product_id)
          REFERENCES products(tenant_id, external_id),
        CONSTRAINT uq_recommendation_result_rank UNIQUE (tenant_id, request_id, rank_position),
        CONSTRAINT uq_recommendation_result_product UNIQUE (tenant_id, request_id, external_product_id),
        CONSTRAINT ck_recommendation_result_position CHECK (rank_position >= 1)
      )
    """)
    op.execute("CREATE INDEX ix_recommendation_results_tenant_product ON recommendation_results(tenant_id, external_product_id)")
    op.execute("""
      INSERT INTO recommendation_results (id, tenant_id, request_id, external_product_id,
        rank_position, candidate_source, strategy, created_at)
      SELECT gen_random_uuid(), r.tenant_id, r.request_id, p.external_id,
        (item.value->>'position')::integer,
        COALESCE(r.response->>'fallback_tier', 'legacy'),
        COALESCE(r.response->>'strategy', 'legacy'), r.created_at
      FROM recommendation_records r
      CROSS JOIN LATERAL jsonb_array_elements(r.response->'items') item
      JOIN products p ON p.tenant_id = r.tenant_id AND p.external_id = item.value->>'external_product_id'
      WHERE (item.value->>'position') ~ '^[0-9]+$'
      ON CONFLICT DO NOTHING
    """)
    op.execute("ALTER TABLE recommendation_results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recommendation_results FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY recommendation_results_select ON recommendation_results FOR SELECT TO graphrec_app USING ({TENANT})")
    op.execute(f"CREATE POLICY recommendation_results_insert ON recommendation_results FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute("GRANT SELECT, INSERT ON recommendation_results TO graphrec_app")
    op.execute("ALTER TABLE recommendation_feedback ADD COLUMN recommendation_result_id uuid REFERENCES recommendation_results(id)")
    op.execute("""
      UPDATE recommendation_feedback f SET recommendation_result_id = r.id
      FROM recommendation_results r
      WHERE f.tenant_id = r.tenant_id AND f.request_id = r.request_id
        AND f.feedback_type IN ('click', 'conversion')
        AND f.payload->>'external_product_id' = r.external_product_id
        AND (f.payload->>'position' IS NULL OR (f.payload->>'position')::integer = r.rank_position)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE recommendation_feedback DROP COLUMN recommendation_result_id")
    op.execute("DROP TABLE recommendation_results")
