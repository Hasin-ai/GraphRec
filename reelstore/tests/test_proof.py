"""Unit and integration tests for the capability proof battery (P1-P19) and proof API routes."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.graphrec import build_local
from app.main import create_app
from app.proof.battery import ProofBattery
from app.proof.runner import get_latest_proof_report, run_proof_battery
from app.proof.schemas import ProofReport
from tests.test_phase1 import FakeGraphRecExtended


@pytest.fixture
def test_app():
    cfg = Settings(
        graphrec_api_key="gr_live_proof_test_key",
        reel_secret_key="dev-secret-key-proof-testing-minimum32",
        reel_env="development",
    )
    fake_client = FakeGraphRecExtended()
    svc = build_local(cfg, fake_client)
    return create_app(settings=cfg, svc=svc)


@pytest.mark.asyncio
async def test_proof_battery_synthetic_execution():
    cfg = Settings(
        graphrec_api_key="gr_live_proof_test_key",
        reel_secret_key="dev-secret-key-proof-testing-minimum32",
        reel_env="development",
    )
    fake_client = FakeGraphRecExtended()
    svc = build_local(cfg, fake_client)

    battery = ProofBattery(svc, run_id="proof-test-run")
    checks = await battery.run_all()
    assert len(checks) == 19
    check_ids = [c.id for c in checks]
    assert check_ids == [f"P{i}" for i in range(1, 20)]

    report = await run_proof_battery(svc, profile="tiny")
    assert isinstance(report, ProofReport)
    assert report.summary.total_checks == 19
    assert report.summary.passed_checks >= 15
    assert get_latest_proof_report() is not None


@pytest.mark.asyncio
async def test_proof_api_routes(test_app):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger proof battery via API
        run_res = await client.post("/api/reel/proof/run", json={"profile": "tiny"})
        assert run_res.status_code == 200
        run_data = run_res.json()["data"]
        assert run_data["summary"]["total_checks"] == 19
        assert len(run_data["checks"]) == 19

        # Retrieve latest proof report via API
        latest_res = await client.get("/api/reel/proof/latest")
        assert latest_res.status_code == 200
        latest_data = latest_res.json()["data"]
        assert latest_data["summary"]["run_id"] == run_data["summary"]["run_id"]
        assert latest_data["summary"]["total_checks"] == 19
