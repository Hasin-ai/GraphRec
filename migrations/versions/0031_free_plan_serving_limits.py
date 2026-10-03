"""D16: free-plan serving limits 8 concurrent slots, 120 requests/minute, 1 replica.

Plan limits stay data (``pricing_plans.limits``) and can be changed per plan by
the platform operator (``PUT /v1/platform/plans/{id}``); tenant overrides still
apply on top. Tenant quota snapshots on the free plan are updated the same way
``platform_update_plan`` propagates a plan edit.
"""

from alembic import op

revision = "0031_free_plan_serving_limits"
down_revision = "0030_tenant_name_uniqueness"
branch_labels = None
depends_on = None

FREE_PLAN_ID = "00000000-0000-4000-8000-000000000001"


def _apply(values: str) -> None:
    op.execute(f"""
      UPDATE public.pricing_plans SET limits = limits || '{values}'::jsonb
      WHERE id = '{FREE_PLAN_ID}'
    """)
    op.execute(f"""
      UPDATE public.tenant_resource_quotas q SET limits = q.limits || '{values}'::jsonb
      FROM public.tenant_subscriptions s
      WHERE s.tenant_id = q.tenant_id AND s.plan_id = '{FREE_PLAN_ID}'
    """)


def upgrade() -> None:
    _apply('{"concurrent_recommendation_requests": 8, "requests_per_minute": 120, "maximum_inference_replicas": 1}')


def downgrade() -> None:
    _apply('{"concurrent_recommendation_requests": 4, "requests_per_minute": 60, "maximum_inference_replicas": 1}')
