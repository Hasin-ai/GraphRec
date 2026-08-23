"""One place that decides which artifact store a process gets.

Every process that touches an artifact — the training worker, the reconciler,
inference — needs the same store, configured the same way, and none of them
should be the place that decides what "the same way" means. So the decision is
made once, from settings, and the callers take an `ArtifactStore`.

The factory returns the protocol, not the adapter. That is the whole point of
Phase 9 having a port here: a test can hand `LocalArtifactStore` to the pipeline
and get the real code path, and Phase 11's bundle loader cannot accidentally
grow a dependency on boto3 exception types.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from graphrec.common.config import ArtifactStoreKind

if TYPE_CHECKING:
    from graphrec.common.config import Settings
    from graphrec.storage.store import ArtifactStore


def create_artifact_store(settings: Settings) -> ArtifactStore:
    """Build the configured store.

    `artifact_local_root` is resolved and created here rather than lazily on
    first write, so a misconfigured path fails at startup where an operator is
    watching, and not four stages into a training run.
    """
    if settings.artifact_store is ArtifactStoreKind.LOCAL:
        from graphrec.storage.local import LocalArtifactStore

        root = pathlib.Path(settings.artifact_local_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return LocalArtifactStore(root)

    from graphrec.storage.s3 import S3ArtifactStore

    return S3ArtifactStore(
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        use_path_style=settings.s3_use_path_style,
    )


__all__ = ["create_artifact_store"]
