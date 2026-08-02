"""Qdrant gRPC client singleton.

A single QdrantClient instance is created per process using the QDRANT_URL
from settings. The client is created on first call and reused thereafter.

gRPC is preferred over HTTP REST because it provides lower latency for
high-frequency vector search calls in the inference path.
"""
from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient

from graphrec_core.settings import get_settings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Return a shared Qdrant gRPC client, created once per process.

    Falls back gracefully to HTTP if the URL does not start with
    ``grpc://`` or ``http://qdrant:6334`` style — Qdrant-client auto-detects
    the scheme.
    """
    settings = get_settings()
    url = settings.qdrant_url
    # qdrant-client accepts grpc:// and http:// URLs; extract host and port.
    # For gRPC URLs like "http://qdrant:6334" prefer_grpc=True enables gRPC.
    return QdrantClient(url=url, prefer_grpc=True, timeout=10.0)
