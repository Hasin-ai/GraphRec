"""The object store port, and what a digest is for.

Three verbs — put, get, delete — plus the two path-shaped helpers the ML layer
needs, because `safetensors` and `numpy.savez` both open files rather than
accept bytes and pretending otherwise would mean holding a model in memory twice
to satisfy an interface.

**Every put returns a digest and every get can be asked to verify one.** That is
the reason this is a port at all rather than a boto3 client passed around: the
digest is computed on the way in, stored in the row that describes the object
(`dataset_snapshots.checksum`), and checked on the way out. A corrupted or
substituted object is then a refusal at load, which is Phase 10's exit criterion
and is cheaper to build now than to retrofit around a client that was already
being called directly from four places.

`DigestMismatchError` is deliberately not a `GraphRecError`. It never reaches a
tenant: an artifact that fails verification is an internal failure and the
console is told a job failed, not which byte was wrong.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pathlib

#: The prefix a stored digest carries, so the algorithm travels with the value
#: and a future migration to a different one is a readable transition rather
#: than a silent reinterpretation of sixty-four hex characters.
DIGEST_ALGORITHM = "sha256"

#: Read in chunks rather than whole: a model bundle is tens of megabytes and a
#: snapshot can be more, and a worker holding all of it to hash it is a worker
#: that fails on the largest tenant first.
CHUNK_BYTES = 1 << 20


class StorageError(RuntimeError):
    """The object store could not do what was asked.

    Transient by default — see `graphrec.jobs.failures`: a storage timeout is
    one of the failures BUILD_PROMPT L471 says *is* worth another attempt.
    """


class DigestMismatchError(StorageError):
    """What came back is not what was stored.

    Not transient. Retrying a read of a corrupted object reads the same
    corrupted object, and the retry budget belongs to failures that can change
    their mind.
    """


def digest_bytes(data: bytes) -> str:
    return f"{DIGEST_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


def digest_file(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            hasher.update(chunk)
    return f"{DIGEST_ALGORITHM}:{hasher.hexdigest()}"


def verify(actual: str, expected: str | None, *, key: str) -> None:
    """Raise unless the digests agree. `None` expected means no claim was made.

    A caller that has no expectation passes `None` and gets no check, which is
    honest; a caller that passes an empty string gets a mismatch, which is also
    honest. The one thing this must not do is treat a missing expectation as a
    passed check.
    """
    if expected is None:
        return
    if actual != expected:
        raise DigestMismatchError(f"{key} does not match its recorded digest")


@runtime_checkable
class ArtifactStore(Protocol):
    """Where snapshots, checkpoints and bundles live.

    Synchronous. Every caller is a worker doing one long thing at a time, and an
    async S3 client would add a dependency to buy concurrency nothing here
    wants: a training worker uploading a checkpoint has nothing else to do.
    """

    def put_bytes(self, key: str, data: bytes) -> str:
        """Store `data`, returning its digest."""
        ...

    def get_bytes(self, key: str, *, expected_digest: str | None = None) -> bytes: ...

    def put_file(self, key: str, path: pathlib.Path) -> str:
        """Upload a local file, returning its digest."""
        ...

    def get_file(self, key: str, path: pathlib.Path, *, expected_digest: str | None = None) -> None:
        """Download to a local path, creating parents."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None:
        """Remove the object. Absent is not an error — delete is idempotent
        because the caller retrying a cleanup has not done anything wrong."""
        ...

    def uri(self, key: str) -> str:
        """The value stored in a `uri` column.

        A URI, not a key, because a deployment that moves from a filesystem to
        S3 must be able to tell an old row's location from a new one's without
        consulting a setting that has since changed.
        """
        ...


__all__ = [
    "CHUNK_BYTES",
    "DIGEST_ALGORITHM",
    "ArtifactStore",
    "DigestMismatchError",
    "StorageError",
    "digest_bytes",
    "digest_file",
    "verify",
]
