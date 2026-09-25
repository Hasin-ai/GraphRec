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

from graphrec_core.vector_store.collections import collection_name, ensure_payload_indexes
from graphrec_core.settings import get_settings


#: Collections whose payload indexes were verified by this process.
_INDEXED_COLLECTIONS: set[str] = set()


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
    if coll not in _INDEXED_COLLECTIONS:
        # Collections created before payload indexes existed get them lazily.
        try:
            ensure_payload_indexes(client, coll)
        except Exception:  # noqa: BLE001
            return []
        _INDEXED_COLLECTIONS.add(coll)

    # Build payload filter: tenant isolation + optional exclusion list
    must_conditions: list[qmodels.Condition] = [
        qmodels.FieldCondition(
            key="tenant_id",
            match=qmodels.MatchValue(value=str(tenant_id)),
        )
    ]

    if exclude_ids:
        # One MatchExcept condition instead of one must_not per id: with the
        # keyword payload index this costs ~10 ms for hundreds of exclusions,
        # where per-id conditions took seconds (a shopper's whole history is
        # excluded on every request).
        must_conditions.append(
            qmodels.FieldCondition(
                key="external_id",
                match=qmodels.MatchExcept(**{"except": list(dict.fromkeys(exclude_ids))}),
            )
        )

    query_filter = qmodels.Filter(must=must_conditions)

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
        for hit in sorted(results, key=lambda item: (-item.score, str((item.payload or {}).get("external_id", ""))))
        if hit.payload and "external_id" in hit.payload
    ]
