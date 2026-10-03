"""Enforce tenant ownership in the direct feedback-to-result foreign key."""

from alembic import op

revision = "0025_result_feedback_tenant_fk"
down_revision = "0024_recommendation_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recommendation_results ADD CONSTRAINT uq_recommendation_result_tenant_id UNIQUE (tenant_id, id)")
    op.execute("ALTER TABLE recommendation_feedback DROP CONSTRAINT recommendation_feedback_recommendation_result_id_fkey")
    op.execute("""
      ALTER TABLE recommendation_feedback
      ADD CONSTRAINT fk_recommendation_feedback_result_tenant
      FOREIGN KEY (tenant_id, recommendation_result_id)
      REFERENCES recommendation_results(tenant_id, id)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE recommendation_feedback DROP CONSTRAINT fk_recommendation_feedback_result_tenant")
    op.execute("""
      ALTER TABLE recommendation_feedback
      ADD CONSTRAINT recommendation_feedback_recommendation_result_id_fkey
      FOREIGN KEY (recommendation_result_id) REFERENCES recommendation_results(id)
    """)
    op.execute("ALTER TABLE recommendation_results DROP CONSTRAINT uq_recommendation_result_tenant_id")
