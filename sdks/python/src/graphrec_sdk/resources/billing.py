from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Union, cast

from ..enums import UsageType
from ..errors import InputValidationError
from ..models.billing import Subscription, UsageSummary, UsageTrend
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncSubscriptions", "AsyncUsage", "Subscriptions", "Usage"]


GRANULARITIES = ("hour", "day", "week")


def _utc(value: Optional[datetime], name: str) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise InputValidationError(f"{name} must be a datetime")
    # Naive datetimes are taken as UTC so the server never compares naive and aware values.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _trend_query(
    granularity: str,
    start: Optional[datetime],
    end: Optional[datetime],
    types: Optional[Iterable[Union[UsageType, str]]],
) -> Dict[str, Any]:
    granularity = str(getattr(granularity, "value", granularity))
    if granularity not in GRANULARITIES:
        raise InputValidationError(f"granularity must be one of {GRANULARITIES}")
    start, end = _utc(start, "start"), _utc(end, "end")
    if start is not None and end is not None and start >= end:
        raise InputValidationError("start must be before end")
    selected = None if types is None else ",".join(str(getattr(t, "value", t)) for t in types)
    return {
        "granularity": granularity,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "types": selected or None,
    }


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


def _period_query(period: Optional[str]) -> Optional[Dict[str, object]]:
    if period is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise InputValidationError("period must be YYYY-MM")
    return {"period": period}


class Usage(SyncResource):
    def get(self, period: Optional[str] = None) -> UsageSummary:
        """Usage per dimension with remaining allowance.

        ``GET /v1/usage`` - scope ``usage:read``. ``period="YYYY-MM"`` (UC-24) reads a
        past monthly period (up to 24 months back); inventory dimensions
        (``scope == "current"``) always reflect now.
        """

        return cast(UsageSummary, self._client.request("usage.get", query=_period_query(period), cast_to=UsageSummary))

    def trends(
        self,
        *,
        granularity: str = "day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        types: Optional[Iterable[Union[UsageType, str]]] = None,
    ) -> UsageTrend:
        """Usage per period and usage type, read from the usage ledger.

        ``GET /v1/usage/trends`` - scope ``usage:read``. ``granularity`` is
        ``hour``, ``day`` or ``week``; the window defaults to the 30 days before
        ``end`` (default now). ``types`` limits the result to some usage types.
        Naive datetimes are treated as UTC.
        """

        return cast(
            UsageTrend,
            self._client.request(
                "usage.trends",
                query=_trend_query(granularity, start, end, types),
                cast_to=UsageTrend,
            ),
        )


class AsyncUsage(AsyncResource):
    async def get(self, period: Optional[str] = None) -> UsageSummary:
        """Async variant of :meth:`Usage.get`."""

        return cast(UsageSummary, await self._client.request("usage.get", query=_period_query(period), cast_to=UsageSummary))

    async def trends(
        self,
        *,
        granularity: str = "day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        types: Optional[Iterable[Union[UsageType, str]]] = None,
    ) -> UsageTrend:
        """Async variant of :meth:`Usage.trends`."""

        return cast(
            UsageTrend,
            await self._client.request(
                "usage.trends",
                query=_trend_query(granularity, start, end, types),
                cast_to=UsageTrend,
            ),
        )
