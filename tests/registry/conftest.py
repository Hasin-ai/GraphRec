"""Fixtures for the registry suite.

A `model_versions` row cannot be conjured: it points at a training run, a
snapshot and a model, all three with `RESTRICT` behind them. So this seeds the
chain the way training would have left it — a settled `jobs` row, a
`training_jobs` row over it, a snapshot, and then the version — rather than
mocking the repository the routes read through. That matters here more than it
usually would, because half of what this phase claims is enforced by the
schema: the partial unique index on one active version, the archived/archived_at
biconditional, the failure-note rule. A fake store would pass all three.

The tenants, the app and the tokens are the authorization suite's, so gate 4 is
tested against the same policies every other suite is tested against.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from graphrec.common.enums import ModelVersionStatus
from tests.authz.conftest import (  # noqa: F401
    api,
    home_admin,
    home_dev,
    other_admin,
    realm,
    seed_engine,
)
from tests.ingestion.conftest import (  # noqa: F401
    _app_url,
    _empty_ingestion,
    bound,
    ingest_sessionmaker,
)
from tests.training.conftest import _empty_training  # noqa: F401

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

pytestmark = [pytest.mark.db]

#: Fixed, so an ordering assertion is about `version_number` rather than about
#: how fast the machine inserted four rows.
NOW = dt.datetime(2026, 8, 20, 11, 0, tzinfo=dt.UTC)

DIGEST = "sha256:" + "ab" * 32

#: What a run of the pipeline would have measured. Distinct per measure so a
#: test that read the wrong column would see the wrong number rather than a
#: number that happened to match.
MEASURED = {
    "recall_at_10": 0.214,
    "hit_rate_at_10": 0.331,
    "ndcg_at_10": 0.187,
    "coverage": 0.612,
}
BASELINE = {
    "recall_at_10": 0.151,
    "hit_rate_at_10": 0.240,
    "ndcg_at_10": 0.129,
    "coverage": 0.442,
}


@pytest.fixture
def home(realm) -> uuid.UUID:  # noqa: F811
    tenant_id = realm["home"]["tenant_id"]
    assert isinstance(tenant_id, uuid.UUID)
    return tenant_id


@pytest.fixture
def away(realm) -> uuid.UUID:  # noqa: F811
    """The realm's second active tenant — the one gate 4 must keep out."""
    tenant_id = realm["other"]["tenant_id"]
    assert isinstance(tenant_id, uuid.UUID)
    return tenant_id


@pytest.fixture
def registry(api, _empty_training) -> TestClient:  # noqa: F811
    """The authorization suite's app, with the registry emptied first.

    Nothing here needs its own `Settings`: the registry has no knobs, which is
    itself worth noticing — the metric floor is applied at registration, and by
    the time a version is a row the verdict has already been reached.
    """
    return api


@pytest.fixture
def seed_version(bound):  # noqa: F811
    """One version, with the run and snapshot it came from.

    Returns the version id. `model_id` is reused across calls for the same
    tenant so version numbers share a numbering space, which is what makes
    "newest first" and the rollback-target arithmetic mean anything.
    """

    async def _seed(
        tenant_id: uuid.UUID,
        *,
        version_number: int,
        status: ModelVersionStatus = ModelVersionStatus.ELIGIBLE,
        measured: dict[str, float] | None = None,
        baseline: dict[str, float] | None = None,
        failure_note: str | None = None,
    ) -> uuid.UUID:
        version_id = uuid.uuid4()
        async with bound(tenant_id) as session:
            model_id = await _model(session, tenant_id)
            job_id, training_job_id = await _run(session, tenant_id, model_id, version_number)
            snapshot_id = await _snapshot(session, tenant_id, training_job_id)
            await session.execute(
                sa.text(
                    "INSERT INTO model_versions (model_version_id, tenant_id, model_id, "
                    "    version_number, status, training_job_id, snapshot_id, artifact_uri, "
                    "    artifact_digest, feature_contract, embedding_dim, metrics, "
                    "    failure_note, created_at, archived_at) "
                    "VALUES (:vid, :tid, :mid, :n, :status, :job, :snap, :uri, :digest, "
                    "    CAST(:contract AS jsonb), 128, CAST(:metrics AS jsonb), :note, "
                    "    :created, :archived)"
                ),
                {
                    "vid": version_id,
                    "tid": tenant_id,
                    "mid": model_id,
                    "n": version_number,
                    "status": status.value,
                    "job": training_job_id,
                    "snap": snapshot_id,
                    "uri": f"s3://artifacts/{version_id}/bundle.safetensors",
                    "digest": DIGEST,
                    "contract": '{"features": ["sequence", "product", "category"]}',
                    "metrics": _json(measured or MEASURED),
                    "note": failure_note,
                    # Descending with the version number, so a test that ordered
                    # by timestamp instead of by number would get the same
                    # answer — and one that got them backwards would not.
                    "created": NOW + dt.timedelta(minutes=version_number),
                    "archived": (
                        NOW + dt.timedelta(hours=1)
                        if status is ModelVersionStatus.ARCHIVED
                        else None
                    ),
                },
            )
            for split, values in (
                ("test", measured or MEASURED),
                ("baseline", baseline or BASELINE),
            ):
                for metric, value in values.items():
                    await session.execute(
                        sa.text(
                            "INSERT INTO model_evaluation_metrics (tenant_id, model_version_id, "
                            "    split, metric_name, value) "
                            "VALUES (:tid, :vid, :split, :metric, :value)"
                        ),
                        {
                            "tid": tenant_id,
                            "vid": version_id,
                            "split": split,
                            "metric": metric,
                            "value": value,
                        },
                    )
        return version_id

    return _seed


def _json(values: dict[str, float]) -> str:
    import json

    return json.dumps(values)


async def _model(session, tenant_id: uuid.UUID) -> uuid.UUID:
    """The tenant's `default` model, created once and found thereafter."""
    found = await session.scalar(
        sa.text("SELECT model_id FROM models WHERE name = 'default' LIMIT 1")
    )
    if found is not None:
        assert isinstance(found, uuid.UUID)
        return found
    model_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO models (model_id, tenant_id, name, model_type) "
            "VALUES (:mid, :tid, 'default', 'DGSR')"
        ),
        {"mid": model_id, "tid": tenant_id},
    )
    return model_id


async def _run(
    session, tenant_id: uuid.UUID, model_id: uuid.UUID, version_number: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """A settled run. Settled rather than queued because the partial unique
    index in migration 0010 allows one active run per tenant, and these tests
    seed four versions."""
    job_id = uuid.uuid4()
    training_job_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO jobs (job_id, tenant_id, job_type, status, completed_at) "
            "VALUES (:jid, :tid, 'training', 'succeeded', now())"
        ),
        {"jid": job_id, "tid": tenant_id},
    )
    await session.execute(
        sa.text(
            "INSERT INTO training_jobs (training_job_id, tenant_id, job_id, model_id, "
            "    request_ref, state, interaction_window_days, max_epochs, requested_at, "
            "    completed_at) "
            "VALUES (:tjid, :tid, :jid, :mid, :ref, 'succeeded', 90, 20, :at, :at)"
        ),
        {
            "tjid": training_job_id,
            "tid": tenant_id,
            "jid": job_id,
            "mid": model_id,
            "ref": f"seed-{version_number}-{training_job_id.hex[:8]}",
            "at": NOW + dt.timedelta(minutes=version_number),
        },
    )
    return job_id, training_job_id


async def _snapshot(session, tenant_id: uuid.UUID, training_job_id: uuid.UUID) -> uuid.UUID:
    snapshot_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO dataset_snapshots (snapshot_id, tenant_id, training_job_id, cutoff_at, "
            "    window_days, uri, checksum, sequence_count, product_count, event_count) "
            "VALUES (:sid, :tid, :tjid, :at, 90, :uri, :checksum, 1200, 340, 9800)"
        ),
        {
            "sid": snapshot_id,
            "tid": tenant_id,
            "tjid": training_job_id,
            "at": NOW,
            "uri": f"s3://snapshots/{snapshot_id}/dataset.parquet",
            "checksum": DIGEST,
        },
    )
    return snapshot_id
