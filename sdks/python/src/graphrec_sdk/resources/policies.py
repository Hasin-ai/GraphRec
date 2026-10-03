"""Tenant policies: recommendation re-ranking rules and automatic retraining."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union, cast

from pydantic import BaseModel, ValidationError

from ..errors import InputValidationError
from ..models.policies import (
    RecommendationPolicy,
    RecommendationPolicyUpdate,
    RetrainingPolicy,
    RetrainingPolicyUpdate,
)
from ._base import AsyncResource, SyncResource

__all__ = [
    "AsyncRecommendationPolicyResource",
    "AsyncRetrainingPolicyResource",
    "RecommendationPolicyResource",
    "RetrainingPolicyResource",
]

RecommendationPolicyLike = Union[RecommendationPolicyUpdate, RecommendationPolicy, Dict[str, Any]]
RetrainingPolicyLike = Union[RetrainingPolicyUpdate, RetrainingPolicy, Dict[str, Any]]


def _recommendation_body(
    policy: Optional[RecommendationPolicyLike], fields: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        model = _merge(RecommendationPolicyUpdate, policy, fields)
    except ValidationError as exc:
        raise InputValidationError(f"invalid recommendation policy: {exc}") from exc
    return cast(Dict[str, Any], model.model_dump(mode="json"))


def _retraining_body(
    policy: Optional[RetrainingPolicyLike], fields: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        model = _merge(RetrainingPolicyUpdate, policy, fields)
    except ValidationError as exc:
        raise InputValidationError(f"invalid retraining policy: {exc}") from exc
    return cast(Dict[str, Any], model.model_dump(mode="json"))


def _merge(model: Any, policy: Any, fields: Dict[str, Any]) -> Any:
    base: Dict[str, Any] = {}
    if isinstance(policy, BaseModel):
        # An update model, or the resource returned by ``get()``: keep the editable fields.
        base = {k: v for k, v in policy.model_dump().items() if k in model.model_fields}
    elif policy is not None:
        base = dict(policy)
    base.update({key: value for key, value in fields.items() if value is not None})
    return model.model_validate(base)


class RecommendationPolicyResource(SyncResource):
    """Diversity and freshness re-ranking rules (``/v1/recommendation-policy``)."""

    def get(self) -> RecommendationPolicy:
        """The tenant's re-ranking rules.

        ``GET /v1/recommendation-policy`` - scope ``models:read``.
        """

        return cast(
            RecommendationPolicy,
            self._client.request("recommendation_policy.get", cast_to=RecommendationPolicy),
        )

    def update(
        self,
        policy: Optional[RecommendationPolicyLike] = None,
        *,
        diversity_enabled: Optional[bool] = None,
        max_per_category: Optional[int] = None,
        freshness_enabled: Optional[bool] = None,
        freshness_weight: Optional[float] = None,
        freshness_half_life_days: Optional[int] = None,
    ) -> RecommendationPolicy:
        """Replace the re-ranking rules.

        ``PUT /v1/recommendation-policy`` - scope ``models:deploy``.

        This is a full replacement: fields you leave out take the server defaults,
        not their current values. Start from :meth:`get` to change one field::

            current = client.tenant.recommendation_policy.get()
            client.tenant.recommendation_policy.update(current, max_per_category=2)
        """

        body = _recommendation_body(
            policy,
            dict(
                diversity_enabled=diversity_enabled,
                max_per_category=max_per_category,
                freshness_enabled=freshness_enabled,
                freshness_weight=freshness_weight,
                freshness_half_life_days=freshness_half_life_days,
            ),
        )
        return cast(
            RecommendationPolicy,
            self._client.request(
                "recommendation_policy.update", json=body, cast_to=RecommendationPolicy
            ),
        )


class AsyncRecommendationPolicyResource(AsyncResource):
    async def get(self) -> RecommendationPolicy:
        """Async variant of :meth:`RecommendationPolicyResource.get`."""

        return cast(
            RecommendationPolicy,
            await self._client.request("recommendation_policy.get", cast_to=RecommendationPolicy),
        )

    async def update(
        self,
        policy: Optional[RecommendationPolicyLike] = None,
        *,
        diversity_enabled: Optional[bool] = None,
        max_per_category: Optional[int] = None,
        freshness_enabled: Optional[bool] = None,
        freshness_weight: Optional[float] = None,
        freshness_half_life_days: Optional[int] = None,
    ) -> RecommendationPolicy:
        """Async variant of :meth:`RecommendationPolicyResource.update`."""

        body = _recommendation_body(
            policy,
            dict(
                diversity_enabled=diversity_enabled,
                max_per_category=max_per_category,
                freshness_enabled=freshness_enabled,
                freshness_weight=freshness_weight,
                freshness_half_life_days=freshness_half_life_days,
            ),
        )
        return cast(
            RecommendationPolicy,
            await self._client.request(
                "recommendation_policy.update", json=body, cast_to=RecommendationPolicy
            ),
        )


class RetrainingPolicyResource(SyncResource):
    """Scheduled and event-triggered retraining (``/v1/retraining-policy``)."""

    def get(self) -> RetrainingPolicy:
        """Policy plus the evaluator's last outcome.

        ``GET /v1/retraining-policy`` - scope ``training:read``.
        """

        return cast(
            RetrainingPolicy,
            self._client.request("retraining_policy.get", cast_to=RetrainingPolicy),
        )

    def update(
        self,
        policy: Optional[RetrainingPolicyLike] = None,
        *,
        schedule_enabled: Optional[bool] = None,
        interval_minutes: Optional[int] = None,
        event_trigger_enabled: Optional[bool] = None,
        event_threshold: Optional[int] = None,
        epochs: Optional[int] = None,
    ) -> RetrainingPolicy:
        """Replace the retraining policy. ``PUT /v1/retraining-policy`` - scope ``training:write``.

        Full replacement: omitted fields take the server defaults, so pass the
        result of :meth:`get` as ``policy`` to change single fields. The server may
        refuse an interval below ``minimum_interval_minutes`` with a 422.
        """

        body = _retraining_body(
            policy,
            dict(
                schedule_enabled=schedule_enabled,
                interval_minutes=interval_minutes,
                event_trigger_enabled=event_trigger_enabled,
                event_threshold=event_threshold,
                epochs=epochs,
            ),
        )
        return cast(
            RetrainingPolicy,
            self._client.request("retraining_policy.update", json=body, cast_to=RetrainingPolicy),
        )


class AsyncRetrainingPolicyResource(AsyncResource):
    async def get(self) -> RetrainingPolicy:
        """Async variant of :meth:`RetrainingPolicyResource.get`."""

        return cast(
            RetrainingPolicy,
            await self._client.request("retraining_policy.get", cast_to=RetrainingPolicy),
        )

    async def update(
        self,
        policy: Optional[RetrainingPolicyLike] = None,
        *,
        schedule_enabled: Optional[bool] = None,
        interval_minutes: Optional[int] = None,
        event_trigger_enabled: Optional[bool] = None,
        event_threshold: Optional[int] = None,
        epochs: Optional[int] = None,
    ) -> RetrainingPolicy:
        """Async variant of :meth:`RetrainingPolicyResource.update`."""

        body = _retraining_body(
            policy,
            dict(
                schedule_enabled=schedule_enabled,
                interval_minutes=interval_minutes,
                event_trigger_enabled=event_trigger_enabled,
                event_threshold=event_threshold,
                epochs=epochs,
            ),
        )
        return cast(
            RetrainingPolicy,
            await self._client.request(
                "retraining_policy.update", json=body, cast_to=RetrainingPolicy
            ),
        )
