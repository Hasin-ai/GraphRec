from __future__ import annotations

from typing import cast

from ..models.serving import AutoscalingStatus, DeploymentStatus, MetricsSummary, ReplicaStatus
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncDeployment", "AsyncMetrics", "Deployment", "Metrics"]


class Deployment(SyncResource):
    """Recommendation-serving status. Scope: ``deployments:read``."""

    def get(self) -> DeploymentStatus:
        """``GET /v1/deployment``."""

        return cast(
            DeploymentStatus, self._client.request("deployment.get", cast_to=DeploymentStatus)
        )

    def replicas(self) -> ReplicaStatus:
        """``GET /v1/deployment/replicas``."""

        return cast(
            ReplicaStatus, self._client.request("deployment.replicas", cast_to=ReplicaStatus)
        )

    def autoscaling(self) -> AutoscalingStatus:
        """``GET /v1/deployment/autoscaling``."""

        return cast(
            AutoscalingStatus,
            self._client.request("deployment.autoscaling", cast_to=AutoscalingStatus),
        )


class AsyncDeployment(AsyncResource):
    async def get(self) -> DeploymentStatus:
        """Async variant of :meth:`Deployment.get`."""

        return cast(
            DeploymentStatus, await self._client.request("deployment.get", cast_to=DeploymentStatus)
        )

    async def replicas(self) -> ReplicaStatus:
        """Async variant of :meth:`Deployment.replicas`."""

        return cast(
            ReplicaStatus, await self._client.request("deployment.replicas", cast_to=ReplicaStatus)
        )

    async def autoscaling(self) -> AutoscalingStatus:
        """Async variant of :meth:`Deployment.autoscaling`."""

        return cast(
            AutoscalingStatus,
            await self._client.request("deployment.autoscaling", cast_to=AutoscalingStatus),
        )


class Metrics(SyncResource):
    """Serving and model-quality metrics. Scope: ``metrics:read``."""

    def summary(self) -> MetricsSummary:
        """Request/error/fallback rates, p95 latency and offline quality.

        ``GET /v1/metrics/summary``.
        """

        return cast(MetricsSummary, self._client.request("metrics.summary", cast_to=MetricsSummary))


class AsyncMetrics(AsyncResource):
    async def summary(self) -> MetricsSummary:
        """Async variant of :meth:`Metrics.summary`."""

        return cast(
            MetricsSummary, await self._client.request("metrics.summary", cast_to=MetricsSummary)
        )
