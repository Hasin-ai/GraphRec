"""ER-NF-01 / ER-NF-05 (A-21): real worker processes, real signals.

* SIGKILL mid-batch: the accepted job survives in durable state, is reclaimed
  once its heartbeat is stale, and completes on the retry.
* SIGTERM mid-batch: the worker hands the job back without spending an attempt.
* Deterministic failures terminate visibly at once; transient ones retry once.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text

from graphrec_core.database.models import TrainingJob
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.dgsr import worker
from tests.integration.test_srs_acceptance import limits, provision
from tests.integration.test_training_worker import isolated_training_queue, seed  # noqa: F401

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _job(tenant, job_id) -> TrainingJob:
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        job = db.get(TrainingJob, UUID(job_id))
        db.expunge(job)
        return job


def _seed_larger(client, headers):
    """Enough history that a 10-epoch run lasts long enough to be interrupted mid-batch."""
    products = [{"external_id": str(i), "title": f"Item {i}"} for i in range(30)]
    assert client.post("/v1/products:bulk-upsert", json={"products": products}, headers=headers).status_code == 200
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [{"event_id": f"{u}-{i}", "event_type": "view", "user_id": f"u{u}", "external_product_id": str((i * 7 + u) % 30),
               "occurred_at": (start + timedelta(seconds=u * 40 + i)).isoformat()} for u in range(40) for i in range(12)]
    assert client.post("/v1/events/batches", json={"events": events}, headers=headers).status_code == 200


def _queue(client, epochs=10):
    tenant, headers = provision(client)
    limits(client, tenant, training_jobs=5, accepted_events=100_000)
    if epochs > 1:
        _seed_larger(client, headers)
    else:
        seed(client, headers)
    response = client.post("/v1/training-jobs", json={"configuration": {"mode": "train", "epochs": epochs}},
                           headers=headers)
    assert response.status_code == 200, response.text
    return tenant, response.json()["id"]


def _start_worker(tmp_path):
    env = {**os.environ, "GENERATED_MODEL_ROOT": str(tmp_path), "PYTHONPATH": str(ROOT)}
    return subprocess.Popen([sys.executable, "-m", "graphrec_core.dgsr.worker"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait(predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def test_er_nf_01_killed_worker_job_is_reclaimed_and_completes(client, tmp_path):
    tenant, job_id = _queue(client)
    process = _start_worker(tmp_path)
    try:
        _wait(lambda: _job(tenant, job_id).stage in {"training", "evaluating_validation"})
        process.send_signal(signal.SIGKILL)  # abrupt: no handler runs
        process.wait(10)
    finally:
        if process.poll() is None:
            process.kill()
    killed = _job(tenant, job_id)
    assert killed.status == "running" and killed.attempts == 1
    # The worker's heartbeat would go stale after 5 minutes; age it instead of waiting.
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        db.get(TrainingJob, UUID(job_id)).heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    # The global CPU lock was released with the dead process: a new worker starts.
    process = _start_worker(tmp_path)
    try:
        done = _wait(lambda: _job(tenant, job_id).status in {"succeeded", "failed"} and _job(tenant, job_id), 120)
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(30)
    assert done.status == "succeeded", done.failure_reason
    assert done.attempts == 2


def test_er_nf_01_sigterm_requeues_without_spending_an_attempt(client, tmp_path):
    tenant, job_id = _queue(client)
    process = _start_worker(tmp_path)
    try:
        _wait(lambda: _job(tenant, job_id).stage in {"training", "evaluating_validation"})
        process.send_signal(signal.SIGTERM)
        assert process.wait(30) == 0
    finally:
        if process.poll() is None:
            process.kill()
    job = _job(tenant, job_id)
    assert (job.status, job.stage, job.attempts) == ("queued", "requeued_on_shutdown", 0)
    assert not (tmp_path / tenant / job_id).exists()


def test_er_nf_05_deterministic_failure_is_terminal_and_visible(client, tmp_path, monkeypatch):
    monkeypatch.setattr(worker.get_settings(), "generated_model_root", str(tmp_path))
    tenant, job_id = _queue(client, epochs=1)

    def broken(*_args):
        raise ValueError("Held-out validation and test examples are required.")

    monkeypatch.setattr(worker, "train_job", broken)
    assert worker.run_once()
    job = _job(tenant, job_id)
    assert job.status == "failed" and "deterministic failure" in job.failure_reason
    with SessionLocal() as db:
        assert db.execute(text("SELECT * FROM public.claim_training_job()")).first() is None
        db.rollback()


def test_er_nf_05_transient_failure_retries_once_then_fails(client, tmp_path, monkeypatch):
    monkeypatch.setattr(worker.get_settings(), "generated_model_root", str(tmp_path))
    tenant, job_id = _queue(client, epochs=1)

    def unavailable(*_args):
        raise ConnectionError("vector store unreachable")

    monkeypatch.setattr(worker, "train_job", unavailable)
    assert worker.run_once()
    first = _job(tenant, job_id)
    assert (first.status, first.stage, first.attempts) == ("queued", "retry_scheduled", 1)
    assert worker.run_once()
    second = _job(tenant, job_id)
    assert second.status == "failed" and second.attempts == 2
    assert "retry budget exhausted" in second.failure_reason


def test_transient_classification():
    from sqlalchemy.exc import OperationalError
    assert worker.is_transient(ConnectionError())
    assert worker.is_transient(TimeoutError())
    assert worker.is_transient(OperationalError("SELECT 1", {}, Exception("server closed")))
    assert not worker.is_transient(ValueError("bad data"))
    assert not worker.is_transient(KeyError("x"))
