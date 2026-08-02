"""Vector store package — Qdrant-backed item embedding index and retrieval."""

from graphrec_core.vector_store.client import get_qdrant_client
from graphrec_core.vector_store.collections import collection_name, delete_collection, ensure_collection
from graphrec_core.vector_store.indexer import index_item_embeddings
from graphrec_core.vector_store.retriever import retrieve_candidates

__all__ = [
    "get_qdrant_client",
    "collection_name",
    "ensure_collection",
    "delete_collection",
    "index_item_embeddings",
    "retrieve_candidates",
]
