"""The bucket's layout.

One rule, and everything else follows from it: **every key begins with the
tenant it belongs to.** `tenants/{tenant_id}/…` is not cosmetic. It means a
bucket policy, a lifecycle rule or a deletion sweep can be written against a
prefix rather than against a list, and it means an object whose key does not
start with the caller's tenant is visibly wrong before anything opens it.

That prefix is a *convenience*, not the isolation boundary. Phase 10's bundle
manifest carries the tenant id inside the artifact and verifies it at load, and
that check is the one that matters: a key is metadata an operator can rename and
a manifest is content a digest covers. Both, because they fail differently.

Keys are built here and nowhere else. A module that formats its own would be a
second layout, and the first sign of it would be an object nobody can find.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

#: Every tenant-owned object lives under this.
TENANT_PREFIX = "tenants"


def tenant_root(tenant_id: uuid.UUID) -> str:
    return f"{TENANT_PREFIX}/{tenant_id}"


def snapshot_key(tenant_id: uuid.UUID, snapshot_id: uuid.UUID) -> str:
    """The frozen dataset one run read.

    `.npz` because the snapshot is arrays — sequences, timestamps, weights, item
    features — and `numpy.savez` is the format that does not require a second
    dependency to read back. Not `pickle`, for the reason ADR 0025 gives about
    checkpoints: an artifact somebody could swap must not be a program.
    """
    return f"{tenant_root(tenant_id)}/snapshots/{snapshot_id}.npz"


def checkpoint_key(tenant_id: uuid.UUID, training_job_id: uuid.UUID) -> str:
    """The resume point, keyed by the *job* rather than by the epoch.

    One key, overwritten each epoch. Keeping every epoch's checkpoint would make
    resume a search for the newest of N objects, and "newest" in an object store
    is a timestamp somebody else's clock wrote. One key means resume is a `GET`
    and the answer is unambiguous.
    """
    return f"{tenant_root(tenant_id)}/checkpoints/{training_job_id}.safetensors"


def bundle_key(tenant_id: uuid.UUID, version_id: uuid.UUID, name: str) -> str:
    """One file inside a served model version's bundle (Phase 10).

    Here rather than in the registry because the layout is one thing and this is
    the module that holds it.
    """
    return f"{tenant_root(tenant_id)}/bundles/{version_id}/{name}"


def belongs_to(key: str, tenant_id: uuid.UUID) -> bool:
    """Whether `key` is under this tenant's prefix.

    Used before a read, so a stored `uri` that has been tampered with is refused
    by the reader rather than followed by it.
    """
    return key.startswith(f"{tenant_root(tenant_id)}/")


__all__ = [
    "TENANT_PREFIX",
    "belongs_to",
    "bundle_key",
    "checkpoint_key",
    "snapshot_key",
    "tenant_root",
]
