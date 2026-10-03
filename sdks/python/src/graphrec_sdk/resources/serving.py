from __future__ import annotations

from typing import Any, Dict, Optional, cast

from ..errors import InputValidationError
from ..models.serving import DeploymentStatus, MetricsSummary, ScalingStatus
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncDeployment", "AsyncMetrics", "Deployment", "Metrics"]


def _window(window_minutes: Optional[int]) -> Optional[Dict[str, Any]]:
    return None if window_minutes is None else {"window_minutes": window_minutes}


def _scaling_query(limit: int) -> Dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise InputValidationError("limit must be an integer between 1 and 100")
    return {"limit": limit}


class Deployment(SyncResource):
    """Recommendation-serving status. Scope: ``deployments:read``."""

    def get(self) -> DeploymentStatus:
        """``GET /v1/deployment``."""

        return cast(
            DeploymentStatus, self._client.request("deployment.get", cast_to=DeploymentStatus)
        )

    def scaling(self, *, limit: int = 20) -> ScalingStatus:
        """Capacity policy, live demand and the ``limit`` most recent scaling events.

        ``GET /v1/deployment/scaling`` - scope ``deployments:read``.
        """

        return cast(
            ScalingStatus,
            self._client.request(
                "deployment.scaling", query=_scaling_query(limit), cast_to=ScalingStatus
            ),
        )


class AsyncDeployment(AsyncResource):
    async def get(self) -> DeploymentStatus:
        """Async variant of :meth:`Deployment.get`."""

        return cast(
            DeploymentStatus, await self._client.request("deployment.get", cast_to=DeploymentStatus)
        )

    async def scaling(self, *, limit: int = 20) -> ScalingStatus:
        """Async variant of :meth:`Deployment.scaling`."""

        return cast(
            ScalingStatus,
            await self._client.request(
                "deployment.scaling", query=_scaling_query(limit), cast_to=ScalingStatus
            ),
        )


class Metrics(SyncResource):
    """Measured serving metrics. Scope: ``metrics:read``."""

    def summary(self, *, window_minutes: Optional[int] = None) -> MetricsSummary:
        """Request rate, error and fallback rates, p95 latency and offline quality.

        Measured over the last ``window_minutes`` (the API defaults to 60).
        ``GET /v1/metrics/summary``.
        """

        return cast(
            MetricsSummary,
            self._client.request(
                "metrics.summary", query=_window(window_minutes), cast_to=MetricsSummary
            ),
        )


class AsyncMetrics(AsyncResource):
    async def summary(self, *, window_minutes: Optional[int] = None) -> MetricsSummary:
        """Async variant of :meth:`Metrics.summary`."""

        return cast(
            MetricsSummary,
            await self._client.request(
                "metrics.summary", query=_window(window_minutes), cast_to=MetricsSummary
            ),
        )
