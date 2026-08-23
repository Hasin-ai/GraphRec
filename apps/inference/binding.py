"""What this process is serving, and how it came to be serving it.

An inference process is pinned to one tenant (SRS §6.4, `GRAPHREC_TENANT_ID`)
and, once bound, to one model version. `ModelBinding` is that pair plus the
epoch it was started for; `BundleBinder` is the code that produces one.

**Binding is load-then-report, never report-then-load.** `bind` downloads the
bundle, verifies its digest, refuses it unless the manifest names this tenant,
and only then builds the index and publishes the binding. `/readyz` answers from
the published binding, the driver's `observe` answers from `/readyz`, and the
reconciler swaps `active_version_id` only when it sees a ready replica serving
the desired version. That chain is ER-F-06's load-before-swap, and this module
is its first link: a bundle that will not load never produces a ready replica,
so the swap never happens and the previous version keeps answering.

**A refused bundle is a permanent failure, not a retry.** A digest mismatch or a
foreign `tenant_id` will still mismatch in thirty seconds. The process reports
itself unready and says why; the reconciler times the activation out and marks
the version `failed_deployment`. Retrying here would turn a decidable failure
into a deployment that is merely slow.

**The target can move under a running process.** In the pinned deployment the
driver hands the version in the environment and a new version means a new
container. In shared-process development there is one process and desired state
changes in the database, so `refresh` re-reads it and rebinds. Both paths run the
same `bind`, because a development mode that skipped digest verification would
be a development mode that never exercised the check.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.db.models import ModelDeployment, ModelVersion
from graphrec.ml.bundle import BUNDLE_NAME, BundleError, load_bundle
from graphrec.storage import keys

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.ml.bundle import Bundle
    from graphrec.ml.index import CandidateIndex, IndexKey
    from graphrec.storage.store import ArtifactStore

logger = logging.getLogger(__name__)


class BindingError(RuntimeError):
    """The bundle this process was told to serve cannot be served.

    Distinct from `BundleError`, which says the bytes are wrong. This also
    covers "there is no such version" and "the store has nothing at that key" —
    the operational half of the same outcome.
    """


@dataclass(frozen=True, slots=True)
class ModelBinding:
    """One loaded version, and the desired-state epoch it was loaded for.

    `epoch` is carried so drift is visible. A process bound at epoch 4 that is
    still running when the deployment is on epoch 5 is serving a version nobody
    asked for any more — indistinguishable from a healthy process if the only
    thing recorded were the version id, because a rollback to v7 and a fresh
    activation of v7 are the same version and different intentions.
    """

    tenant_id: uuid.UUID
    model_version_id: uuid.UUID
    version_number: int
    epoch: int
    item_count: int

    @property
    def index_key(self) -> IndexKey:
        return (self.tenant_id, self.model_version_id)


@dataclass(frozen=True, slots=True)
class BindingTarget:
    """What desired state says this process should be serving."""

    model_version_id: uuid.UUID
    epoch: int


class BundleBinder:
    """Resolves a target, loads its bundle, and publishes the binding.

    Holds the index because the index is the loaded bundle. Everything else —
    the session, the store — is passed per call, as everywhere else in this
    codebase.
    """

    def __init__(
        self,
        *,
        index: CandidateIndex,
        store: ArtifactStore,
        tenant_id: uuid.UUID,
        pinned_version_id: uuid.UUID | None = None,
    ) -> None:
        self._index = index
        self._store = store
        self._tenant_id = tenant_id
        self._pinned_version_id = pinned_version_id
        self._binding: ModelBinding | None = None
        self._failure: str | None = None
        # One rebind at a time. Two concurrent refreshes would both download,
        # both build, and the loser would overwrite the winner's index with an
        # older version — a race whose symptom is a replica quietly serving the
        # version it was replacing.
        self._lock = asyncio.Lock()

    @property
    def binding(self) -> ModelBinding | None:
        """What is resident, or `None` before the first successful load."""
        return self._binding

    @property
    def failure(self) -> str | None:
        """Why the last attempt failed, for `/readyz` to report."""
        return self._failure

    def is_ready(self) -> bool:
        """`ready` in the sense `serving_replicas.ready` means it.

        The index must actually hold the bound version. A binding recorded
        beside an index that was dropped would be a process reporting readiness
        for a matrix it no longer has.
        """
        return self._binding is not None and self._binding.index_key in self._index.loaded()

    async def target(self, session: AsyncSession) -> BindingTarget | None:
        """The version desired state says to serve.

        A pinned process was told at start-up and does not ask: the driver put
        the version in the environment, and a process that re-read the database
        could disagree with the container it is running in. The epoch still
        comes from the row, because that is the number the reconciler compares
        against when it decides whether this replica is stale.
        """
        deployment: ModelDeployment | None = await session.scalar(
            sa.select(ModelDeployment).limit(1)
        )
        epoch = deployment.epoch if deployment else 0

        if self._pinned_version_id is not None:
            return BindingTarget(model_version_id=self._pinned_version_id, epoch=epoch)
        if deployment is None:
            return None
        # Desired before active: during an activation the process should be
        # loading what was asked for, which is the whole of load-before-swap.
        # `active` is the answer once the swap has happened and after a restart.
        wanted = deployment.desired_version_id or deployment.active_version_id
        if wanted is None:
            return None
        return BindingTarget(model_version_id=wanted, epoch=epoch)

    async def refresh(self, session: AsyncSession) -> ModelBinding | None:
        """Bind if the target moved; otherwise leave everything alone.

        Called on a timer. The common case is "nothing changed", and it costs
        one indexed read of one row.
        """
        target = await self.target(session)
        if target is None:
            return self._binding
        current = self._binding
        if (
            current is not None
            and current.model_version_id == target.model_version_id
            and current.epoch == target.epoch
        ):
            return current
        return await self.bind(session, target=target)

    async def bind(self, session: AsyncSession, *, target: BindingTarget) -> ModelBinding:
        """Download, verify, build, publish — in that order, always.

        Publishing last is the point. Until the last line of this method the
        process is still ready for whatever it was serving before, so a failed
        activation costs a log line and an unready *new* replica rather than an
        outage on the old one.
        """
        async with self._lock:
            version = await session.get(ModelVersion, target.model_version_id)
            if version is None:
                # Under RLS this also covers another tenant's version: the row
                # is not visible, so it does not exist as far as this process
                # is concerned. Which is the correct answer to give it.
                self._failure = "unknown model version"
                raise BindingError(self._failure)

            key = keys.bundle_key(self._tenant_id, version.model_version_id, BUNDLE_NAME)
            if not self._store.exists(key):
                self._failure = "bundle artifact is missing from the store"
                raise BindingError(self._failure)

            try:
                bundle = await asyncio.to_thread(self._load, key)
            except BundleError as error:
                # The manifest named another tenant, or the digest did not
                # match. Both are refusals to serve, and neither is retried.
                self._failure = str(error)
                logger.error(
                    "bundle_refused",
                    extra={
                        "tenant_id": str(self._tenant_id),
                        "model_version_id": str(version.model_version_id),
                        "detail": self._failure,
                    },
                )
                raise BindingError(self._failure) from error

            if bundle.manifest.model_version_id != version.model_version_id:
                # The bytes are a valid bundle for this tenant, and for a
                # different version. Serving them would report `model_version`
                # v8 while answering from v6's embeddings — ER-F-05's field
                # made into a lie.
                self._failure = "bundle names a different model version"
                raise BindingError(self._failure)

            await asyncio.to_thread(self._index.build, bundle)
            binding = ModelBinding(
                tenant_id=self._tenant_id,
                model_version_id=version.model_version_id,
                version_number=version.version_number,
                epoch=target.epoch,
                item_count=bundle.manifest.item_count,
            )
            previous = self._binding
            self._binding = binding
            self._failure = None
            logger.info(
                "bundle_bound",
                extra={
                    "tenant_id": str(self._tenant_id),
                    "model_version_id": str(binding.model_version_id),
                    "version_number": binding.version_number,
                    "epoch": binding.epoch,
                    "items": binding.item_count,
                },
            )
            if previous is not None and previous.model_version_id != binding.model_version_id:
                # Free the old matrix. Not before the new one is built: a
                # process that dropped first would be unready for the length of
                # a download for no reason.
                self._index.drop(previous.index_key)
            return binding

    def _load(self, key: str) -> Bundle:
        """Blocking half of `bind`, run on a thread.

        A temporary directory rather than a cache: a bundle is tens of
        megabytes, it is read once into memory, and a cache would introduce the
        question of whether the file on disk is the file the digest was checked
        against.
        """
        with tempfile.TemporaryDirectory(prefix="graphrec-bundle-") as scratch:
            path = Path(scratch) / BUNDLE_NAME
            self._store.get_file(key, path)
            return load_bundle(path, tenant_id=self._tenant_id)

    def describe(self) -> dict[str, object]:
        """What `/readyz` renders. No secrets, no keys, no paths."""
        binding = self._binding
        return {
            "ready": self.is_ready(),
            "tenant_id": str(self._tenant_id),
            "model_version": (
                {
                    "version_id": str(binding.model_version_id),
                    "version_number": binding.version_number,
                }
                if binding is not None
                else None
            ),
            "epoch": binding.epoch if binding else None,
            "detail": self._failure,
        }


__all__ = ["BindingError", "BindingTarget", "BundleBinder", "ModelBinding"]
