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
    distance: qmodels.Distance = qmodels.Distance.COSINE,
) -> None:
    """Create the Qdrant collection if it does not already exist.

    Uses cosine distance (standard for normalised embedding similarity) and
    an HNSW index configured for the educational-scale catalog sizes
    targeted by GraphRec.

    Args:
        client: Active QdrantClient instance.
        name:   Collection name (from ``collection_name()``).
        dim:    Item embedding dimension matching the DGSR-lite output layer.
        distance: COSINE for normalised synthetic vectors; DOT for DGSR, whose
                scores are unnormalised ``query . item`` products (Eq. 18).
    """
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(
                size=dim,
                distance=distance,
                hnsw_config=qmodels.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                ),
            ),
        )
    ensure_payload_indexes(client, name)


#: Payload fields every search filters on. Without keyword indexes Qdrant
#: evaluates the filter point by point, and excluding a shopper's history
#: (hundreds of ids) took seconds instead of milliseconds.
INDEXED_PAYLOAD_FIELDS = ("external_id", "tenant_id")


def ensure_payload_indexes(client: QdrantClient, name: str) -> None:
    """Create the keyword payload indexes the retriever relies on (idempotent)."""
    present = set(client.get_collection(name).payload_schema or {})
    for field in INDEXED_PAYLOAD_FIELDS:
        if field not in present:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
                wait=True,
            )


def delete_collection(client: QdrantClient, name: str) -> None:
    """Delete a Qdrant collection.

    Called when a model version is archived to free storage.
    Safe to call even if the collection does not exist.
    """
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        client.delete_collection(collection_name=name)
