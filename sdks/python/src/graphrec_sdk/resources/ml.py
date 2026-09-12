from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Mapping, Optional, Union, cast
from uuid import UUID

from ..errors import InputValidationError, WaitTimeoutError
from ..models.ml import ModelVersion, ModelVersionList, TrainingJob, TrainingJobList
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncModelVersions", "AsyncTrainingJobs", "ModelVersions", "TrainingJobs"]

DEFAULT_MODEL_TYPE = "simplified_dgsr"


def _version_body(
    version_tag: str,
    model_type: str,
    metrics: Optional[Mapping[str, Any]],
    artifact_uri: Optional[str],
) -> Dict[str, Any]:
    if not version_tag or len(version_tag) > 64:
        raise InputValidationError("version_tag must be 1-64 characters")
    if not model_type or len(model_type) > 64:
        raise InputValidationError("model_type must be 1-64 characters")
    body: Dict[str, Any] = {"version_tag": version_tag, "model_type": model_type}
    if metrics:
        body["metrics"] = dict(metrics)
    if artifact_uri is not None:
        body["artifact_uri"] = artifact_uri
    return body


def _job_body(
    model_type: str,
    dataset_snapshot_id: Optional[Union[str, UUID]],
    configuration: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    if not model_type or len(model_type) > 64:
        raise InputValidationError("model_type must be 1-64 characters")
    body: Dict[str, Any] = {"model_type": model_type}
    if dataset_snapshot_id is not None:
        body["dataset_snapshot_id"] = str(dataset_snapshot_id)
    if configuration:
        body["configuration"] = dict(configuration)
    return body


def _find(jobs: TrainingJobList, job_id: Union[str, UUID]) -> Optional[TrainingJob]:
    wanted = str(job_id)
    return next((job for job in jobs if str(job.id) == wanted), None)


class ModelVersions(SyncResource):
    """Model registry. Scopes: ``models:read`` / ``models:write`` / ``models:deploy``."""

    def create(
        self,
        *,
        version_tag: str,
        model_type: str = DEFAULT_MODEL_TYPE,
        metrics: Optional[Mapping[str, Any]] = None,
        artifact_uri: Optional[str] = None,
    ) -> ModelVersion:
        """Register an externally trained version (``POST /v1/model-versions``).

        Raises :class:`~graphrec_sdk.DuplicateResourceError` if the tag exists.
        """

        return cast(
            ModelVersion,
            self._client.request(
                "model_versions.create",
                json=_version_body(version_tag, model_type, metrics, artifact_uri),
                cast_to=ModelVersion,
            ),
        )

    def list(self) -> ModelVersionList:
        """``GET /v1/model-versions``, newest first. ``.active`` gives the serving version."""

        return cast(
            ModelVersionList, self._client.request("model_versions.list", cast_to=ModelVersionList)
        )

    def get(self, version_id: Union[str, UUID]) -> ModelVersion:
        """``GET /v1/model-versions/{version_id}``."""

        return cast(
            ModelVersion,
            self._client.request(
                "model_versions.get", path_params={"version_id": version_id}, cast_to=ModelVersion
            ),
        )

    def get_active(self) -> Optional[ModelVersion]:
        """The version currently serving recommendations, or ``None``."""

        return self.list().active

    def activate(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Serve this version; the previous active one becomes ``retired``.

        ``POST /v1/model-versions/{version_id}:activate``.
        """

        return cast(
            ModelVersion,
            self._client.request(
                "model_versions.activate",
                path_params={"version_id": version_id},
                cast_to=ModelVersion,
            ),
        )

    def archive(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Archive an inactive version and free its vector index.

        ``POST /v1/model-versions/{version_id}:archive``. Archiving the active
        version raises :class:`~graphrec_sdk.StateConflictError`.
        """

        return cast(
            ModelVersion,
            self._client.request(
                "model_versions.archive",
                path_params={"version_id": version_id},
                cast_to=ModelVersion,
            ),
        )

    def rollback(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Re-activate a previously served version (``POST /v1/models/{id}:rollback``)."""

        return cast(
            ModelVersion,
            self._client.request(
                "model_versions.rollback",
                path_params={"model_id": version_id},
                cast_to=ModelVersion,
            ),
        )


class AsyncModelVersions(AsyncResource):
    async def create(
        self,
        *,
        version_tag: str,
        model_type: str = DEFAULT_MODEL_TYPE,
        metrics: Optional[Mapping[str, Any]] = None,
        artifact_uri: Optional[str] = None,
    ) -> ModelVersion:
        """Async variant of :meth:`ModelVersions.create`."""

        return cast(
            ModelVersion,
            await self._client.request(
                "model_versions.create",
                json=_version_body(version_tag, model_type, metrics, artifact_uri),
                cast_to=ModelVersion,
            ),
        )

    async def list(self) -> ModelVersionList:
        """Async variant of :meth:`ModelVersions.list`."""

        return cast(
            ModelVersionList,
            await self._client.request("model_versions.list", cast_to=ModelVersionList),
        )

    async def get(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Async variant of :meth:`ModelVersions.get`."""

        return cast(
            ModelVersion,
            await self._client.request(
                "model_versions.get", path_params={"version_id": version_id}, cast_to=ModelVersion
            ),
        )

    async def get_active(self) -> Optional[ModelVersion]:
        """Async variant of :meth:`ModelVersions.get_active`."""

        return (await self.list()).active

    async def activate(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Async variant of :meth:`ModelVersions.activate`."""

        return cast(
            ModelVersion,
            await self._client.request(
                "model_versions.activate",
                path_params={"version_id": version_id},
                cast_to=ModelVersion,
            ),
        )

    async def archive(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Async variant of :meth:`ModelVersions.archive`."""

        return cast(
            ModelVersion,
            await self._client.request(
                "model_versions.archive",
                path_params={"version_id": version_id},
                cast_to=ModelVersion,
            ),
        )

    async def rollback(self, version_id: Union[str, UUID]) -> ModelVersion:
        """Async variant of :meth:`ModelVersions.rollback`."""

        return cast(
            ModelVersion,
            await self._client.request(
                "model_versions.rollback",
                path_params={"model_id": version_id},
                cast_to=ModelVersion,
            ),
        )


class TrainingJobs(SyncResource):
    """DGSR training requests. Scopes: ``training:write`` / ``training:read``."""

    def create(
        self,
        *,
        model_type: str = DEFAULT_MODEL_TYPE,
        dataset_snapshot_id: Optional[Union[str, UUID]] = None,
        configuration: Optional[Mapping[str, Any]] = None,
    ) -> TrainingJob:
        """Request training (``POST /v1/training-jobs``).

        Not retried after ambiguous failures (a retry could start a second job).
        The produced version is ``job.model_version_id``; activate it with
        ``client.model_versions.activate(...)`` after reviewing its metrics.
        """

        return cast(
            TrainingJob,
            self._client.request(
                "training_jobs.create",
                json=_job_body(model_type, dataset_snapshot_id, configuration),
                cast_to=TrainingJob,
            ),
        )

    def list(self) -> TrainingJobList:
        """``GET /v1/training-jobs``, newest first."""

        return cast(
            TrainingJobList, self._client.request("training_jobs.list", cast_to=TrainingJobList)
        )

    def find(self, job_id: Union[str, UUID]) -> Optional[TrainingJob]:
        """Look a job up by ID (the API has no single-job endpoint, so this lists jobs)."""

        return _find(self.list(), job_id)

    def wait(
        self,
        job_id: Union[str, UUID],
        *,
        timeout: float = 900.0,
        poll_interval: float = 5.0,
    ) -> TrainingJob:
        """Poll until the job reaches ``succeeded``, ``failed`` or ``cancelled``.

        Raises :class:`~graphrec_sdk.WaitTimeoutError` after ``timeout`` seconds.
        """

        deadline = time.monotonic() + timeout
        while True:
            job = self.find(job_id)
            if job is not None and job.is_terminal:
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state = job.status if job is not None else "not found"
                raise WaitTimeoutError(f"Training job {job_id} still {state} after {timeout:.0f}s")
            time.sleep(min(poll_interval, remaining))


class AsyncTrainingJobs(AsyncResource):
    async def create(
        self,
        *,
        model_type: str = DEFAULT_MODEL_TYPE,
        dataset_snapshot_id: Optional[Union[str, UUID]] = None,
        configuration: Optional[Mapping[str, Any]] = None,
    ) -> TrainingJob:
        """Async variant of :meth:`TrainingJobs.create`."""

        return cast(
            TrainingJob,
            await self._client.request(
                "training_jobs.create",
                json=_job_body(model_type, dataset_snapshot_id, configuration),
                cast_to=TrainingJob,
            ),
        )

    async def list(self) -> TrainingJobList:
        """Async variant of :meth:`TrainingJobs.list`."""

        return cast(
            TrainingJobList,
            await self._client.request("training_jobs.list", cast_to=TrainingJobList),
        )

    async def find(self, job_id: Union[str, UUID]) -> Optional[TrainingJob]:
        """Async variant of :meth:`TrainingJobs.find`."""

        return _find(await self.list(), job_id)

    async def wait(
        self,
        job_id: Union[str, UUID],
        *,
        timeout: float = 900.0,
        poll_interval: float = 5.0,
    ) -> TrainingJob:
        """Async variant of :meth:`TrainingJobs.wait`."""

        deadline = time.monotonic() + timeout
        while True:
            job = await self.find(job_id)
            if job is not None and job.is_terminal:
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state = job.status if job is not None else "not found"
                raise WaitTimeoutError(f"Training job {job_id} still {state} after {timeout:.0f}s")
            await asyncio.sleep(min(poll_interval, remaining))
