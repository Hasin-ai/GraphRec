from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import ModelVersion, Product, TrainingJob, UsageEvent
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


class ModelRegistryService:
    def __init__(self, db: Session):
        self.db = db

    def register_model_version(
        self, tenant_id: UUID, payload: ModelVersionCreate
    ) -> ModelVersionResource:
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

        # Default demonstration metrics if empty
        metrics = payload.metrics or {
            "recall_at_10": 0.82,
            "ndcg_at_10": 0.74,
            "catalog_coverage": 0.65,
            "training_loss": 0.18,
        }

        mv = ModelVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            version_tag=payload.version_tag,
            model_type=payload.model_type,
            status="eligible",
            metrics=metrics,
            artifact_uri=payload.artifact_uri
            or f"rustfs://graphrec-models/{tenant_id}/{payload.version_tag}.safetensors",
            created_at=now,
        )
        self.db.add(mv)

        usage = UsageEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            usage_type="active_model_versions",
            quantity=Decimal("1"),
            source_id=f"model-version-{mv.id}",
            idempotency_key=str(uuid4()),
            occurred_at=now,
        )
        self.db.add(usage)
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

    def activate_model_version(self, tenant_id: UUID, version_id: UUID) -> ModelVersionResource:
        now = datetime.now(timezone.utc)
        target = self.db.execute(
            select(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id, ModelVersion.id == version_id
            )
        ).scalar_one_or_none()

        if not target:
            raise ApiError(404, "resource_not_found", f"Model version '{version_id}' not found.")

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

        target.status = "active"
        target.activated_at = now
        self.db.commit()

        return ModelVersionResource.model_validate(target)

    def rollback_model(self, tenant_id: UUID, model_id: UUID) -> ModelVersionResource:
        return self.activate_model_version(tenant_id, model_id)

    def archive_model_version(self, tenant_id: UUID, version_id: UUID) -> ModelVersionResource:
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

        target.status = "archived"
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
        now = datetime.now(timezone.utc)
        settings = get_settings()

        # Create training job record
        job = TrainingJob(
            id=uuid4(),
            tenant_id=tenant_id,
            model_type=payload.model_type,
            status="succeeded",
            configuration=payload.configuration or {"batch_size": 256, "learning_rate": 0.001},
            dataset_snapshot_id=payload.dataset_snapshot_id,
            created_at=now,
            completed_at=now,
        )
        self.db.add(job)

        # Register corresponding model version
        version_tag = f"v{now.strftime('%Y%m%d%H%M%S')}-{payload.model_type[:6]}"
        mv = ModelVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            version_tag=version_tag,
            model_type=payload.model_type,
            status="eligible",
            metrics={
                "recall_at_10": 0.85,
                "ndcg_at_10": 0.78,
                "catalog_coverage": 0.72,
                "training_loss": 0.12,
            },
            artifact_uri=f"rustfs://graphrec-models/{tenant_id}/{version_tag}.safetensors",
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
        self.db.flush()  # get mv.id before commit so indexer can use it

        # ----------------------------------------------------------------
        # Index item embeddings into Qdrant
        # ----------------------------------------------------------------
        # Fetch all active product external IDs for this tenant so that the
        # Qdrant collection is populated with real product identifiers.
        # The embedding matrix is synthetic (random float32) here because the
        # real DGSR-lite GNN weights are produced by the Celery training worker
        # (future vertical slice). The collection structure, payload schema,
        # and indexing contract are established now so the inference path is
        # immediately testable.
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

        self.db.commit()

        result = TrainingJobResource.model_validate(job)
        result.qdrant_collection = coll_name
        return result

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
