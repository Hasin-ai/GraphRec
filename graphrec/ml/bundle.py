"""A served model version, as one file that vouches for itself.

A bundle is what `indexing_embeddings` uploads and what an inference process
downloads and loads before any pointer swap (ER-F-06). Between those two moments
it sits in an object store that several components can write to, so the question
this module answers is not "how do I serialise a matrix" but "what must be true
of these bytes before a tenant's recommendations are computed from them".

**One file, not a directory.** safetensors already carries a `str → str`
metadata header beside the tensors, so the manifest travels *inside* the
artifact. A manifest in a sibling object would be a second thing to fetch, a
second thing to keep consistent, and — the part that matters — a second thing an
attacker could leave behind while replacing the first.

**Two digests, because they cover different things.** `model_versions.
artifact_digest` is the digest of the whole file and is checked by the store on
the way out: it catches truncation, corruption and substitution of the object.
`payload_digest` lives *in* the manifest and covers the tensor bytes alone: it
catches a file whose header was kept and whose weights were swapped. Neither
subsumes the other, and a manifest that vouched only for itself would vouch for
anything.

**The tenant id is in the manifest and it is checked.** `keys.belongs_to` checks
the *path*, which is a claim made by whoever built the path. The manifest is a
claim made by the process that trained the model, sealed under the file digest
the registry recorded at registration. Phase 10's exit criterion — a
foreign-tenant manifest is refused — is about the second claim, because the
first one is exactly as trustworthy as the row that produced it.

**Refusal is total.** There is no partial load, no "the dimensions disagree but
the weights look fine". A bundle that fails any check raises `BundleError` and
the caller keeps serving whatever it was serving, which in Phase 11 is the
previously active version.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from safetensors.torch import load_file, save_file

if TYPE_CHECKING:
    from numpy.typing import NDArray

#: The tensor holding the item matrix. Dot-product scoring means a version *is*
#: this matrix (ADR 0023), so it is the one tensor a bundle must have.
EMBEDDINGS_KEY = "item_embeddings"

#: The metadata header key holding the manifest, as a JSON document.
MANIFEST_KEY = "graphrec"

#: The bundle's own layout version, independent of the model version's number.
#: An inference process that met a bundle from a newer build must refuse it
#: rather than read the fields it recognises: a bundle is loaded to serve
#: traffic, and "mostly understood" is not a state traffic should be served
#: from.
FORMAT_VERSION = 1

#: The file's name inside `keys.bundle_key(...)`. One name, so a reader does not
#: have to list a prefix to discover what it is about to trust.
BUNDLE_NAME = "bundle.safetensors"

#: What the store's `digest_bytes` returns, so the two spell an algorithm the
#: same way. Repeated rather than imported because `graphrec.ml` does not depend
#: on `graphrec.storage` — the ML layer writes files, and something else decides
#: where files live.
DIGEST_ALGORITHM = "sha256"


class BundleError(RuntimeError):
    """These bytes are not a bundle this process may serve from.

    Deliberately not a `GraphRecError`. It never reaches a tenant: a bundle that
    fails verification becomes a `failed_deployment` with approved copy, and
    which check failed is an operator's business (NR-NF-06).
    """


@dataclass(frozen=True, slots=True)
class FeatureContract:
    """What the bundle expects its inputs to look like.

    Checked at load in Phase 11 against the features the serving process can
    actually produce, which is the failure the prototype's `v-4` panel narrates:
    *"embedding index rejected the feature contract"* (L704). Carried here so
    that refusal is a comparison of two recorded values rather than an exception
    from deep inside a matrix multiply.
    """

    feature_builder_version: int
    static_feature_dim: int
    category_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "feature_builder_version": self.feature_builder_version,
            "static_feature_dim": self.static_feature_dim,
            "category_count": self.category_count,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FeatureContract:
        return cls(
            feature_builder_version=int(raw["feature_builder_version"]),
            static_feature_dim=int(raw["static_feature_dim"]),
            category_count=int(raw["category_count"]),
        )


@dataclass(frozen=True, slots=True)
class BundleManifest:
    """Everything about the bundle that is not a number in the matrix.

    `item_refs` is here rather than in a tensor because the external product
    identifiers are strings, and because they are the bundle's way back out: a
    version that returned row indices would be meaningless the moment the
    catalogue changed. They are also what makes the matrix interpretable at all,
    which is why they are covered by the payload digest.
    """

    tenant_id: uuid.UUID
    model_version_id: uuid.UUID
    training_job_id: uuid.UUID
    snapshot_id: uuid.UUID
    embedding_dim: int
    #: External product identifiers, positionally aligned with the matrix rows.
    item_refs: list[str]
    feature_contract: FeatureContract
    payload_digest: str
    created_at: dt.datetime
    format_version: int = FORMAT_VERSION
    #: Free-form, and never trusted for a decision. Build provenance for a human
    #: reading a bundle out of a bucket six months later.
    notes: dict[str, str] = field(default_factory=dict)

    @property
    def item_count(self) -> int:
        return len(self.item_refs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "tenant_id": str(self.tenant_id),
            "model_version_id": str(self.model_version_id),
            "training_job_id": str(self.training_job_id),
            "snapshot_id": str(self.snapshot_id),
            "embedding_dim": self.embedding_dim,
            "item_refs": self.item_refs,
            "feature_contract": self.feature_contract.as_dict(),
            "payload_digest": self.payload_digest,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BundleManifest:
        try:
            return cls(
                format_version=int(raw["format_version"]),
                tenant_id=uuid.UUID(raw["tenant_id"]),
                model_version_id=uuid.UUID(raw["model_version_id"]),
                training_job_id=uuid.UUID(raw["training_job_id"]),
                snapshot_id=uuid.UUID(raw["snapshot_id"]),
                embedding_dim=int(raw["embedding_dim"]),
                item_refs=[str(ref) for ref in raw["item_refs"]],
                feature_contract=FeatureContract.from_dict(raw["feature_contract"]),
                payload_digest=str(raw["payload_digest"]),
                created_at=dt.datetime.fromisoformat(raw["created_at"]),
                notes={str(k): str(v) for k, v in raw.get("notes", {}).items()},
            )
        except (KeyError, TypeError, ValueError) as error:
            # A malformed manifest and an absent one are the same refusal. What
            # they are not is a `KeyError` out of a serving process.
            msg = f"bundle manifest is not readable: {type(error).__name__}"
            raise BundleError(msg) from error


@dataclass(frozen=True, slots=True)
class Bundle:
    """A verified bundle: the manifest, and the matrix it describes."""

    manifest: BundleManifest
    #: `(item_count, embedding_dim)`, float32, on the CPU.
    item_embeddings: NDArray[np.float32]


def payload_digest(embeddings: NDArray[np.float32], item_refs: list[str]) -> str:
    """Digest the matrix and the labels together, in a stable order.

    Together, because they are only meaningful together: swapping two rows of
    the matrix and two entries of `item_refs` is a change no digest over either
    one alone would notice, and it would silently recommend the wrong products.

    The matrix is hashed as C-contiguous float32 and the refs as newline-joined
    UTF-8, so the value does not depend on how numpy happened to lay the array
    out in the process that computed it.
    """
    hasher = hashlib.sha256()
    contiguous = np.ascontiguousarray(embeddings, dtype=np.float32)
    hasher.update(f"{contiguous.shape[0]}x{contiguous.shape[1]}".encode())
    hasher.update(contiguous.tobytes())
    hasher.update(b"\x00")
    hasher.update("\n".join(item_refs).encode())
    return f"{DIGEST_ALGORITHM}:{hasher.hexdigest()}"


def write_bundle(
    path: Path,
    *,
    embeddings: NDArray[np.float32] | torch.Tensor,
    item_refs: list[str],
    tenant_id: uuid.UUID,
    model_version_id: uuid.UUID,
    training_job_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    feature_contract: FeatureContract,
    created_at: dt.datetime | None = None,
    notes: dict[str, str] | None = None,
) -> BundleManifest:
    """Seal a matrix and its labels into one file, atomically.

    Atomic for the reason `save_checkpoint` is: the upload that follows must
    either find a whole bundle or find nothing, and a half-written file that
    happens to parse is the worst of the three outcomes.
    """
    matrix = _as_float32(embeddings)
    if matrix.ndim != 2:
        msg = f"item embeddings must be a matrix, got shape {matrix.shape}"
        raise BundleError(msg)
    if matrix.shape[0] != len(item_refs):
        # Caught here rather than at load, because here there is still someone
        # to blame. At load there is only a tenant waiting for a recommendation.
        msg = f"{matrix.shape[0]} embedding rows for {len(item_refs)} items"
        raise BundleError(msg)

    manifest = BundleManifest(
        tenant_id=tenant_id,
        model_version_id=model_version_id,
        training_job_id=training_job_id,
        snapshot_id=snapshot_id,
        embedding_dim=int(matrix.shape[1]),
        item_refs=list(item_refs),
        feature_contract=feature_contract,
        payload_digest=payload_digest(matrix, item_refs),
        created_at=created_at or dt.datetime.now(dt.UTC),
        notes=notes or {},
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".partial")
    os.close(handle)
    try:
        save_file(
            {EMBEDDINGS_KEY: torch.from_numpy(matrix).contiguous()},
            temporary,
            metadata={MANIFEST_KEY: json.dumps(manifest.as_dict())},
        )
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return manifest


def load_bundle(path: Path, *, tenant_id: uuid.UUID) -> Bundle:
    """Read a bundle, refusing it unless every claim it makes holds.

    `tenant_id` is required rather than optional. A signature with a default
    would let a caller load a bundle without deciding whose it is, and the one
    caller who forgot would be the incident. The checks, in order:

    1. it parses as safetensors at all;
    2. it carries a manifest written by this code;
    3. the manifest's format version is one this build reads;
    4. the manifest names *this* tenant;
    5. it has an item matrix;
    6. the matrix's shape matches what the manifest promised;
    7. the payload digest over matrix and labels matches.

    Tenant before shape on purpose: another tenant's bundle is a security
    failure and a malformed one is an operational failure, and the first
    question a log line should answer is which of those happened.
    """
    try:
        tensors = load_file(str(path))
    except Exception as error:
        msg = f"{path.name} is not a readable safetensors file"
        raise BundleError(msg) from error

    manifest = _read_manifest(path)
    if manifest.format_version != FORMAT_VERSION:
        msg = (
            f"{path.name} is bundle format {manifest.format_version}, "
            f"and this build reads {FORMAT_VERSION}"
        )
        raise BundleError(msg)
    if manifest.tenant_id != tenant_id:
        # No identifiers in the message. This is the one refusal whose text
        # could tell one tenant something about another.
        msg = f"{path.name} was built for a different tenant"
        raise BundleError(msg)

    if EMBEDDINGS_KEY not in tensors:
        msg = f"{path.name} has no {EMBEDDINGS_KEY!r} tensor"
        raise BundleError(msg)
    matrix = tensors[EMBEDDINGS_KEY].to(torch.float32).cpu().numpy()

    expected = (manifest.item_count, manifest.embedding_dim)
    if matrix.shape != expected:
        msg = f"{path.name} holds a {matrix.shape} matrix where its manifest promises {expected}"
        raise BundleError(msg)

    actual = payload_digest(matrix, manifest.item_refs)
    if actual != manifest.payload_digest:
        msg = f"{path.name} does not match the digest in its own manifest"
        raise BundleError(msg)

    return Bundle(manifest=manifest, item_embeddings=matrix)


def read_manifest(path: Path) -> BundleManifest:
    """The manifest alone, without materialising the matrix.

    For the caller that wants to know whose bundle this is before deciding to
    spend the memory — the reconciler inspecting an artifact it did not build.
    """
    return _read_manifest(path)


def _read_manifest(path: Path) -> BundleManifest:
    from safetensors import safe_open

    try:
        with safe_open(str(path), framework="pt") as handle:
            metadata = handle.metadata() or {}
    except Exception as error:
        msg = f"{path.name} is not a readable safetensors file"
        raise BundleError(msg) from error

    raw = metadata.get(MANIFEST_KEY)
    if raw is None:
        msg = f"{path.name} has no {MANIFEST_KEY!r} manifest — it was not written by this code"
        raise BundleError(msg)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        msg = f"{path.name} has a manifest that is not JSON"
        raise BundleError(msg) from error
    if not isinstance(parsed, dict):
        msg = f"{path.name} has a manifest that is not an object"
        raise BundleError(msg)
    return BundleManifest.from_dict(parsed)


def _as_float32(embeddings: NDArray[np.float32] | torch.Tensor) -> NDArray[np.float32]:
    if isinstance(embeddings, torch.Tensor):
        return np.ascontiguousarray(embeddings.detach().cpu().numpy(), dtype=np.float32)
    return np.ascontiguousarray(embeddings, dtype=np.float32)


__all__ = [
    "BUNDLE_NAME",
    "DIGEST_ALGORITHM",
    "EMBEDDINGS_KEY",
    "FORMAT_VERSION",
    "MANIFEST_KEY",
    "Bundle",
    "BundleError",
    "BundleManifest",
    "FeatureContract",
    "load_bundle",
    "payload_digest",
    "read_manifest",
    "write_bundle",
]
