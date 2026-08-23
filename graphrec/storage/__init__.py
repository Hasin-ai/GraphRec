"""Object storage: snapshots, checkpoints and model bundles.

Three modules, and the split is the usual one.

* `keys` — the bucket layout. Every key starts with its tenant.
* `store` — the port, plus the digest helpers every adapter shares.
* `local` / `s3` — the two adapters. Which one runs is a setting; nothing above
  this package knows the difference.

Nothing authoritative lives here. A row in PostgreSQL records that a snapshot
exists, what it covers and what it hashes to; the object is the payload that row
describes. Losing the object costs a re-run, and losing the row would cost the
ability to tell whether the object is the right one — which is why the digest is
in the row and not only in the manifest.
"""

from __future__ import annotations

from graphrec.storage.store import (
    ArtifactStore,
    DigestMismatchError,
    StorageError,
    digest_bytes,
    digest_file,
)

__all__ = [
    "ArtifactStore",
    "DigestMismatchError",
    "StorageError",
    "digest_bytes",
    "digest_file",
]
