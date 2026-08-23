"""The registry's read paths, and the one write a tenant can make.

Four routes' worth of behaviour (BACKEND_PLAN §12.8): the list behind `/models`,
the five stat cards above it, the detail page with its three-way comparison, and
`:archive`. Activation and rollback are Phase 11 — they change what serves, and
what serves is a deployment rather than a row.

**The comparison is three-way because the decision is** (XR-F-10, UC-17). A
tenant deciding whether to activate version 7 is asking two questions at once:
is it better than recommending the top sellers, and is it better than what is
serving now. The prototype renders both deltas in one table (L1752-1756), so the
endpoint returns both columns; computing either client-side would mean loading
every version to find the active one.

**Archiving deletes bytes and keeps the row.** History stays queryable
(BACKEND_PLAN L1168): the metrics of a version archived last quarter are how a
tenant reads this quarter's numbers. What goes is the artifact — and the
candidate index built from it, which is §6.3's "collection deleted on archive"
honoured by the in-process adapter (ADR 0026).

**The rollback-target protection is enforced here rather than by a constraint.**
"The retired version immediately preceding the active one" is a question about
another row, and a check constraint cannot see one. It is pinned by a test
instead, which is the honest arrangement: the rule lives where it can be read.
"""

from __future__ import annotations

import datetime as dt
import decimal
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.enums import ModelVersionStatus
from graphrec.common.errors import ConflictError, NotFoundError
from graphrec.common.logging import get_logger
from graphrec.db.models import Model, ModelEvaluationMetric, ModelVersion
from graphrec.domain.registry import lifecycle
from graphrec.storage import keys

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.ml.index import CandidateIndex
    from graphrec.storage.store import ArtifactStore

logger = get_logger(__name__)

#: The four measures the comparison table draws (L1752-1755), in the order it
#: draws them. A dictionary would be enough for the wire, but the order is part
#: of the specification and a set would lose it.
COMPARISON_METRICS = ("recall_at_10", "hit_rate_at_10", "ndcg_at_10", "coverage")

#: `model_evaluation_metrics.split`. `TEST` is the version's own number, and
#: `BASELINE` is the popularity ranker over the same held-out rows — not a data
#: split, and the column name is a small abuse for the sake of one table rather
#: than two (migration 0011's docstring argues it).
SPLIT_TEST = "test"
SPLIT_BASELINE = "baseline"
SPLIT_VALIDATION = "validation"

#: The five cards above `/models` (L1737). `desired` is the count of versions a
#: tenant *intends* to serve, which is one whenever anything is active or
#: eligible — the deployment's own desired-replica count is Phase 11's and lives
#: on a different resource.
SUMMARY_STATUSES = (
    ModelVersionStatus.ACTIVE,
    ModelVersionStatus.ELIGIBLE,
    ModelVersionStatus.RETIRED,
    ModelVersionStatus.FAILED_DEPLOYMENT,
)


@dataclass(frozen=True, slots=True)
class VersionSummary:
    """The five stat cards, as numbers rather than as a rendering."""

    active: int
    desired: int
    eligible: int
    retired: int
    failed_deployment: int

    def as_dict(self) -> dict[str, int]:
        return {
            "active": self.active,
            "desired": self.desired,
            "eligible": self.eligible,
            "retired": self.retired,
            "failed_deployment": self.failed_deployment,
        }


class RegistryService:
    """Reads over `model_versions`, and archive.

    The artifact store and the candidate index are optional. A control-plane
    process that only ever reads has no business holding either, and requiring
    them would make every read path construct an S3 client to list five rows.
    `archive` is the one method that needs them, and it says so.
    """

    def __init__(
        self,
        *,
        store: ArtifactStore | None = None,
        index: CandidateIndex | None = None,
    ) -> None:
        self._store = store
        self._index = index

    # ------------------------------------------------------------------ reads

    async def get(self, session: AsyncSession, *, version_id: uuid.UUID) -> ModelVersion:
        """Gate 4. Another tenant's version is invisible under the policy, so a
        missing row and a foreign one are the same `404` — a `403` would confirm
        that it exists."""
        version = await session.get(ModelVersion, version_id)
        if version is None:
            raise NotFoundError("not_found")
        return version

    async def list_versions(
        self,
        session: AsyncSession,
        *,
        status: ModelVersionStatus | None = None,
        limit: int = 50,
    ) -> list[ModelVersion]:
        """The `/models` table, newest version first (L1726).

        Ordered by `version_number` rather than by `created_at`. They agree
        today, and the number is the thing the page shows: a table sorted by a
        timestamp that renders a number is a table that can appear misordered
        for reasons the reader cannot see.
        """
        query = sa.select(ModelVersion).order_by(ModelVersion.version_number.desc()).limit(limit)
        if status is not None:
            query = query.where(ModelVersion.status == status.value)
        return list((await session.scalars(query)).all())

    async def summary(self, session: AsyncSession) -> VersionSummary:
        """One grouped count, not five. Under RLS the whole table is the
        tenant's, so this is a single scan of a small relation."""
        rows = (
            await session.execute(
                sa.select(ModelVersion.status, sa.func.count())
                .group_by(ModelVersion.status)
                .select_from(ModelVersion)
            )
        ).all()
        counts = {status: int(count) for status, count in rows}
        active = counts.get(ModelVersionStatus.ACTIVE.value, 0)
        eligible = counts.get(ModelVersionStatus.ELIGIBLE.value, 0)
        return VersionSummary(
            active=active,
            # A tenant with something to serve wants one version serving. Zero
            # when there is neither an active nor an eligible version, because
            # "desired 1, active 0" beside an empty registry would read as a
            # fault rather than as a tenant who has not trained yet.
            desired=1 if active or eligible else 0,
            eligible=eligible,
            retired=counts.get(ModelVersionStatus.RETIRED.value, 0),
            failed_deployment=counts.get(ModelVersionStatus.FAILED_DEPLOYMENT.value, 0),
        )

    async def active_version(self, session: AsyncSession) -> ModelVersion | None:
        """At most one, guaranteed by the partial unique index."""
        found: ModelVersion | None = await session.scalar(
            sa.select(ModelVersion).where(ModelVersion.status == ModelVersionStatus.ACTIVE.value)
        )
        return found

    async def context(self, session: AsyncSession) -> lifecycle.VersionContext:
        """The two facts every gate-5 predicate needs, read once."""
        active = await self.active_version(session)
        has_retired = bool(
            await session.scalar(
                sa.select(sa.literal(1))
                .select_from(ModelVersion)
                .where(ModelVersion.status == ModelVersionStatus.RETIRED.value)
                .limit(1)
            )
        )
        return lifecycle.VersionContext(
            active_number=active.version_number if active else None,
            has_retired=has_retired,
        )

    async def metrics_for(
        self, session: AsyncSession, *, version_ids: Sequence[uuid.UUID]
    ) -> dict[tuple[uuid.UUID, str], dict[str, float]]:
        """`(version, split) -> {metric: value}`, for however many versions.

        Batched because the detail page needs two versions' numbers — this one
        and the active one — and two round trips for one table is two chances
        for them to disagree about what is active.
        """
        if not version_ids:
            return {}
        rows = (
            await session.scalars(
                sa.select(ModelEvaluationMetric).where(
                    ModelEvaluationMetric.model_version_id.in_(list(version_ids))
                )
            )
        ).all()
        out: dict[tuple[uuid.UUID, str], dict[str, float]] = {}
        for row in rows:
            out.setdefault((row.model_version_id, row.split), {})[row.metric_name] = float(
                row.value
            )
        return out

    async def model_type(self, session: AsyncSession, *, model_id: uuid.UUID) -> str:
        """The family name the detail page renders (L1771).

        Read from `models` rather than stored on the version: a version belongs
        to a model, and copying the type onto it would create a second place for
        it to be wrong.
        """
        found: str | None = await session.scalar(
            sa.select(Model.model_type).where(Model.model_id == model_id)
        )
        return found or "DGSR"

    async def detail(self, session: AsyncSession, *, version_id: uuid.UUID) -> dict[str, Any]:
        """The whole `/models/:versionId` page, in one response.

        `active_comparison` is `None` when nothing is active or when *this* is
        the active version. The prototype renders an em-dash in that column
        (L1756), which is a client's rendering of an absent value rather than a
        value the server should invent — and comparing a version against itself
        would fill four columns with zeroes that mean nothing.
        """
        version = await self.get(session, version_id=version_id)
        context = await self.context(session)
        active = await self.active_version(session)

        wanted = [version.model_version_id]
        if active is not None and active.model_version_id != version.model_version_id:
            wanted.append(active.model_version_id)
        measured = await self.metrics_for(session, version_ids=wanted)

        own = measured.get((version.model_version_id, SPLIT_TEST), {})
        baseline = measured.get((version.model_version_id, SPLIT_BASELINE), {})
        comparison: dict[str, Any] | None = None
        if active is not None and active.model_version_id != version.model_version_id:
            comparison = {
                "version_number": active.version_number,
                **_measures(measured.get((active.model_version_id, SPLIT_TEST), {})),
            }

        status = version.version_status
        return {
            "version_id": version.model_version_id,
            "version_number": version.version_number,
            "model_id": version.model_id,
            "model_type": await self.model_type(session, model_id=version.model_id),
            "status": version.status,
            "created_at": version.created_at,
            "archived_at": version.archived_at,
            "training_job_id": version.training_job_id,
            "metrics": _measures(own),
            "baseline": _measures(baseline),
            "active_comparison": comparison,
            "artifact": {
                "digest": version.artifact_digest,
                "uri": version.artifact_uri,
                "snapshot_id": version.snapshot_id,
                "feature_contract": render_contract(version.feature_contract),
                "embedding_dim": version.embedding_dim,
            },
            "eligible": version.is_eligible(),
            "failure_note": version.failure_note,
            "actions": {
                "activate": lifecycle.can_activate(status).as_dict(),
                "rollback": lifecycle.can_rollback(status, context).as_dict(),
                "archive": lifecycle.can_archive(status, version.version_number, context).as_dict(),
            },
        }

    # ----------------------------------------------------------------- writes

    async def archive(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        version_id: uuid.UUID,
        reason: str | None = None,
        now: dt.datetime | None = None,
    ) -> ModelVersion:
        """Retire the bytes, keep the record.

        The refusal and the console's disabled button come from the same
        `can_archive`, so a client that somehow issued the request anyway is
        told exactly what the button would have said. `409` in every refused
        case: none of them is a validation failure — the request is well formed
        and the registry's state is what forbids it.

        The bytes go before the row is updated. The other order would mark a
        version archived and then fail to delete, leaving a row that says the
        artifact is gone beside an artifact that is not; this order can leave an
        orphaned object, which a retention sweep can find and a tenant never
        sees.
        """
        version = await self.get(session, version_id=version_id)
        context = await self.context(session)
        decision = lifecycle.can_archive(version.version_status, version.version_number, context)
        if not decision.allowed:
            raise ConflictError(decision.code or "invalid_state")

        self._forget_artifact(tenant_id=tenant_id, version=version)

        version.status = ModelVersionStatus.ARCHIVED.value
        version.archived_at = now or dt.datetime.now(dt.UTC)
        await session.flush()
        logger.info(
            "model_version_archived",
            extra={
                "model_version_id": str(version.model_version_id),
                "version_number": version.version_number,
                # The tenant's own words, bounded by the schema. Phase 12 writes
                # this to `audit_logs`; until then it belongs in the log line
                # rather than nowhere.
                "reason_supplied": bool(reason),
            },
        )
        return version

    def _forget_artifact(self, *, tenant_id: uuid.UUID, version: ModelVersion) -> None:
        """Drop the index and delete the bundle, tolerating either being absent.

        A control-plane process constructed without a store or an index skips
        both. That is not a silent failure: it is the read-only deployment doing
        the part of the work it can do, and the artifact is then removed by the
        retention sweep that owns orphaned objects. Deleting is idempotent
        anyway, because an archive retried after a partial failure has not done
        anything wrong.
        """
        if self._index is not None:
            self._index.drop((tenant_id, version.model_version_id))
        if self._store is not None:
            from graphrec.ml.bundle import BUNDLE_NAME

            self._store.delete(keys.bundle_key(tenant_id, version.model_version_id, BUNDLE_NAME))


def render_contract(contract: Mapping[str, Any]) -> str:
    """The feature contract as the console renders it (L1758).

    The prototype shows `sequence · product · category · brand` — a sentence,
    not an object. The column is `jsonb` because Phase 11 compares contracts
    field by field before a swap, and this turns the stored object back into the
    line the page draws. Unknown keys are listed rather than dropped: a contract
    that grew a field should show it, not hide it behind a renderer that only
    knows last quarter's vocabulary.
    """
    features = contract.get("features")
    if isinstance(features, list) and features:
        return " · ".join(str(feature) for feature in features)
    return " · ".join(f"{key}={value}" for key, value in sorted(contract.items())) or "—"


def _measures(values: Mapping[str, float]) -> dict[str, float | None]:
    """The four comparison measures, in order, with absences kept as absences.

    `None` rather than `0.0` for a measure that was not recorded. Zero is a
    score, and a table that renders a missing coverage as 0.00 says the model
    recommended one item to everybody.
    """
    return {metric: values.get(metric) for metric in COMPARISON_METRICS}


def as_decimal(value: float) -> decimal.Decimal:
    """`numeric(18,6)`, quantised on the way in.

    So the number the console plots is the number the evaluator computed rather
    than the one PostgreSQL rounded it to on a later read — the same reason
    `training_metrics` quantises.
    """
    return decimal.Decimal(str(value)).quantize(decimal.Decimal("0.000001"))


__all__ = [
    "COMPARISON_METRICS",
    "SPLIT_BASELINE",
    "SPLIT_TEST",
    "SPLIT_VALIDATION",
    "RegistryService",
    "VersionSummary",
    "as_decimal",
    "render_contract",
]
