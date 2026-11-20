"""seed the Basic and Pro demonstration plans

SRS 2 "Provisional Demonstration Plan Limits" defines Free, Basic and Pro;
only Free existed. The extra dimensions (queued messages, storage, training
duration, concurrency) keep the Free plan's shape so quota code reads one
schema for every plan.

Revision ID: 0012_basic_pro_plans
Revises: 0011_event_user_history_index
Create Date: 2026-09-12
"""
from collections.abc import Sequence
from typing import Union
import json

from alembic import op

revision: str = "0012_basic_pro_plans"
down_revision: Union[str, None] = "0011_event_user_history_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLANS = {
    "basic": {
        "name": "Basic",
        "limits": {
            "accepted_events": 500_000,
            "recommendation_requests": 250_000,
            "requests_per_minute": 300,
            "concurrent_recommendation_requests": 12,
            "training_jobs": 4,
            "active_model_versions": 5,
            "maximum_inference_replicas": 2,
            "concurrent_training_jobs": 1,
            "maximum_training_duration_minutes": 60,
            "stored_products": 50_000,
            "queued_messages": 5_000,
            "artifact_storage_bytes": 5 * 1024**3,
        },
    },
    "pro": {
        "name": "Pro",
        "limits": {
            "accepted_events": 2_000_000,
            "recommendation_requests": 1_000_000,
            "requests_per_minute": 1_000,
            "concurrent_recommendation_requests": 30,
            "training_jobs": 12,
            "active_model_versions": 10,
            "maximum_inference_replicas": 3,
            "concurrent_training_jobs": 2,
            "maximum_training_duration_minutes": 180,
            "stored_products": 500_000,
            "queued_messages": 50_000,
            "artifact_storage_bytes": 20 * 1024**3,
        },
    },
}


def upgrade() -> None:
    for code, plan in PLANS.items():
        limits = json.dumps(plan["limits"]).replace("'", "''")
        op.execute(
            "INSERT INTO pricing_plans (id, code, name, limits, is_active) "
            f"VALUES (gen_random_uuid(), '{code}', '{plan['name']}', '{limits}'::jsonb, true) "
            "ON CONFLICT (code) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM pricing_plans WHERE code IN ('basic', 'pro')")
