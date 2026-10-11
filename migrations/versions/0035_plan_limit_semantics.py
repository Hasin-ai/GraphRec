"""D-11 (approved 2026-10-08): plan limits that say what they enforce.

* ``concurrent_training_jobs`` on Pro becomes 1: BRULE-06 allows one active
  training request per tenant, and the platform runs one CPU trainer.
* ``queued_messages`` is removed: batches are applied synchronously and there is
  no tenant message queue to bound.
* ``active_model_versions`` keeps its values but now counts retained (non-archived)
  versions, enforced when a version is created (code change, no data change).
* ``maximum_training_duration_minutes`` keeps its values and is now enforced by
  the worker (capped by the local worker budget).
"""

from alembic import op

revision = "0035_plan_limit_semantics"
down_revision = "0034_audit_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE public.pricing_plans SET limits = limits - 'queued_messages'")
    op.execute("UPDATE public.tenant_resource_quotas SET limits = limits - 'queued_messages', "
               "overrides = overrides - 'queued_messages'")
    op.execute("""UPDATE public.pricing_plans SET limits = limits || '{"concurrent_training_jobs": 1}'::jsonb
                  WHERE code = 'pro'""")
    op.execute("""UPDATE public.tenant_resource_quotas q SET limits = q.limits || '{"concurrent_training_jobs": 1}'::jsonb
                  FROM public.tenant_subscriptions s JOIN public.pricing_plans p ON p.id = s.plan_id
                  WHERE s.tenant_id = q.tenant_id AND p.code = 'pro'""")


def downgrade() -> None:
    for code, queued in (("free", 500), ("basic", 5000), ("pro", 50000)):
        op.execute(f"""UPDATE public.pricing_plans SET limits = limits || '{{"queued_messages": {queued}}}'::jsonb
                       WHERE code = '{code}'""")
        op.execute(f"""UPDATE public.tenant_resource_quotas q SET limits = q.limits || '{{"queued_messages": {queued}}}'::jsonb
                       FROM public.tenant_subscriptions s JOIN public.pricing_plans p ON p.id = s.plan_id
                       WHERE s.tenant_id = q.tenant_id AND p.code = '{code}'""")
    op.execute("""UPDATE public.pricing_plans SET limits = limits || '{"concurrent_training_jobs": 2}'::jsonb
                  WHERE code = 'pro'""")
