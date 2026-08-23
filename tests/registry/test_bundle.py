"""What a bundle must survive being asked before it may serve traffic.

Phase 10's two exit criteria live here: a corrupted bundle is refused at load,
and a foreign-tenant manifest is refused. Both are written as *load* tests
rather than as write tests, because the write side is ours and the load side is
where an artifact that somebody else could have touched is admitted.

The corruptions are deliberately of different kinds — a truncated file, a file
that is not safetensors at all, a file whose header survived while its weights
were replaced, a manifest that promises a shape the tensor does not have. A
single "corrupt the file" test would pass against a loader that only checked one
of them, and the one it did not check is the one that reaches production.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import numpy as np
import pytest
import torch
from safetensors.torch import load_file, save_file

from graphrec.ml import bundle as bundle_ops

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")

CONTRACT = bundle_ops.FeatureContract(
    feature_builder_version=1, static_feature_dim=3, category_count=4
)


def _write(tmp_path, *, tenant_id=TENANT, items=6, dim=8):
    path = tmp_path / bundle_ops.BUNDLE_NAME
    rng = np.random.default_rng(7)
    embeddings = rng.standard_normal((items, dim), dtype=np.float32)
    manifest = bundle_ops.write_bundle(
        path,
        embeddings=embeddings,
        item_refs=[f"SKU-{index:03d}" for index in range(items)],
        tenant_id=tenant_id,
        model_version_id=uuid.uuid4(),
        training_job_id=uuid.uuid4(),
        snapshot_id=uuid.uuid4(),
        feature_contract=CONTRACT,
        created_at=dt.datetime(2026, 8, 23, 9, 0, tzinfo=dt.UTC),
    )
    return path, manifest, embeddings


# ------------------------------------------------------------- the happy path


def test_a_bundle_round_trips_its_matrix_and_its_labels(tmp_path) -> None:
    path, manifest, embeddings = _write(tmp_path)

    loaded = bundle_ops.load_bundle(path, tenant_id=TENANT)

    assert loaded.manifest.tenant_id == TENANT
    assert loaded.manifest.item_refs == manifest.item_refs
    assert loaded.manifest.embedding_dim == 8
    assert loaded.manifest.item_count == 6
    np.testing.assert_allclose(loaded.item_embeddings, embeddings)


def test_the_manifest_is_readable_without_loading_the_matrix(tmp_path) -> None:
    """The reconciler asks whose bundle this is before spending the memory."""
    path, manifest, _ = _write(tmp_path)

    assert bundle_ops.read_manifest(path).model_version_id == manifest.model_version_id


def test_a_manifest_carries_the_feature_contract_phase_11_will_check(tmp_path) -> None:
    path, _, _ = _write(tmp_path)

    contract = bundle_ops.load_bundle(path, tenant_id=TENANT).manifest.feature_contract

    assert contract == CONTRACT


def test_the_payload_digest_covers_the_labels_and_not_only_the_matrix() -> None:
    """Swapping two rows *and* their labels is a change no digest over either
    one alone would notice, and it recommends the wrong products."""
    embeddings = np.arange(12, dtype=np.float32).reshape(3, 4)
    refs = ["A", "B", "C"]

    reordered = embeddings[[1, 0, 2]]
    assert bundle_ops.payload_digest(embeddings, refs) != bundle_ops.payload_digest(
        reordered, ["B", "A", "C"]
    )


def test_a_mismatched_row_count_is_refused_at_write_not_at_load(tmp_path) -> None:
    """Caught where there is still someone to blame."""
    with pytest.raises(bundle_ops.BundleError, match="3 embedding rows for 2 items"):
        bundle_ops.write_bundle(
            tmp_path / "b.safetensors",
            embeddings=np.zeros((3, 4), dtype=np.float32),
            item_refs=["A", "B"],
            tenant_id=TENANT,
            model_version_id=uuid.uuid4(),
            training_job_id=uuid.uuid4(),
            snapshot_id=uuid.uuid4(),
            feature_contract=CONTRACT,
        )


# ------------------------------------------------------ the two exit criteria


def test_a_foreign_tenant_manifest_is_refused_at_load(tmp_path) -> None:
    """Phase 10's second exit criterion.

    The path is under the wrong tenant's prefix too, but that is a claim made by
    whoever built the path. This one is sealed inside the artifact.
    """
    path, _, _ = _write(tmp_path, tenant_id=OTHER_TENANT)

    with pytest.raises(bundle_ops.BundleError, match="different tenant"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_the_refusal_for_a_foreign_bundle_names_no_identifiers(tmp_path) -> None:
    """The one refusal whose text could tell one tenant about another."""
    path, _, _ = _write(tmp_path, tenant_id=OTHER_TENANT)

    with pytest.raises(bundle_ops.BundleError) as caught:
        bundle_ops.load_bundle(path, tenant_id=TENANT)

    assert str(OTHER_TENANT) not in str(caught.value)


def test_a_truncated_bundle_is_refused_at_load(tmp_path) -> None:
    """Phase 10's first exit criterion, in its most ordinary form."""
    path, _, _ = _write(tmp_path)
    whole = path.read_bytes()
    path.write_bytes(whole[: len(whole) // 2])

    with pytest.raises(bundle_ops.BundleError, match="not a readable safetensors file"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_a_file_that_is_not_safetensors_at_all_is_refused(tmp_path) -> None:
    path = tmp_path / bundle_ops.BUNDLE_NAME
    path.write_bytes(b"this is not a tensor file")

    with pytest.raises(bundle_ops.BundleError):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_swapped_weights_under_an_intact_header_are_refused(tmp_path) -> None:
    """The corruption a whole-file digest cannot see once the file is rewritten.

    This is why the manifest carries a digest of its own: the store's digest is
    recomputed on whatever bytes are there, so an attacker who rewrites the file
    end to end passes it. The payload digest was sealed when the model was
    trained and does not move.
    """
    path, _, _ = _write(tmp_path)
    from safetensors import safe_open

    with safe_open(str(path), framework="pt") as handle:
        metadata = handle.metadata()
    tensors = load_file(str(path))
    tensors[bundle_ops.EMBEDDINGS_KEY] = torch.zeros_like(tensors[bundle_ops.EMBEDDINGS_KEY])
    save_file(tensors, str(path), metadata=metadata)

    with pytest.raises(bundle_ops.BundleError, match="does not match the digest"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_a_manifest_promising_a_shape_the_tensor_does_not_have_is_refused(tmp_path) -> None:
    path, manifest, _ = _write(tmp_path)
    tensors = load_file(str(path))
    lying = manifest.as_dict() | {"embedding_dim": 999}
    save_file(tensors, str(path), metadata={bundle_ops.MANIFEST_KEY: json.dumps(lying)})

    with pytest.raises(bundle_ops.BundleError, match="manifest promises"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_a_bundle_without_a_manifest_is_refused(tmp_path) -> None:
    """A safetensors file this code did not write is not a bundle."""
    path = tmp_path / bundle_ops.BUNDLE_NAME
    save_file({bundle_ops.EMBEDDINGS_KEY: torch.zeros(3, 4)}, str(path))

    with pytest.raises(bundle_ops.BundleError, match="not written by this code"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_a_manifest_missing_a_field_is_a_refusal_and_not_a_key_error(tmp_path) -> None:
    path, manifest, _ = _write(tmp_path)
    tensors = load_file(str(path))
    partial = {k: v for k, v in manifest.as_dict().items() if k != "payload_digest"}
    save_file(tensors, str(path), metadata={bundle_ops.MANIFEST_KEY: json.dumps(partial)})

    with pytest.raises(bundle_ops.BundleError, match="not readable"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_a_bundle_from_a_future_format_is_refused_rather_than_partly_read(tmp_path) -> None:
    """ "Mostly understood" is not a state traffic should be served from."""
    path, manifest, _ = _write(tmp_path)
    tensors = load_file(str(path))
    newer = manifest.as_dict() | {"format_version": bundle_ops.FORMAT_VERSION + 1}
    save_file(tensors, str(path), metadata={bundle_ops.MANIFEST_KEY: json.dumps(newer)})

    with pytest.raises(bundle_ops.BundleError, match="bundle format"):
        bundle_ops.load_bundle(path, tenant_id=TENANT)


def test_a_partial_write_leaves_no_bundle_behind(tmp_path) -> None:
    """The crash a bundle exists to survive can happen during its own write."""
    path = tmp_path / bundle_ops.BUNDLE_NAME

    with pytest.raises(bundle_ops.BundleError):
        bundle_ops.write_bundle(
            path,
            embeddings=np.zeros((2, 2, 2), dtype=np.float32),
            item_refs=["A", "B"],
            tenant_id=TENANT,
            model_version_id=uuid.uuid4(),
            training_job_id=uuid.uuid4(),
            snapshot_id=uuid.uuid4(),
            feature_contract=CONTRACT,
        )

    assert not path.exists()
    assert list(tmp_path.glob("*.partial")) == []
