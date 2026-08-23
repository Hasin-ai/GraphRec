"""What an inference process agrees to serve, and what it refuses.

The refusals are the interesting half. A bundle whose manifest names another
tenant is not a bug to be logged and worked around — it is the one failure that,
if tolerated, would serve one customer's catalogue to another. So it is refused
at load, permanently, and the process reports itself unready with a reason
`/readyz` can render.

Everything here goes through `write_bundle` and `load_bundle` against a real
store on disk, because the digest verification is what makes the refusal
trustworthy and a hand-built `Bundle` would skip it.
"""

from __future__ import annotations

import uuid

import pytest

from apps.inference.binding import BindingError, BindingTarget, BundleBinder
from graphrec.common.enums import ModelVersionStatus
from graphrec.ml.index import InProcessIndex
from tests.serving.conftest import CATALOGUE

pytestmark = [pytest.mark.db]


def _binder(store, tenant_id, *, pinned=None) -> BundleBinder:
    return BundleBinder(
        index=InProcessIndex(), store=store, tenant_id=tenant_id, pinned_version_id=pinned
    )


async def test_a_bundle_that_names_this_tenant_binds_and_reports_ready(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
) -> None:
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=4, status=ModelVersionStatus.ACTIVE)
    publish_bundle(tenant_id, version_id)
    seed_deployment(tenant_id, active_version_id=version_id, desired_version_id=version_id)
    binder = _binder(artifact_store, tenant_id)

    async with bound_serving(tenant_id) as session:
        binding = await binder.refresh(session)

    assert binding is not None
    assert binding.model_version_id == version_id
    assert binding.version_number == 4
    assert binding.item_count == len(CATALOGUE)
    assert binder.is_ready() is True
    assert binder.failure is None


async def test_a_bundle_belonging_to_another_tenant_is_refused(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
) -> None:
    """BACKEND_PLAN L1678. The manifest is checked against the process's pin.

    The bytes are a perfectly valid bundle. They belong to somebody else, and
    that is the only fact that matters — so the process stays unready and says
    why, rather than serving beta's catalogue under alpha's name.
    """
    alpha, beta = serving_tenants["alpha"], serving_tenants["beta"]
    seed_catalogue(alpha)
    version_id = seed_model_version(alpha, version_number=1)
    seed_deployment(alpha, desired_version_id=version_id)
    # Written to alpha's key, with beta's tenant in the manifest.
    publish_bundle(alpha, version_id, manifest_tenant_id=beta)
    binder = _binder(artifact_store, alpha)

    with pytest.raises(BindingError):
        async with bound_serving(alpha) as session:
            await binder.bind(session, target=BindingTarget(model_version_id=version_id, epoch=1))

    assert binder.is_ready() is False
    assert binder.failure is not None
    assert binder.binding is None


async def test_a_bundle_naming_a_different_version_is_refused(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
    tmp_path,
) -> None:
    """ER-F-05's `model_version` field made into a lie, caught at load.

    The bytes are this tenant's and they load cleanly; they are v1's embeddings
    stored under v2's key. Serving them would report v2 and answer from v1.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    older = seed_model_version(tenant_id, version_number=1)
    newer = seed_model_version(tenant_id, version_number=2)
    seed_deployment(tenant_id, desired_version_id=newer)

    import numpy as np

    from graphrec.ml.bundle import BUNDLE_NAME, FeatureContract, write_bundle
    from graphrec.storage import keys

    path = tmp_path / "wrong-version.safetensors"
    write_bundle(
        path,
        embeddings=np.eye(8, dtype=np.float32),
        item_refs=list(CATALOGUE)[:8],
        tenant_id=tenant_id,
        model_version_id=older,
        training_job_id=uuid.uuid4(),
        snapshot_id=uuid.uuid4(),
        feature_contract=FeatureContract(
            feature_builder_version=1, static_feature_dim=3, category_count=2
        ),
    )
    artifact_store.put_file(keys.bundle_key(tenant_id, newer, BUNDLE_NAME), path)
    binder = _binder(artifact_store, tenant_id)

    with pytest.raises(BindingError) as raised:
        async with bound_serving(tenant_id) as session:
            await binder.bind(session, target=BindingTarget(model_version_id=newer, epoch=1))

    assert "different model version" in str(raised.value)


async def test_a_missing_artifact_is_a_refusal_and_not_a_crash(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
) -> None:
    """Nothing was ever uploaded. The process reports unready with a reason the
    reconciler can time out on, which is what turns this into a failed
    activation rather than a deployment that hangs."""
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id, desired_version_id=version_id)
    binder = _binder(artifact_store, tenant_id)

    with pytest.raises(BindingError):
        async with bound_serving(tenant_id) as session:
            await binder.refresh(session)

    assert binder.failure is not None
    assert binder.is_ready() is False


async def test_a_pinned_process_follows_its_pin_rather_than_the_deployment(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
) -> None:
    """The driver put the version in the environment; the row may say otherwise.

    That is not a disagreement to resolve — it is load-before-swap in progress.
    A process that re-read the database would load the version it was replacing.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    active = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    candidate = seed_model_version(tenant_id, version_number=2)
    publish_bundle(tenant_id, active, seed=1)
    publish_bundle(tenant_id, candidate, seed=2)
    seed_deployment(tenant_id, active_version_id=active, desired_version_id=active)

    binder = _binder(artifact_store, tenant_id, pinned=candidate)
    async with bound_serving(tenant_id) as session:
        binding = await binder.refresh(session)

    assert binding is not None
    assert binding.model_version_id == candidate


async def test_a_refresh_that_changes_nothing_keeps_the_binding(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
) -> None:
    """The common case, and it must not reload.

    A binder that rebuilt the index every ten seconds would spend a tenant's
    memory bandwidth on a matrix it already had, and would be unready for the
    length of a download every time.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    publish_bundle(tenant_id, version_id)
    seed_deployment(tenant_id, active_version_id=version_id, desired_version_id=version_id)
    binder = _binder(artifact_store, tenant_id)

    async with bound_serving(tenant_id) as session:
        first = await binder.refresh(session)
    async with bound_serving(tenant_id) as session:
        second = await binder.refresh(session)

    assert first is second


async def test_a_new_epoch_on_the_same_version_rebinds(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
) -> None:
    """A rollback to the version already resident is a new epoch on the same id.

    Without the epoch in the binding the two would be indistinguishable, and a
    replica would report itself as serving something nobody currently wants.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    publish_bundle(tenant_id, version_id)
    seed_deployment(tenant_id, active_version_id=version_id, desired_version_id=version_id)
    binder = _binder(artifact_store, tenant_id)

    async with bound_serving(tenant_id) as session:
        first = await binder.refresh(session)

    import sqlalchemy as sa

    from graphrec.db.models import ModelDeployment

    async with bound_serving(tenant_id) as session:
        deployment = await session.scalar(sa.select(ModelDeployment))
        assert deployment is not None
        deployment.epoch += 1

    async with bound_serving(tenant_id) as session:
        second = await binder.refresh(session)

    assert first is not None
    assert second is not None
    assert second.epoch == first.epoch + 1


async def test_describe_reveals_no_keys_and_no_paths(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    bound_serving,
    artifact_store,
    publish_bundle,
) -> None:
    """`/readyz` is reachable from inside the deployment network. It says what
    is resident and nothing about where it came from."""
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    publish_bundle(tenant_id, version_id)
    seed_deployment(tenant_id, active_version_id=version_id, desired_version_id=version_id)
    binder = _binder(artifact_store, tenant_id)
    async with bound_serving(tenant_id) as session:
        await binder.refresh(session)

    described = binder.describe()

    assert set(described) == {"ready", "tenant_id", "model_version", "epoch", "detail"}
    rendered = repr(described)
    assert "s3://" not in rendered
    assert str(artifact_store.root) not in rendered
