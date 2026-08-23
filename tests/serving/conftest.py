"""Fixtures for the serving suite.

Everything here is real: real rows under real policies, a real bundle written by
`write_bundle` and read back by `load_bundle`, a real `LocalArtifactStore`, and
`InProcessDriver` rather than a mock. That is not thoroughness for its own sake
— it is what the phase's claims require. Load-before-swap is a property of the
sequence `apply → observe → swap`, and a driver whose `observe` returned
whatever a test wanted would test the assertion instead of the sequence.

Two tenants, because "this tenant's products are never returned to that one" is
not a statement one tenant can make.

The catalogue is seeded with a deliberate shape:

* `alpha` has ten products across two categories and enough interaction events
  to give the popularity lane a stable order;
* one of them is inactive, so `_eligible_refs` has something to exclude and a
  lane that forgot the predicate would be visible;
* `beta` has products whose external ids *collide* with alpha's, which is the
  only arrangement in which a cross-tenant leak is detectable — matching ids
  mean a leaked row looks like a correct answer.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from typing import TYPE_CHECKING

import numpy as np
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.inference.main import create_app
from graphrec.common.config import ArtifactStoreKind
from graphrec.common.enums import ModelVersionStatus, TenantStatus
from graphrec.db.tenant_context import bind_tenant
from graphrec.ml.bundle import BUNDLE_NAME, FeatureContract, write_bundle
from graphrec.storage import keys
from graphrec.storage.local import LocalArtifactStore
from tests.isolation.conftest import _force_lifted

if TYPE_CHECKING:
    import pathlib
    from collections.abc import AsyncIterator, Callable, Iterator

pytestmark = [pytest.mark.db]

#: Fixed, so "the 24-hour window" is a window and not a race with the clock.
NOW = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.UTC)

DIGEST = "sha256:" + "cd" * 32

#: Two categories, so the category lane has something to prefer and the
#: diversity cap has something to spread across.
CATALOGUE = {
    "SKU-01": "home",
    "SKU-02": "home",
    "SKU-03": "home",
    "SKU-04": "home",
    "SKU-05": "home",
    "SKU-06": "away",
    "SKU-07": "away",
    "SKU-08": "away",
    "SKU-09": "away",
    "SKU-10": "away",
}
#: Inactive. Never recommended, by any lane, ever.
WITHDRAWN = "SKU-10"

EMBEDDING_DIM = 8


def _app_url() -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    password = os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
    return f"postgresql+psycopg://graphrec_app:{password}@{tail}"


@pytest.fixture
async def serving_sessionmaker(owner_engine) -> AsyncIterator[async_sessionmaker]:
    """Sessions as `graphrec_app` — the role an inference process runs as.

    `NullPool` for the reason the ingestion suite gives: several tests hold a
    second session open to observe what a first has published, and a pool sized
    for one request would wait on itself.
    """
    engine = create_async_engine(_app_url(), poolclass=sa.pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


@pytest.fixture
def seed_engine_sync(owner_engine) -> Iterator:
    """A synchronous connection as `graphrec_app`.

    The seeds run as the runtime role, not as the owner, for the reason the
    ingestion suite gives: the owner is `FORCE`d and no policy names it, so an
    insert as the owner is refused — and an arrangement that only the owner
    could set up would prove nothing about the role that has to live with it.
    """
    engine = sa.create_engine(_app_url(), poolclass=sa.pool.NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def bound_serving(serving_sessionmaker) -> Callable:
    """`async with bound_serving(tenant_id) as session:` — bound and in a
    transaction, exactly as a request would be."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _bound(tenant_id: uuid.UUID) -> AsyncIterator:
        async with serving_sessionmaker() as session, session.begin():
            await bind_tenant(session, tenant_id)
            yield session

    return _bound


#: Written by the serving path and by nothing else, so the sweep is narrow and
#: dependents come before their parents.
_SERVING_TABLES = (
    "recommendation_feedback",
    "recommendation_impressions",
    "recommendation_results",
    "recommendation_requests",
    "serving_replicas",
    "deployment_revisions",
    "model_activation_history",
    "model_deployments",
)

_CATALOGUE_TABLES = (
    "usage_events",
    "monthly_usage_aggregates",
    "interaction_events",
    "customers",
    "products",
    "product_categories",
)

_REGISTRY_TABLES = (
    "model_evaluation_metrics",
    "model_versions",
    "dataset_snapshots",
    "training_jobs",
    "models",
    "jobs",
)


def _wipe(owner_engine, tables: tuple[str, ...]) -> None:
    for table in tables:
        with owner_engine.begin() as conn, _force_lifted(conn, table):
            conn.execute(sa.text(f"DELETE FROM {table}"))


@pytest.fixture
def _empty_serving(owner_engine) -> Iterator[None]:
    """Nothing before, nothing after.

    A deployment left behind is a deployment the *next* test's reconciler pass
    converges, and the failure that produces is both intermittent and blamed on
    the wrong test.
    """
    order = _SERVING_TABLES + _CATALOGUE_TABLES + _REGISTRY_TABLES
    _wipe(owner_engine, order)
    yield
    _wipe(owner_engine, order)


@pytest.fixture
def serving_tenants(
    owner_engine, seed_engine_sync, _empty_serving
) -> Iterator[dict[str, uuid.UUID]]:
    """Two active tenants on the same plan."""
    tenants = {"alpha": uuid.uuid4(), "beta": uuid.uuid4()}
    with seed_engine_sync.begin() as conn:
        plan_id = conn.execute(
            sa.text("SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH'")
        ).scalar_one()
        for label, tenant_id in tenants.items():
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            conn.execute(
                sa.text(
                    "INSERT INTO tenants (tenant_id, plan_id, tenant_code, tenant_name, status) "
                    "VALUES (:tid, :plan, :code, :name, :status)"
                ),
                {
                    "tid": tenant_id,
                    "plan": plan_id,
                    "code": f"srv-{label}-{tenant_id.hex[:8]}",
                    "name": f"Serving {label}",
                    "status": TenantStatus.ACTIVE.value,
                },
            )
    yield tenants
    # No role holds `DELETE` on `tenants` and the owner is fenced out by
    # `FORCE`. Teardown is migration 0002's documented exception.
    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id = ANY(:ids)"),
            {"ids": list(tenants.values())},
        )


@pytest.fixture
def seed_catalogue(seed_engine_sync) -> Callable[[uuid.UUID], dict[str, uuid.UUID]]:
    """Ten products, two categories, one customer and a history.

    Event counts descend with the product number, so the popularity lane's order
    is `SKU-01, SKU-02, …` — an order a test can state rather than discover, and
    one that a change in tie-breaking would visibly disturb.
    """

    def _seed(tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
        ids: dict[str, uuid.UUID] = {}
        with seed_engine_sync.begin() as conn:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            categories: dict[str, uuid.UUID] = {}
            for name in ("home", "away"):
                category_id = uuid.uuid4()
                categories[name] = category_id
                conn.execute(
                    sa.text(
                        "INSERT INTO product_categories (category_id, tenant_id, "
                        "    external_category_id, name) VALUES (:cid, :tid, :ext, :name)"
                    ),
                    {"cid": category_id, "tid": tenant_id, "ext": f"cat-{name}", "name": name},
                )

            # Two customers, because `interaction_events.customer_id` is NOT
            # NULL and the popularity lane must be fed by *somebody*. `CUST-1`
            # has a two-item history — enough for `personalized`, short enough
            # that the graph lane's answer is not the whole catalogue — and
            # `CROWD` carries everything else.
            customer_id, crowd_id = uuid.uuid4(), uuid.uuid4()
            for label, cid in (("CUST-1", customer_id), ("CROWD", crowd_id)):
                conn.execute(
                    sa.text(
                        "INSERT INTO customers (customer_id, tenant_id, external_customer_id, "
                        "    first_seen_at, last_seen_at) VALUES (:cid, :tid, :ext, :at, :at)"
                    ),
                    {
                        "cid": cid,
                        "tid": tenant_id,
                        "ext": label,
                        "at": NOW - dt.timedelta(days=1),
                    },
                )
            ids["customer"] = customer_id
            ids["crowd"] = crowd_id

            for position, (ref, category) in enumerate(CATALOGUE.items()):
                product_id = uuid.uuid4()
                ids[ref] = product_id
                conn.execute(
                    sa.text(
                        "INSERT INTO products (product_id, tenant_id, external_product_id, "
                        "    category_id, title, is_active, disabled_reason, disabled_at) "
                        "VALUES (:pid, :tid, :ext, :cat, :title, :active, :reason, :disabled)"
                    ),
                    {
                        "pid": product_id,
                        "tid": tenant_id,
                        "ext": ref,
                        "cat": categories[category],
                        "title": f"Product {ref}",
                        "active": ref != WITHDRAWN,
                        "reason": None if ref != WITHDRAWN else "Withdrawn from sale.",
                        "disabled": None if ref != WITHDRAWN else NOW,
                    },
                )
                # Descending counts, and only the first two attributed to the
                # customer — so `personalized` has a short history and the
                # popularity lane has a long tail.
                for event in range(len(CATALOGUE) - position):
                    event_id = uuid.uuid4()
                    conn.execute(
                        sa.text(
                            "INSERT INTO interaction_events (event_id, tenant_id, "
                            "    external_event_id, customer_id, product_id, event_type, "
                            "    occurred_at, received_at) "
                            "VALUES (:eid, :tid, :ext, :cust, :pid, 'view', :at, :at)"
                        ),
                        {
                            "eid": event_id,
                            "tid": tenant_id,
                            "ext": f"ev-{event_id.hex[:12]}",
                            "cust": customer_id if position < 2 else crowd_id,
                            "pid": product_id,
                            "at": NOW - dt.timedelta(hours=event + 1),
                        },
                    )
        return ids

    return _seed


@pytest.fixture
def seed_model_version(seed_engine_sync) -> Callable[..., uuid.UUID]:
    """A version, and the run and snapshot `RESTRICT` requires behind it.

    Synchronous and through the owner, because this is arranging the world the
    test is about rather than exercising a code path — the registry suite covers
    the path that produces these rows.
    """

    def _seed(
        tenant_id: uuid.UUID,
        *,
        version_number: int,
        status: ModelVersionStatus = ModelVersionStatus.ELIGIBLE,
        model_id: uuid.UUID | None = None,
        artifact_uri: str | None = None,
    ) -> uuid.UUID:
        version_id = uuid.uuid4()
        with seed_engine_sync.begin() as conn:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            if model_id is None:
                model_id = conn.execute(
                    sa.text("SELECT model_id FROM models WHERE tenant_id = :tid LIMIT 1"),
                    {"tid": tenant_id},
                ).scalar()
            if model_id is None:
                model_id = uuid.uuid4()
                conn.execute(
                    sa.text(
                        "INSERT INTO models (model_id, tenant_id, name, model_type) "
                        "VALUES (:mid, :tid, 'default', 'DGSR')"
                    ),
                    {"mid": model_id, "tid": tenant_id},
                )
            job_id, training_job_id = uuid.uuid4(), uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO jobs (job_id, tenant_id, job_type, status, completed_at) "
                    "VALUES (:jid, :tid, 'training', 'succeeded', now())"
                ),
                {"jid": job_id, "tid": tenant_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO training_jobs (training_job_id, tenant_id, job_id, model_id, "
                    "    request_ref, state, interaction_window_days, max_epochs, requested_at, "
                    "    completed_at) "
                    "VALUES (:tjid, :tid, :jid, :mid, :ref, 'succeeded', 90, 20, :at, :at)"
                ),
                {
                    "tjid": training_job_id,
                    "tid": tenant_id,
                    "jid": job_id,
                    "mid": model_id,
                    "ref": f"srv-{training_job_id.hex[:8]}",
                    "at": NOW,
                },
            )
            snapshot_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO dataset_snapshots (snapshot_id, tenant_id, training_job_id, "
                    "    cutoff_at, window_days, uri, checksum, sequence_count, product_count, "
                    "    event_count) "
                    "VALUES (:sid, :tid, :tjid, :at, 90, :uri, :digest, 100, 10, 500)"
                ),
                {
                    "sid": snapshot_id,
                    "tid": tenant_id,
                    "tjid": training_job_id,
                    "at": NOW,
                    "uri": f"s3://snapshots/{snapshot_id}/dataset.parquet",
                    "digest": DIGEST,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO model_versions (model_version_id, tenant_id, model_id, "
                    "    version_number, status, training_job_id, snapshot_id, artifact_uri, "
                    "    artifact_digest, feature_contract, embedding_dim, metrics, created_at) "
                    "VALUES (:vid, :tid, :mid, :n, :status, :tjid, :sid, :uri, :digest, "
                    "    CAST(:contract AS jsonb), :dim, CAST('{}' AS jsonb), :created)"
                ),
                {
                    "vid": version_id,
                    "tid": tenant_id,
                    "mid": model_id,
                    "n": version_number,
                    "status": status.value,
                    "tjid": training_job_id,
                    "sid": snapshot_id,
                    "uri": artifact_uri or f"s3://artifacts/{tenant_id}/{version_id}/{BUNDLE_NAME}",
                    "digest": DIGEST,
                    "contract": '{"features": ["sequence"]}',
                    "dim": EMBEDDING_DIM,
                    "created": NOW + dt.timedelta(minutes=version_number),
                },
            )
        return version_id

    return _seed


@pytest.fixture
def artifact_store(tmp_path: pathlib.Path) -> LocalArtifactStore:
    """A store on disk. Not a fake: `BundleBinder` calls `get_file` and then
    `load_bundle`, and the digest check the loader performs is half of what the
    binding tests assert."""
    return LocalArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def publish_bundle(artifact_store, tmp_path: pathlib.Path) -> Callable[..., np.ndarray]:
    """Write a real bundle for a version and put it where the binder looks.

    The embeddings are seeded per version so two versions produce *different*
    orders — which is what makes "the answer came from v8" an observation rather
    than an assumption.
    """

    def _publish(
        tenant_id: uuid.UUID,
        version_id: uuid.UUID,
        *,
        manifest_tenant_id: uuid.UUID | None = None,
        seed: int = 7,
        item_refs: list[str] | None = None,
    ) -> np.ndarray:
        refs = item_refs or list(CATALOGUE)
        rng = np.random.default_rng(seed)
        matrix = rng.standard_normal((len(refs), EMBEDDING_DIM), dtype=np.float32)
        path = tmp_path / f"bundle-{version_id.hex[:8]}.safetensors"
        write_bundle(
            path,
            embeddings=matrix,
            item_refs=refs,
            # The manifest's tenant is a *parameter*, so a test can write a
            # bundle that belongs to somebody else and watch it be refused.
            tenant_id=manifest_tenant_id or tenant_id,
            model_version_id=version_id,
            training_job_id=uuid.uuid4(),
            snapshot_id=uuid.uuid4(),
            feature_contract=FeatureContract(
                feature_builder_version=1, static_feature_dim=3, category_count=2
            ),
            created_at=NOW,
        )
        artifact_store.put_file(keys.bundle_key(tenant_id, version_id, BUNDLE_NAME), path)
        return matrix

    return _publish


@pytest.fixture
def seed_deployment(seed_engine_sync) -> Callable[..., uuid.UUID]:
    """A `model_deployments` row wanting one replica of nothing yet."""

    def _seed(
        tenant_id: uuid.UUID,
        *,
        model_id: uuid.UUID | None = None,
        active_version_id: uuid.UUID | None = None,
        desired_version_id: uuid.UUID | None = None,
        desired_replicas: int = 1,
        min_replicas: int = 1,
    ) -> uuid.UUID:
        deployment_id = uuid.uuid4()
        with seed_engine_sync.begin() as conn:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            if model_id is None:
                model_id = conn.execute(
                    sa.text("SELECT model_id FROM models WHERE tenant_id = :tid LIMIT 1"),
                    {"tid": tenant_id},
                ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO model_deployments (deployment_id, tenant_id, model_id, state, "
                    "    active_version_id, desired_version_id, desired_replicas, "
                    "    min_replicas, max_replicas, ready_replicas, epoch) "
                    "VALUES (:did, :tid, :mid, :state, :active, :desired, :want, "
                    "    :floor, :ceiling, 0, 1)"
                ),
                {
                    "did": deployment_id,
                    "tid": tenant_id,
                    "mid": model_id,
                    "state": "available" if active_version_id else "pending",
                    "active": active_version_id,
                    "desired": desired_version_id,
                    "want": desired_replicas,
                    # `set_desired` resets the count to `min_replicas`, because
                    # a re-activation must not silently keep a scale somebody
                    # applied by hand. A test that wants three replicas has to
                    # want three as policy.
                    "floor": min_replicas,
                    "ceiling": max(min_replicas, desired_replicas, 2),
                },
            )
        return deployment_id

    return _seed


@pytest.fixture
def issue_credential(seed_engine_sync, settings) -> Callable[..., str]:
    """A real credential for a tenant, returning the secret the caller presents.

    The row is written directly rather than through `CredentialService.create`
    because the digest is the only part that has to be genuine: the data plane
    verifies a presented secret against `key_hash` with the process's pepper,
    and a hand-written row proves that path works without dragging the whole
    creation policy (caps, expiry validation, audit) into a serving test.
    """
    from graphrec.auth import api_keys as secrets_lib

    def _issue(
        tenant_id: uuid.UUID,
        *,
        scopes: list[str] | None = None,
        expires_in_days: int = 30,
        revoked: bool = False,
    ) -> str:
        generated = secrets_lib.issue(
            pepper=settings.api_key_hmac_pepper.get_secret_value(),
            hash_version=settings.api_key_hash_version,
        )
        now = dt.datetime.now(dt.UTC)
        with seed_engine_sync.begin() as conn:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            conn.execute(
                sa.text(
                    "INSERT INTO api_keys (tenant_id, name, visible_prefix, key_hash, "
                    "    hash_version, scopes, expires_at, revoked_at) "
                    "VALUES (:tid, :name, :prefix, :hash, :hv, :scopes, :exp, :rev)"
                ),
                {
                    "tid": tenant_id,
                    "name": f"serving-test-{generated.visible_prefix}",
                    "prefix": generated.visible_prefix,
                    "hash": generated.digest,
                    "hv": generated.hash_version,
                    "scopes": scopes
                    if scopes is not None
                    else ["recommendations:read", "feedback:write"],
                    "exp": now + dt.timedelta(days=expires_in_days),
                    "rev": now if revoked else None,
                },
            )
        return generated.secret

    return _issue


@pytest.fixture
def pinned_app(settings, artifact_store, monkeypatch):
    """`create_app` for a given tenant, with the store the fixtures publish to.

    A factory rather than a fixture with a fixed tenant, because the interesting
    test here is the one that presents *beta's* credential to *alpha's* process,
    and that needs both to exist at once.
    """

    def _build(tenant_id: uuid.UUID, *, pinned_version_id: uuid.UUID | None = None) -> Iterator:
        if pinned_version_id is None:
            monkeypatch.delenv("GRAPHREC_MODEL_VERSION_ID", raising=False)
        else:
            monkeypatch.setenv("GRAPHREC_MODEL_VERSION_ID", str(pinned_version_id))
        return create_app(
            settings.model_copy(
                update={
                    "tenant_id": tenant_id,
                    # The enum, not the string: `model_copy` does not validate,
                    # so a bare `"local"` would sit in the field unconverted and
                    # never match `ArtifactStoreKind.LOCAL` in the store factory.
                    "artifact_store": ArtifactStoreKind.LOCAL,
                    "artifact_local_root": str(artifact_store.root),
                    # The poller would otherwise fire mid-test and rebind under
                    # an assertion. The refresh at startup is the one under test.
                    "inference_poll_seconds": 3600.0,
                }
            )
        )

    return _build


@pytest.fixture
def ready_tenant(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, publish_bundle
):
    """alpha, seeded, with an active version whose bundle is on disk."""
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=3, status=ModelVersionStatus.ACTIVE)
    publish_bundle(tenant_id, version_id)
    seed_deployment(tenant_id, active_version_id=version_id, desired_version_id=version_id)
    return tenant_id, version_id


@pytest.fixture
def seed_requests(seed_engine_sync) -> Callable[..., None]:
    """Write `recommendation_requests` rows with a stated shape.

    The metrics come from these rows and from nothing else, so the fixture
    writes them directly rather than making real recommendations: a test about
    a 95th percentile needs twenty latencies it chose, and twenty real requests
    would produce twenty latencies nobody can assert on.
    """

    def _seed(
        tenant_id: uuid.UUID,
        *,
        status: str = "served",
        count: int = 1,
        latency_ms: int | None = 20,
        fallback: bool = False,
        error_class: str | None = None,
        error_reason: str | None = None,
        age: dt.timedelta = dt.timedelta(minutes=5),
        prefix: str = "m",
    ) -> None:
        # `ck_recommendation_requests_error_explained`: anything other than a
        # clean `served` must say why, and a `served` row must not invent a
        # reason. The schema makes the error panel's copy a precondition of
        # failing rather than something filled in afterwards.
        if status != "served" and error_class is None:
            error_class = "unavailable"
            error_reason = error_reason or "The recommendation service is temporarily unavailable."

        moment = dt.datetime.now(dt.UTC) - age
        with seed_engine_sync.begin() as conn:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            for index in range(count):
                conn.execute(
                    sa.text(
                        "INSERT INTO recommendation_requests (tenant_id, external_request_id, "
                        "    session_hash, strategy, fallback_applied, requested_count, "
                        "    returned_count, latency_ms, status, error_class, error_reason, "
                        "    requested_at) "
                        "VALUES (:tid, :ext, :hash, :strategy, :fallback, 10, :returned, "
                        "    :latency, :status, :eclass, :ereason, :at)"
                    ),
                    {
                        "tid": tenant_id,
                        "ext": f"{prefix}-{uuid.uuid4().hex[:12]}-{index}",
                        # An identity is required (`ck_..._identified`) and these
                        # rows belong to nobody in particular.
                        "hash": uuid.uuid4().hex,
                        "strategy": "fallback" if fallback else "personalized",
                        "fallback": fallback,
                        "returned": 0 if status == "refused" else 10,
                        "latency": latency_ms,
                        "status": status,
                        "eclass": error_class,
                        "ereason": error_reason,
                        "at": moment - dt.timedelta(seconds=index),
                    },
                )

    return _seed
