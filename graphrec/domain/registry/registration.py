"""Turning a finished run into a version, in two deliberate steps.

`registered`, then `eligible` or `rejected`. One statement could do both, and
the reason not to is that the two facts have different authors: the *row* is
what the training run produced, and the *status* is what the floor decided about
it. Writing them together would make a floor change look like a retrospective
edit of what was trained. Written apart, a version that exists but has not been
judged is a state the schema can hold — which is exactly what a crash between
the two leaves behind, and what the resumed attempt then finishes.

**Registration is idempotent on the training job.** `uq_model_versions_job`
allows one version per run, so a retried `registering` stage finds the row its
predecessor wrote and completes the judgement rather than inserting a second
version of the same model. The same obligation `dataset_snapshots` has, for the
same reason: a stage that runs twice must leave what one run of it would.

**The version number is allocated under the row's own unique constraint.**
`max(version_number) + 1` has a race; `uq_model_versions_number` catches it, and
the caller retries. That is the correct place for the check — a sequence would
be per-table rather than per-model, and an advisory lock would serialise every
tenant's registration behind one another's.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import ModelVersionStatus
from graphrec.common.ids import uuid7
from graphrec.domain.registry import lifecycle
from graphrec.domain.registry.service import (
    SPLIT_BASELINE,
    SPLIT_TEST,
    as_decimal,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

#: What `model_versions.metrics` holds — the four measures the list page renders
#: without a join (L1730). The rows in `model_evaluation_metrics` remain the
#: record; this is a denormalised copy and is never read for a decision.
HEADLINE_METRICS = ("recall_at_10", "hit_rate_at_10", "ndcg_at_10", "coverage")


@dataclass(frozen=True, slots=True)
class Registration:
    """Everything the registry needs that the pipeline knows."""

    model_version_id: uuid.UUID
    model_id: uuid.UUID
    training_job_id: uuid.UUID
    snapshot_id: uuid.UUID
    artifact_uri: str
    artifact_digest: str
    feature_contract: dict[str, object]
    embedding_dim: int
    measured: Mapping[str, float]
    baseline: Mapping[str, float]


async def existing_version(
    session: AsyncSession, *, training_job_id: uuid.UUID
) -> tuple[uuid.UUID, str] | None:
    """This run's version, if a previous attempt already registered one."""
    row = (
        await session.execute(
            sa.text(
                "SELECT model_version_id, status FROM model_versions "
                " WHERE training_job_id = :training_job_id"
            ),
            {"training_job_id": training_job_id},
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


async def register(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    registration: Registration,
    floor: lifecycle.MetricFloor | None = None,
    now: dt.datetime | None = None,
) -> tuple[uuid.UUID, lifecycle.Verdict]:
    """Insert the version and its metrics, then apply the floor.

    Returns the version identifier and the verdict, so the caller can record
    both in the job's progress without reading the row back.
    """
    verdict = lifecycle.judge(registration.measured, registration.baseline, floor)
    existing = await existing_version(session, training_job_id=registration.training_job_id)

    if existing is None:
        await _insert_version(
            session,
            tenant_id=tenant_id,
            registration=registration,
            version_number=await next_version_number(session, model_id=registration.model_id),
            now=now or dt.datetime.now(dt.UTC),
        )
        version_id = registration.model_version_id
    else:
        version_id, _status = existing

    await _insert_metrics(
        session, tenant_id=tenant_id, version_id=version_id, registration=registration
    )
    await _apply_verdict(session, version_id=version_id, verdict=verdict)
    return version_id, verdict


async def next_version_number(session: AsyncSession, *, model_id: uuid.UUID) -> int:
    """One more than the highest this model has had, archived ones included.

    Archived versions still count. Reusing a number that a tenant has an audit
    record of would make two different artifacts share one name, and the row
    that would have caught it has been kept precisely so history stays
    queryable.
    """
    highest = await session.scalar(
        sa.text("SELECT max(version_number) FROM model_versions WHERE model_id = :model_id"),
        {"model_id": model_id},
    )
    return int(highest or 0) + 1


async def _insert_version(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    registration: Registration,
    version_number: int,
    now: dt.datetime,
) -> None:
    """`registered`, always. The floor has not spoken yet."""
    await session.execute(
        sa.text(
            "INSERT INTO model_versions "
            "  (model_version_id, tenant_id, model_id, version_number, status, "
            "   training_job_id, snapshot_id, artifact_uri, artifact_digest, "
            "   feature_contract, embedding_dim, metrics, created_at) "
            "VALUES (:model_version_id, :tenant_id, :model_id, :version_number, :status, "
            "        :training_job_id, :snapshot_id, :artifact_uri, :artifact_digest, "
            "        CAST(:feature_contract AS jsonb), :embedding_dim, "
            "        CAST(:metrics AS jsonb), :created_at)"
        ).bindparams(
            sa.bindparam("feature_contract", value=registration.feature_contract, type_=sa.JSON),
            sa.bindparam("metrics", value=_headline(registration.measured), type_=sa.JSON),
        ),
        {
            "model_version_id": registration.model_version_id,
            "tenant_id": tenant_id,
            "model_id": registration.model_id,
            "version_number": version_number,
            "status": ModelVersionStatus.REGISTERED.value,
            "training_job_id": registration.training_job_id,
            "snapshot_id": registration.snapshot_id,
            "artifact_uri": registration.artifact_uri,
            "artifact_digest": registration.artifact_digest,
            "embedding_dim": registration.embedding_dim,
            "created_at": now,
        },
    )


async def _insert_metrics(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    registration: Registration,
) -> None:
    """Both splits, with a repeat ignored.

    `ON CONFLICT DO NOTHING` rather than an upsert, because there is no `UPDATE`
    grant on this table and a resumed run re-measuring what it already recorded
    should keep the original measurement rather than fail on it.
    """
    rows = [
        {
            "metric_id": uuid7(),
            "tenant_id": tenant_id,
            "model_version_id": version_id,
            "split": split,
            "metric_name": name,
            "value": as_decimal(value),
        }
        for split, values in (
            (SPLIT_TEST, registration.measured),
            (SPLIT_BASELINE, registration.baseline),
        )
        for name, value in values.items()
    ]
    if not rows:
        return
    await session.execute(
        sa.text(
            "INSERT INTO model_evaluation_metrics "
            "  (metric_id, tenant_id, model_version_id, split, metric_name, value) "
            "VALUES (:metric_id, :tenant_id, :model_version_id, :split, :metric_name, :value) "
            "ON CONFLICT (model_version_id, split, metric_name) DO NOTHING"
        ),
        rows,
    )


async def _apply_verdict(
    session: AsyncSession, *, version_id: uuid.UUID, verdict: lifecycle.Verdict
) -> None:
    """The second step, and the only column pair the app may write.

    Guarded on `status = 'registered'`. A version that has since been activated,
    rejected by a later floor or archived is not something a re-run of this
    stage may reset — and a retry after a crash *between* the two steps finds
    the row exactly as it left it, which is the case the guard is for.
    """
    await session.execute(
        sa.text(
            "UPDATE model_versions SET status = :status, failure_note = :failure_note "
            " WHERE model_version_id = :model_version_id AND status = :registered"
        ),
        {
            "status": verdict.status.value,
            "failure_note": verdict.note,
            "model_version_id": version_id,
            "registered": ModelVersionStatus.REGISTERED.value,
        },
    )


def _headline(measured: Mapping[str, float]) -> dict[str, float]:
    return {name: float(measured[name]) for name in HEADLINE_METRICS if name in measured}


__all__ = [
    "HEADLINE_METRICS",
    "Registration",
    "existing_version",
    "next_version_number",
    "register",
]
