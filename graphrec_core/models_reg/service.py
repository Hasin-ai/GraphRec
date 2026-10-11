from __future__ import annotations

import logging
import json
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from graphrec_core.database.models import AuditLog, CustomerEvent, DatasetSnapshot, DatasetSnapshotContent, ModelDeployment, ModelVersion, Product, TrainingJob, UsageEvent
from graphrec_core.usage.limits import require_capacity
from graphrec_core.feedback import payload_hash
from graphrec_core.errors import ApiError
from graphrec_core.schemas.models import (
    ModelVersionCreate,
    ModelVersionResource,
    TrainingJobCreate,
    TrainingJobResource,
)
from graphrec_core.settings import get_settings
from graphrec_core.vector_store.client import get_qdrant_client
from graphrec_core.vector_store.collections import collection_name, delete_collection
from graphrec_core.vector_store.indexer import index_item_embeddings

logger = logging.getLogger(__name__)

ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
#: Model type recorded for versions served by a real DGSR checkpoint.
DGSR_MODEL_TYPE = "dgsr"


def artifact_directory(artifact_uri: str | None) -> Path | None:
    """Resolve a ``file://`` artifact URI to a directory that exists."""
    if not artifact_uri or not artifact_uri.startswith("file://"):
        return None
    path = Path(artifact_uri[len("file://"):])
    return path if path.is_dir() else None


def validate_artifact_binding(directory: Path, tenant_id: UUID, checkpoint_sha256: str | None = None) -> None:
    """Bindings are provisioned by the operator, outside public API writes."""
    identity = json.loads((directory / "tenant_identity.json").read_text(encoding="utf-8"))
    public_reference = isinstance(identity.get("public_reference_dataset"), str) and bool(identity["public_reference_dataset"].strip())
    permitted = identity.get("tenant_id") == str(tenant_id) or str(tenant_id) in identity.get("tenant_ids", [])
    if not public_reference and not permitted:
        raise ValueError("Artifact is not provisioned for this tenant")
    expected = identity.get("checkpoint_sha256")
    if public_reference and not expected:
        raise ValueError("Public reference artifacts must pin their checkpoint digest")
    if checkpoint_sha256 is not None and expected and expected != checkpoint_sha256:
        raise ValueError("Artifact differs from its operator-provisioned identity")


class ModelRegistryService:
    def __init__(self, db: Session, principal=None, correlation_id: UUID | None = None):
        self.db = db
        self.principal = principal
        self.correlation_id = correlation_id or uuid4()

    def _audit(self, tenant_id: UUID, action: str, resource_id: UUID, *, outcome: str = "succeeded", details: dict | None = None) -> None:
        self.db.add(AuditLog(id=uuid4(), tenant_id=tenant_id,
            actor_type=self.principal.actor_type if self.principal else "system",
            actor_reference=self.principal.actor_reference if self.principal else None,
            action_type=action, resource_type="training_job" if action.startswith("training") else "model_version",
            resource_reference=resource_id, outcome=outcome, correlation_reference=self.correlation_id,
            redacted_details=details or {}, occurred_at=datetime.now(timezone.utc)))

    def register_model_version(
        self, tenant_id: UUID, payload: ModelVersionCreate
    ) -> ModelVersionResource:
        if get_settings().is_production:
            # A-02: tenants cannot assert their own model quality in production.
            raise ApiError(404, "resource_not_found", "The requested resource was not found")
        now = datetime.now(timezone.utc)
        existing = self.db.execute(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id,
                ModelVersion.version_tag == payload.version_tag,
            )
        ).scalar_one_or_none()

        if existing:
            raise ApiError(
                409,
                "duplicate_resource",
                f"Model version tag '{payload.version_tag}' already exists for this tenant.",
            )

        require_capacity(self.db, tenant_id, "active_model_versions")
        mv = ModelVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            version_tag=payload.version_tag,
            model_type=payload.model_type,
            status="eligible",
            metrics=payload.metrics,
            artifact_uri=payload.artifact_uri
            or f"unregistered://{tenant_id}/{payload.version_tag}",
            created_at=now,
        )
        self.db.add(mv)
        self._audit(tenant_id, "model_registered", mv.id)
        self.db.commit()

        return ModelVersionResource.model_validate(mv)

    def list_model_versions(self, tenant_id: UUID) -> list[ModelVersionResource]:
        items = (
            self.db.execute(
                select(ModelVersion)
                .where(ModelVersion.tenant_id == tenant_id)
                .order_by(ModelVersion.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [ModelVersionResource.model_validate(m) for m in items]

    def get_model_version(self, tenant_id: UUID, version_id: UUID) -> ModelVersionResource:
        mv = self.db.execute(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id, ModelVersion.id == version_id
            )
        ).scalar_one_or_none()

        if not mv:
            raise ApiError(404, "resource_not_found", f"Model version '{version_id}' not found.")

        return ModelVersionResource.model_validate(mv)

    def activate_model_version(self, tenant_id: UUID, version_id: UUID, *, rollback: bool = False) -> ModelVersionResource:
        now = datetime.now(timezone.utc)
        # Serialize all lifecycle transitions for a tenant before changing its
        # active pointer. Validation completes before the old version is retired.
        self._lock_lifecycle(tenant_id)
        target = self.db.execute(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id, ModelVersion.id == version_id
            )
        ).scalar_one_or_none()

        if not target:
            raise ApiError(404, "resource_not_found", f"Model version '{version_id}' not found.")

        if target.status == "active" and not rollback:
            return ModelVersionResource.model_validate(target)
        required_status = "retired" if rollback else "eligible"
        if target.status != required_status:
            raise ApiError(409, "model_not_eligible", f"The target must be {required_status} for this operation.")
        previous_active = self.db.scalar(select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id, ModelVersion.status == "active",
        ))
        try:
            self._validate_activation(tenant_id, target)
        except ApiError:
            self._set_deployment(tenant_id, desired=target.id,
                                 active=previous_active.id if previous_active else None,
                                 status="degraded", failure_reason="model_not_ready", at=now)
            self._audit(tenant_id, "model_rollback" if rollback else "model_activation", target.id,
                        outcome="failed", details={"reason": "model_not_ready"})
            self.db.commit()
            raise

        # Demote current active model to retired
        actives = (
            self.db.execute(
                select(ModelVersion).where(
                    ModelVersion.tenant_id == tenant_id, ModelVersion.status == "active"
                )
            )
            .scalars()
            .all()
        )
        for active in actives:
            active.status = "retired"

        self.db.flush()

        target.status = "active"
        target.activated_at = now
        self._set_deployment(tenant_id, desired=target.id, active=target.id,
                             status="available", failure_reason=None, at=now)
        self._audit(tenant_id, "model_rollback" if rollback else "model_activation", target.id,
                    details={"previous_version_ids": [str(active.id) for active in actives]})
        self.db.commit()

        return ModelVersionResource.model_validate(target)

    def _set_deployment(self, tenant_id: UUID, *, desired: UUID, active: UUID | None,
                        status: str, failure_reason: str | None, at: datetime) -> None:
        deployment = self.db.scalar(select(ModelDeployment).where(ModelDeployment.tenant_id == tenant_id))
        if deployment is None:
            deployment = ModelDeployment(id=uuid4(), tenant_id=tenant_id,
                                         desired_capacity=1, ready_capacity=0,
                                         last_transition_at=at, status=status)
            self.db.add(deployment)
        deployment.desired_model_version_id = desired
        deployment.active_model_version_id = active
        deployment.status = status
        # XR-NF-01: activation keeps the scaled capacity bound to the active version.
        deployment.ready_capacity = deployment.desired_capacity if active is not None else 0
        deployment.failure_reason = failure_reason
        deployment.last_transition_at = at

    def rollback_model(self, tenant_id: UUID, model_id: UUID) -> ModelVersionResource:
        return self.activate_model_version(tenant_id, model_id, rollback=True)

    def _lock_lifecycle(self, tenant_id: UUID) -> None:
        # Runtime credentials intentionally cannot update the tenants table.
        # Transaction-scoped advisory locks serialize transitions without
        # broadening those database privileges.
        import hashlib
        key = int.from_bytes(hashlib.sha256(f"lifecycle:{tenant_id}".encode()).digest()[:8], "big", signed=True)
        self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def _validate_activation(self, tenant_id: UUID, target: ModelVersion) -> None:
        """Reject absent, changed or unusable artifacts before touching serving state."""
        try:
            if target.model_type == DGSR_MODEL_TYPE:
                from graphrec_core.dgsr.serving import DGSRArtifact, evict_artifact
                directory = artifact_directory(target.artifact_uri)
                roots = [get_settings().model_artifact_root, get_settings().generated_model_root]
                if directory is None or not any(root and directory.resolve().is_relative_to(Path(root).resolve()) for root in roots):
                    raise ValueError("Artifact is outside the configured model store")
                validate_artifact_binding(directory, tenant_id)
                artifact = DGSRArtifact(directory)
                validate_artifact_binding(directory, tenant_id, artifact.checkpoint_sha256)
                expected = (target.metrics or {}).get("source", {}).get("checkpoint_sha256")
                if not expected or artifact.checkpoint_sha256 != expected:
                    raise ValueError("Artifact differs from its registered checkpoint")
                catalog = set(self.db.scalars(select(Product.external_id).where(Product.tenant_id == tenant_id, Product.is_active.is_(True))))
                if not catalog.intersection(artifact.item_ids):
                    raise ValueError("Artifact has no eligible catalog items")
                probe = artifact.encode_known(0)
                if not np.isfinite(probe.query).all():
                    raise ValueError("Artifact produced an invalid query")
                info = get_qdrant_client().get_collection(collection_name(tenant_id, target.id))
                if not info.points_count:
                    raise ValueError("The version has no indexed products")
                evict_artifact(directory)
            else:
                if get_settings().is_production:
                    raise ValueError("Only trained DGSR versions can become active in production")
                # Development placeholders are usable only when their index was
                # actually created. A successful job row alone is insufficient.
                info = get_qdrant_client().get_collection(collection_name(tenant_id, target.id))
                if not info.points_count:
                    raise ValueError("The version has no indexed products")
        except Exception as exc:
            logger.warning("Model readiness validation failed for %s: %s", target.id, exc)
            raise ApiError(422, "model_not_ready", "Model readiness validation failed. Check its artifact and catalog; the current active version was preserved.") from exc

    def archive_model_version(self, tenant_id: UUID, version_id: UUID) -> ModelVersionResource:
        self._lock_lifecycle(tenant_id)
        target = self.db.execute(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id, ModelVersion.id == version_id
            )
        ).scalar_one_or_none()

        if not target:
            raise ApiError(404, "resource_not_found", f"Model version '{version_id}' not found.")

        if target.status == "active":
            raise ApiError(
                409,
                "conflict",
                "Cannot archive currently active model version. Activate another version first.",
            )

        if target.status == "retired":
            active = self.db.scalar(select(ModelVersion.id).where(
                ModelVersion.tenant_id == tenant_id, ModelVersion.status == "active",
            ))
            protected = self.db.scalar(select(ModelVersion.id).where(
                ModelVersion.tenant_id == tenant_id, ModelVersion.status == "retired",
            ).order_by(ModelVersion.activated_at.desc().nulls_last(), ModelVersion.created_at.desc()).limit(1))
            if active is not None and protected == target.id:
                raise ApiError(409, "protected_rollback_target", "This version is retained as the current rollback target.")

        target.status = "archived"
        self._audit(tenant_id, "model_archived", target.id)
        self.db.commit()

        # Clean up the Qdrant collection for this version to free storage
        try:
            coll = collection_name(tenant_id, version_id)
            delete_collection(get_qdrant_client(), coll)
            logger.info("Deleted Qdrant collection %s on archive", coll)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not delete Qdrant collection on archive: %s", exc)

        return ModelVersionResource.model_validate(target)

    # ------------------------------------------------------------------
    # Training job — creates job record + model version + indexes embeddings
    # ------------------------------------------------------------------

    def create_training_job(
        self, tenant_id: UUID, payload: TrainingJobCreate
    ) -> TrainingJobResource:
        if payload.request_id:
            key = int.from_bytes(hashlib.sha256(f"training:{tenant_id}:{payload.request_id}".encode()).digest()[:8], "big", signed=True)
            self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            previous = self.db.scalar(select(TrainingJob).where(
                TrainingJob.tenant_id == tenant_id, TrainingJob.request_id == payload.request_id))
            if previous is not None:
                if previous.payload_hash != payload_hash(payload.model_dump(mode="json")):
                    raise ApiError(409, "idempotency_conflict", "This training identifier was already used with different input.")
                return TrainingJobResource.model_validate(previous)
        tenant_lock = int.from_bytes(hashlib.sha256(f"training-tenant:{tenant_id}".encode()).digest()[:8], "big", signed=True)
        self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": tenant_lock})
        if payload.dataset_snapshot_id is not None:
            snapshot = self.db.scalar(select(DatasetSnapshot).where(
                DatasetSnapshot.tenant_id == tenant_id, DatasetSnapshot.id == payload.dataset_snapshot_id))
            if snapshot is None:
                raise ApiError(404, "resource_not_found", "Dataset snapshot not found.")
        require_capacity(self.db, tenant_id, "training_jobs")
        # D-11: every successful job registers a version; refuse up front when the
        # tenant already retains its plan's maximum (archive one to make room).
        require_capacity(self.db, tenant_id, "active_model_versions")
        artifact_name = (payload.configuration or {}).get("pretrained_artifact")
        mode = (payload.configuration or {}).get("mode", "train")
        self._check_training_eligibility(tenant_id, cooldown=artifact_name is not None or mode == "train")
        if artifact_name is not None:
            return self.import_pretrained_artifact(tenant_id, payload, str(artifact_name))
        if mode == "train":
            return self._queue_training(tenant_id, payload)
        if mode != "placeholder":
            raise ApiError(422, "validation_failed", "Choose train, a pretrained_artifact, or an explicit development placeholder.")
        if get_settings().is_production:
            # A-02: synthetic embeddings are a development aid, never a production model.
            raise ApiError(422, "validation_failed", "Placeholder training is available only in development.",
                           details={"fields": [{"field": "configuration.mode", "message": "Use train or a pretrained_artifact"}]})
        now = datetime.now(timezone.utc)
        settings = get_settings()

        # Create training job record
        job = TrainingJob(
            id=uuid4(),
            request_id=payload.request_id,
            payload_hash=payload_hash(payload.model_dump(mode="json")),
            tenant_id=tenant_id,
            model_type="development_placeholder",
            status="succeeded",
            progress=100,
            configuration=payload.configuration or {"batch_size": 256, "learning_rate": 0.001},
            dataset_snapshot_id=payload.dataset_snapshot_id,
            created_at=now,
            completed_at=now,
        )
        self.db.add(job)

        # Register corresponding model version. The tag carries a slice of the
        # version id so two requests in the same second cannot collide on the
        # (tenant, version_tag) unique constraint.
        version_id = uuid4()
        version_tag = f"v{now.strftime('%Y%m%d%H%M%S')}-{version_id.hex[:6]}"
        mv = ModelVersion(
            id=version_id,
            tenant_id=tenant_id,
            version_tag=version_tag,
            model_type="development_placeholder",
            status="eligible",
            # Real metrics come from the training worker; none exist for synthetic embeddings.
            metrics={},
            artifact_uri=f"placeholder://{tenant_id}/{version_tag}",
            created_at=now,
        )
        self.db.add(mv)
        job.model_version_id = mv.id

        usage = UsageEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            usage_type="training_jobs",
            quantity=Decimal("1"),
            source_id=f"training-job-{job.id}",
            idempotency_key=str(uuid4()),
            occurred_at=now,
        )
        self.db.add(usage)
        try:
            self.db.flush()  # get mv.id before commit so indexer can use it
        except IntegrityError as exc:
            self.db.rollback()
            raise ApiError(
                409,
                "duplicate_resource",
                "A model version with the same tag was registered concurrently; retry.",
            ) from exc

        # ----------------------------------------------------------------
        # Index item embeddings into Qdrant
        # ----------------------------------------------------------------
        # Fetch all active product external IDs for this tenant so that the
        # Qdrant collection is populated with real product identifiers.
        # This explicit development-placeholder mode uses synthetic vectors.
        # Real DGSR training and prepared-artifact import index their learned
        # item embeddings through separate paths.
        coll_name: str | None = None
        try:
            product_ids: list[str] = list(
                self.db.execute(
                    select(Product.external_id).where(
                        Product.tenant_id == tenant_id,
                        Product.is_active == True,  # noqa: E712
                    )
                ).scalars()
            )

            if product_ids:
                dim = settings.qdrant_embedding_dim
                # Synthetic embeddings — replaced by real GNN output in worker
                rng = np.random.default_rng(seed=int(mv.id.int % (2**32)))
                raw = rng.standard_normal((len(product_ids), dim)).astype(np.float32)
                # L2-normalise so cosine similarity equals dot product
                norms = np.linalg.norm(raw, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1.0, norms)
                embeddings = raw / norms

                n_indexed = index_item_embeddings(
                    client=get_qdrant_client(),
                    tenant_id=tenant_id,
                    version_id=mv.id,
                    external_ids=product_ids,
                    embedding_matrix=embeddings,
                )
                coll_name = collection_name(tenant_id, mv.id)
                logger.info(
                    "Indexed %d item embeddings into Qdrant collection %s",
                    n_indexed,
                    coll_name,
                )
            else:
                logger.info(
                    "No active products found for tenant %s; skipping Qdrant indexing", tenant_id
                )
        except Exception as exc:  # noqa: BLE001
            # Qdrant failure must not break the training job response —
            # the API stays functional even if the vector store is down.
            logger.warning("Qdrant indexing failed (non-fatal): %s", exc)

        self._audit(tenant_id, "training_completed", job.id, details={"mode": "development_placeholder"})
        self.db.commit()

        result = TrainingJobResource.model_validate(job)
        result.qdrant_collection = coll_name
        return result

    # ------------------------------------------------------------------
    # Pretrained DGSR artifact import — a training job whose weights come
    # from a checkpoint the notebook trained on this tenant's data.
    # ------------------------------------------------------------------

    def import_pretrained_artifact(
        self, tenant_id: UUID, payload: TrainingJobCreate, artifact_name: str
    ) -> TrainingJobResource:
        """Register a model version backed by ``<model_artifact_root>/<name>``.

        The checkpoint is verified (engine, config, data fingerprint, vocabulary)
        and checked for compatibility with the tenant: its item ids must be this
        tenant's product external ids and its user ids this tenant's event
        user ids. Coverage is recorded in the version metrics; an artifact that
        matches none of the catalog is rejected. Normalized item embeddings
        are indexed into its tenant/version Qdrant collection.
        """
        from graphrec_core.dgsr.serving import ArtifactError, load_artifact

        settings = get_settings()
        if not settings.model_artifact_root:
            raise ApiError(
                422,
                "artifact_imports_disabled",
                "MODEL_ARTIFACT_ROOT is not configured on this deployment.",
            )
        if not ARTIFACT_NAME.match(artifact_name):
            raise ApiError(422, "validation_failed", "pretrained_artifact must be a plain directory name.")
        directory = Path(settings.model_artifact_root) / artifact_name
        if not directory.is_dir() or not directory.resolve().is_relative_to(Path(settings.model_artifact_root).resolve()):
            raise ApiError(404, "artifact_not_found", f"Artifact '{artifact_name}' is not available.")
        try:
            validate_artifact_binding(directory, tenant_id)
        except (OSError, ValueError, TypeError) as exc:
            raise ApiError(404, "artifact_not_found", "This artifact is not provisioned for the tenant.") from exc

        now = datetime.now(timezone.utc)
        job = TrainingJob(
            id=uuid4(),
            request_id=payload.request_id,
            payload_hash=payload_hash(payload.model_dump(mode="json")),
            tenant_id=tenant_id,
            model_type=DGSR_MODEL_TYPE,
            status="running",
            configuration={**(payload.configuration or {}), "mode": "pretrained_import"},
            dataset_snapshot_id=payload.dataset_snapshot_id,
            created_at=now,
        )
        self.db.add(job)
        self.db.add(
            UsageEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                usage_type="training_jobs",
                quantity=Decimal("1"),
                source_id=f"training-job-{job.id}",
                idempotency_key=str(uuid4()),
                occurred_at=now,
            )
        )
        self.db.flush()

        try:
            artifact = load_artifact(directory)
            validate_artifact_binding(directory, tenant_id, artifact.checkpoint_sha256)
        except (ArtifactError, OSError, KeyError, RuntimeError, ValueError) as exc:
            return self._fail_job(job, f"artifact_invalid: {exc}")

        catalog = set(
            self.db.execute(
                select(Product.external_id).where(
                    Product.tenant_id == tenant_id,
                    Product.is_active == True,  # noqa: E712
                )
            ).scalars()
        )
        covered_items = [item for item in artifact.item_ids if item in catalog]
        item_coverage = len(covered_items) / max(1, len(artifact.item_ids))
        if not covered_items:
            return self._fail_job(
                job,
                "artifact_incompatible: none of the checkpoint's item ids are active products of this tenant",
            )
        event_users = set(
            self.db.execute(
                select(CustomerEvent.user_id)
                .where(CustomerEvent.tenant_id == tenant_id, CustomerEvent.user_id.is_not(None))
                .distinct()
            ).scalars()
        )
        user_coverage = sum(1 for user in artifact.user_ids if user in event_users) / max(1, len(artifact.user_ids))

        version_id = uuid4()
        version_tag = f"v{now.strftime('%Y%m%d%H%M%S')}-{version_id.hex[:6]}"
        metrics: dict[str, Any] = {
            **artifact.metrics,
            "source": {
                "artifact": artifact_name,
                **artifact.describe(),
                "catalog_item_coverage": round(item_coverage, 4),
                "event_user_coverage": round(user_coverage, 4),
                "indexed_items": len(covered_items),
                "artifact_bytes": sum(p.stat().st_size for p in directory.iterdir() if p.is_file()),
            },
        }
        require_capacity(self.db, tenant_id, "artifact_storage_bytes", metrics["source"]["artifact_bytes"])
        mv = ModelVersion(
            id=version_id,
            tenant_id=tenant_id,
            version_tag=version_tag,
            model_type=DGSR_MODEL_TYPE,
            status="eligible",
            metrics=metrics,
            artifact_uri=f"file://{directory.resolve().as_posix()}",
            created_at=now,
        )
        self.db.add(mv)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise ApiError(
                409,
                "duplicate_resource",
                "A model version with the same tag was registered concurrently; retry.",
            ) from exc

        coll_name: str | None = None
        try:
            table = artifact.item_embeddings()
            rows = np.asarray([artifact.item_index(item) for item in covered_items], dtype=np.int64)
            vectors = table[rows]
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if not np.isfinite(vectors).all() or np.any(norms <= 0):
                raise ValueError("Artifact item embeddings cannot be indexed")
            n_indexed = index_item_embeddings(
                client=get_qdrant_client(),
                tenant_id=tenant_id,
                version_id=mv.id,
                external_ids=covered_items,
                embedding_matrix=vectors / norms,
            )
            coll_name = collection_name(tenant_id, mv.id)
            logger.info("Indexed %d DGSR item embeddings into %s", n_indexed, coll_name)
        except Exception as exc:  # noqa: BLE001
            # Serving scores in-process when the collection is missing.
            logger.warning("Qdrant indexing of the DGSR item table failed (non-fatal): %s", exc)

        job.status = "succeeded"
        job.progress = 100
        job.stage = "completed"
        job.model_version_id = mv.id
        job.completed_at = datetime.now(timezone.utc)
        self._audit(tenant_id, "training_completed", job.id, details={"mode": "pretrained_import", "model_version_id": str(mv.id)})
        self.db.commit()
        result = TrainingJobResource.model_validate(job)
        result.qdrant_collection = coll_name
        return result

    def _fail_job(self, job: TrainingJob, reason: str) -> TrainingJobResource:
        """Record a terminal failure (ER-NF-04) instead of a half-registered version."""
        job.status = "failed"
        job.failure_reason = reason[:1000]
        job.completed_at = datetime.now(timezone.utc)
        self._audit(job.tenant_id, "training_failed", job.id, outcome="failed", details={"reason": reason.split(":", 1)[0]})
        self.db.commit()
        logger.warning("Training job %s failed: %s", job.id, reason)
        return TrainingJobResource.model_validate(job)

    def _check_training_eligibility(self, tenant_id: UUID, *, cooldown: bool) -> None:
        active = self.db.scalar(select(TrainingJob.id).where(
            TrainingJob.tenant_id == tenant_id,
            TrainingJob.status.in_(["queued", "running"]),
        ).limit(1))
        if active:
            raise ApiError(409, "training_in_progress", "Wait for or cancel this tenant's current training job.")
        seconds = get_settings().training_cooldown_seconds if cooldown else 0
        if not seconds:
            return
        last_completed = self.db.scalar(select(TrainingJob.completed_at).where(
            TrainingJob.tenant_id == tenant_id,
            TrainingJob.model_type == DGSR_MODEL_TYPE,
            TrainingJob.completed_at.is_not(None),
        ).order_by(TrainingJob.completed_at.desc()).limit(1))
        if last_completed is None:
            return
        remaining = math.ceil((last_completed + timedelta(seconds=seconds) - datetime.now(timezone.utc)).total_seconds())
        if remaining > 0:
            raise ApiError(409, "training_cooldown", "Wait before starting another DGSR training job.",
                           retryable=True, retry_after_seconds=remaining)

    def _queue_training(self, tenant_id: UUID, payload: TrainingJobCreate) -> TrainingJobResource:
        from graphrec_core.datasets.service import DatasetService
        from graphrec_core.schemas.datasets import DatasetSnapshotCreate
        configuration = dict(payload.configuration)
        if set(configuration) - {"mode", "epochs"}:
            raise ApiError(422, "validation_failed", "Local training configuration supports only mode and epochs.")
        epochs = configuration.get("epochs", 3)
        if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= 10:
            raise ApiError(422, "validation_failed", "Training epochs must be an integer from 1 to 10.")
        snapshot_id = payload.dataset_snapshot_id
        if snapshot_id is None:
            snapshot_id = DatasetService(self.db).create_snapshot(tenant_id, DatasetSnapshotCreate(), commit=False).id
        content = self.db.get(DatasetSnapshotContent, snapshot_id)
        if content is None or content.tenant_id != tenant_id:
            raise ApiError(422, "snapshot_unavailable", "Create a new snapshot with persisted contents before training.")
        events = content.content["events"]
        from collections import Counter
        histories = Counter(e["user_id"] for e in events if e["user_id"] and e["external_product_id"])
        if not histories or max(histories.values()) < 4:
            raise ApiError(422, "insufficient_training_data", "Training needs at least four chronological product interactions for one shopper, including held-out validation and test targets.")
        if len(events) > 20_000 or len(content.content["products"]) > 10_000:
            raise ApiError(422, "training_capacity_exceeded", "Local CPU training supports up to 20,000 events and 10,000 products. Import a prepared checkpoint for larger datasets.")
        now = datetime.now(timezone.utc)
        job = TrainingJob(id=uuid4(), tenant_id=tenant_id, request_id=payload.request_id,
            payload_hash=payload_hash(payload.model_dump(mode="json")), model_type="dgsr", status="queued",
            stage="queued", progress=0, configuration={**configuration, "epochs": epochs, "mode": "train"},
            dataset_snapshot_id=snapshot_id, created_at=now)
        self.db.add(job)
        self.db.add(UsageEvent(id=uuid4(), tenant_id=tenant_id, usage_type="training_jobs", quantity=Decimal(1),
            source_id=str(job.id), idempotency_key=f"training-{job.id}", occurred_at=now))
        self._audit(tenant_id, "training_requested", job.id, details={"mode": "train"})
        self.db.commit()
        return TrainingJobResource.model_validate(job)

    def cancel_training(self, tenant_id: UUID, job_id: UUID) -> TrainingJobResource:
        job = self.db.scalar(select(TrainingJob).where(TrainingJob.tenant_id == tenant_id, TrainingJob.id == job_id).with_for_update())
        if job is None:
            raise ApiError(404, "resource_not_found", "Training job not found.")
        if job.status not in {"queued", "running"}:
            raise ApiError(409, "job_terminal", "Only queued or running jobs can be cancelled.")
        job.cancel_requested = True
        if job.status == "queued":
            job.status, job.stage, job.completed_at = "cancelled", "cancelled", datetime.now(timezone.utc)
        self._audit(tenant_id, "training_cancel_requested", job.id)
        self.db.commit()
        return TrainingJobResource.model_validate(job)

    def list_training_jobs(self, tenant_id: UUID) -> list[TrainingJobResource]:
        jobs = (
            self.db.execute(
                select(TrainingJob)
                .where(TrainingJob.tenant_id == tenant_id)
                .order_by(TrainingJob.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [TrainingJobResource.model_validate(j) for j in jobs]

    def get_training_job(self, tenant_id: UUID, job_id: UUID) -> TrainingJobResource:
        job = self.db.scalar(select(TrainingJob).where(
            TrainingJob.tenant_id == tenant_id, TrainingJob.id == job_id,
        ))
        if job is None:
            raise ApiError(404, "resource_not_found", "Training job not found.")
        return TrainingJobResource.model_validate(job)
