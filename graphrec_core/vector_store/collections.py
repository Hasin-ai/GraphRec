"""Qdrant collection lifecycle — naming, creation, and deletion.

Collection naming convention:
    ``{prefix}__{tenant_id}__{version_id}``

This guarantees:
- Complete tenant isolation (tenant_id in name + payload filter)
- Version isolation (old versions don't pollute new retrievals)
- Predictable cleanup when a model version is archived

HNSW index parameters:
- m=16: 16 bi-directional links per node — good accuracy/memory balance
- ef_construct=100: search depth during construction — trade-off between
  build time and recall quality. 100 is the Qdrant recommended default.
"""
from __future__ import annotations

from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from graphrec_core.settings import get_settings


def collection_name(tenant_id: UUID, version_id: UUID) -> str:
    """Return the canonical Qdrant collection name for a model version."""
    prefix = get_settings().qdrant_collection_prefix
    # Replace hyphens so the name is a valid Qdrant identifier
    tid = str(tenant_id).replace("-", "")
    vid = str(version_id).replace("-", "")
    return f"{prefix}__{tid}__{vid}"


def ensure_collection(
    client: QdrantClient,
    name: str,
    dim: int,
) -> None:
    """Create the Qdrant collection if it does not already exist.

    Uses cosine distance (standard for normalised embedding similarity) and
    an HNSW index configured for the educational-scale catalog sizes
    targeted by GraphRec.

    Args:
        client: Active QdrantClient instance.
        name:   Collection name (from ``collection_name()``).
        dim:    Item embedding dimension matching the DGSR-lite output layer.
    """
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        return

    client.create_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(
            size=dim,
            distance=qmodels.Distance.COSINE,
            hnsw_config=qmodels.HnswConfigDiff(
                m=16,
                ef_construct=100,
            ),
        ),
    )


def delete_collection(client: QdrantClient, name: str) -> None:
    """Delete a Qdrant collection.

    Called when a model version is archived to free storage.
    Safe to call even if the collection does not exist.
    """
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        client.delete_collection(collection_name=name)
