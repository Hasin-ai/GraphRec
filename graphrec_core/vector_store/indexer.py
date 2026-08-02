"""Item embedding indexer — called at the end of each training job.

After the Celery training worker (or the demo service stub) finishes
training DGSR-lite, it calls ``index_item_embeddings`` to push the
extracted item embedding matrix into Qdrant. Each vector is stored with a
payload so that retrieval can filter by tenant and version.

Payload schema per point:
    {
        "external_id": str,    # item external_id used by the tenant
        "tenant_id":   str,    # UUID hex string for payload filtering
        "version_id":  str,    # UUID hex string for payload filtering
    }

Batching:
    Vectors are upserted in batches of BATCH_SIZE to avoid gRPC message
    size limits. Qdrant gRPC has a 4 MiB default message limit; for dim=128
    float32 vectors each batch of 256 uses ~256 * 128 * 4 ≈ 131 KiB —
    well within the limit.
"""
from __future__ import annotations

from uuid import UUID

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from graphrec_core.vector_store.collections import collection_name, ensure_collection
from graphrec_core.settings import get_settings

BATCH_SIZE = 256


def index_item_embeddings(
    client: QdrantClient,
    tenant_id: UUID,
    version_id: UUID,
    external_ids: list[str],
    embedding_matrix: np.ndarray,
) -> int:
    """Index item embeddings into Qdrant for a specific model version.

    Args:
        client:           Active QdrantClient instance.
        tenant_id:        Owning tenant UUID.
        version_id:       Model version UUID (determines collection name).
        external_ids:     List of item external IDs — must align row-for-row
                          with ``embedding_matrix``.
        embedding_matrix: float32 ndarray of shape ``[N, dim]``.

    Returns:
        Number of vectors successfully indexed.

    Raises:
        ValueError: If ``external_ids`` and ``embedding_matrix`` have
                    mismatched lengths, or if matrix dtype is wrong.
    """
    if len(external_ids) != embedding_matrix.shape[0]:
        raise ValueError(
            f"external_ids length ({len(external_ids)}) does not match "
            f"embedding_matrix rows ({embedding_matrix.shape[0]})"
        )

    settings = get_settings()
    dim = embedding_matrix.shape[1]
    if dim != settings.qdrant_embedding_dim:
        raise ValueError(
            f"Embedding dim {dim} does not match configured "
            f"qdrant_embedding_dim={settings.qdrant_embedding_dim}"
        )

    # Ensure float32 — Qdrant requires float32 vectors
    matrix = embedding_matrix.astype(np.float32)

    coll = collection_name(tenant_id, version_id)
    ensure_collection(client, coll, dim)

    tid_str = str(tenant_id)
    vid_str = str(version_id)
    total = 0

    for start in range(0, len(external_ids), BATCH_SIZE):
        batch_ids = external_ids[start : start + BATCH_SIZE]
        batch_vecs = matrix[start : start + BATCH_SIZE]

        points = [
            qmodels.PointStruct(
                id=start + i,          # sequential integer ID
                vector=batch_vecs[i].tolist(),
                payload={
                    "external_id": batch_ids[i],
                    "tenant_id": tid_str,
                    "version_id": vid_str,
                },
            )
            for i in range(len(batch_ids))
        ]

        client.upsert(collection_name=coll, points=points, wait=True)
        total += len(points)

    return total
