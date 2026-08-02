"""ANN candidate retriever — Stage 1 of the four-stage serving funnel.

Queries the Qdrant collection for a model version using a query vector
(representing the current user's long/short preference state) and returns
the top-K most similar item external IDs ranked by cosine similarity.

Fallback behaviour:
    If the collection does not exist (e.g., Qdrant is unreachable or the
    model version has not been indexed yet), ``retrieve_candidates`` returns
    an empty list. The recommendation route then falls back to the
    ``popular_fallback`` strategy.

Isolation:
    A Qdrant ``must`` filter on ``tenant_id`` payload is applied to every
    search even though the collection is already tenant+version scoped.
    This provides defence-in-depth against any misconfigured collection
    reuse.
"""
from __future__ import annotations

from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from graphrec_core.vector_store.collections import collection_name
from graphrec_core.settings import get_settings


def retrieve_candidates(
    client: QdrantClient,
    tenant_id: UUID,
    version_id: UUID,
    query_vector: list[float],
    top_k: int | None = None,
    exclude_ids: list[str] | None = None,
) -> list[str]:
    """Query Qdrant for the top-K most similar item external IDs.

    Args:
        client:       Active QdrantClient instance.
        tenant_id:    Owning tenant UUID — applied as a payload filter.
        version_id:   Model version UUID — determines which collection to query.
        query_vector: Float list representing the current user/session state.
                      Length must equal ``qdrant_embedding_dim``.
        top_k:        Number of candidates to retrieve (default from settings).
        exclude_ids:  List of external_product_ids to exclude from results
                      (e.g., recently purchased items).

    Returns:
        Ordered list of ``external_id`` strings, highest similarity first.
        Empty list if the collection does not exist or Qdrant is unavailable.
    """
    settings = get_settings()
    k = top_k if top_k is not None else settings.qdrant_top_k
    coll = collection_name(tenant_id, version_id)

    # Check collection existence — avoids gRPC error on missing collection
    try:
        existing = {c.name for c in client.get_collections().collections}
    except Exception:
        return []

    if coll not in existing:
        return []

    # Build payload filter: tenant isolation + optional exclusion list
    must_conditions: list[qmodels.Condition] = [
        qmodels.FieldCondition(
            key="tenant_id",
            match=qmodels.MatchValue(value=str(tenant_id)),
        )
    ]

    must_not_conditions: list[qmodels.Condition] = []
    if exclude_ids:
        for eid in exclude_ids:
            must_not_conditions.append(
                qmodels.FieldCondition(
                    key="external_id",
                    match=qmodels.MatchValue(value=eid),
                )
            )

    query_filter = qmodels.Filter(
        must=must_conditions,
        must_not=must_not_conditions if must_not_conditions else None,
    )

    try:
        results = client.search(
            collection_name=coll,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=k,
            with_payload=True,
        )
    except Exception:
        return []

    return [
        hit.payload["external_id"]
        for hit in results
        if hit.payload and "external_id" in hit.payload
    ]
