from __future__ import annotations

from typing import cast

from ..models.billing import Subscription, UsageSummary
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncSubscriptions", "AsyncUsage", "Subscriptions", "Usage"]


class Subscriptions(SyncResource):
    def get(self) -> Subscription:
        """Current plan, period and effective limits.

        ``GET /v1/subscription`` - scope ``billing:read``.
        """

        return cast(Subscription, self._client.request("subscription.get", cast_to=Subscription))


class AsyncSubscriptions(AsyncResource):
    async def get(self) -> Subscription:
        """Async variant of :meth:`Subscriptions.get`."""

        return cast(
            Subscription, await self._client.request("subscription.get", cast_to=Subscription)
        )


class Usage(SyncResource):
    def get(self) -> UsageSummary:
        """Month-to-date usage per dimension with remaining allowance.

        ``GET /v1/usage`` - scope ``usage:read``.
        """

        return cast(UsageSummary, self._client.request("usage.get", cast_to=UsageSummary))


class AsyncUsage(AsyncResource):
    async def get(self) -> UsageSummary:
        """Async variant of :meth:`Usage.get`."""

        return cast(UsageSummary, await self._client.request("usage.get", cast_to=UsageSummary))
