from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from graphrec_core.schemas.datasets import DatasetSnapshotCreate
from graphrec_core.schemas.models import TrainingJobCreate

client = TestClient(app)


def test_dataset_snapshot_schema() -> None:
    snap_req = DatasetSnapshotCreate(description="Test snapshot")
    assert snap_req.description == "Test snapshot"


def test_training_job_with_dataset_snapshot_schema() -> None:
    snap_id = uuid4()
    job_req = TrainingJobCreate(
        model_type="simplified_dgsr",
        dataset_snapshot_id=snap_id,
        configuration={"epochs": 10},
    )
    assert job_req.model_type == "simplified_dgsr"
    assert job_req.dataset_snapshot_id == snap_id


@pytest.mark.integration
def test_tenant_registration_and_setup_password() -> None:
    unique_id = str(uuid4())[:8]
    email = f"admin-pwd-{unique_id}@test.example"
    reg_resp = client.post(
        "/v1/tenants",
        json={"name": f"Test Password Tenant {unique_id}", "admin_email": email},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert reg_resp.status_code == 201
    setup_token = reg_resp.json()["setup_token"]

    # Knowing the email address alone is not enough to claim the account.
    email_only = client.post(
        "/v1/auth/setup-password",
        json={"email": email, "password": "TestPassword123!"},
    )
    assert email_only.status_code == 422

    pwd_resp = client.post(
        "/v1/auth/setup-password",
        json={"setup_token": setup_token, "password": "TestPassword123!"},
    )
    assert pwd_resp.status_code == 200
    data = pwd_resp.json()
    assert "access_token" in data
    assert data["user_role"] == "tenant_administrator"

