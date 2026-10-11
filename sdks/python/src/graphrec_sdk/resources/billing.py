from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Union, cast
from uuid import UUID

from ..enums import UsageType
from ..errors import InputValidationError
from ..models.billing import PlanChangeRequest, PlanChangeRequestList, Subscription, UsageSummary, UsageTrend
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncSubscriptions", "AsyncUsage", "Subscriptions", "Usage"]


GRANULARITIES = ("hour", "day", "week")
Id = Union[str, UUID]


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


PLAN_CODES = ("free", "basic", "pro")


def _request_body(plan_code: str, message: Optional[str]) -> Dict[str, Any]:
    if plan_code not in PLAN_CODES:
        raise InputValidationError(f"plan_code must be one of {PLAN_CODES}")
    if message is not None and len(message) > 500:
        raise InputValidationError("message must be at most 500 characters")
    body: Dict[str, Any] = {"plan_code": plan_code}
    if message is not None and message.strip():
        body["message"] = message.strip()
    return body


class Subscriptions(SyncResource):
    def get(self) -> Subscription:
        """Current plan, period and effective limits.

        ``GET /v1/subscription`` - scope ``billing:read``.
        """

        return cast(Subscription, self._client.request("subscription.get", cast_to=Subscription))

    def list_requests(self) -> PlanChangeRequestList:
        """This workspace's plan change requests, newest first, and the open one.

        ``GET /v1/subscription/requests`` - scope ``billing:read``.
        """

        return cast(
            PlanChangeRequestList,
            self._client.request("subscription.list_requests", cast_to=PlanChangeRequestList),
        )

    def request_plan(self, plan_code: str, *, message: Optional[str] = None) -> PlanChangeRequest:
        """Ask a platform operator to move this workspace to ``plan_code``.

        ``free`` (Free demo), ``basic`` or ``pro``. GraphRec takes no payments: the plan
        changes when an operator approves. One request may be open at a time.
        ``POST /v1/subscription/requests`` - scope ``billing:write`` (administrators).
        """

        return cast(
            PlanChangeRequest,
            self._client.request(
                "subscription.request_plan", json=_request_body(plan_code, message), cast_to=PlanChangeRequest
            ),
        )

    def cancel_request(self, request_id: Id) -> PlanChangeRequest:
        """Withdraw a pending request. ``POST /v1/subscription/requests/{request_id}:cancel``."""

        return cast(
            PlanChangeRequest,
            self._client.request(
                "subscription.cancel_request", path_params={"request_id": request_id}, cast_to=PlanChangeRequest
            ),
        )


class AsyncSubscriptions(AsyncResource):
    async def get(self) -> Subscription:
        """Async variant of :meth:`Subscriptions.get`."""

        return cast(
            Subscription, await self._client.request("subscription.get", cast_to=Subscription)
        )

    async def list_requests(self) -> PlanChangeRequestList:
        """Async variant of :meth:`Subscriptions.list_requests`."""

        return cast(
            PlanChangeRequestList,
            await self._client.request("subscription.list_requests", cast_to=PlanChangeRequestList),
        )

    async def request_plan(self, plan_code: str, *, message: Optional[str] = None) -> PlanChangeRequest:
        """Async variant of :meth:`Subscriptions.request_plan`."""

        return cast(
            PlanChangeRequest,
            await self._client.request(
                "subscription.request_plan", json=_request_body(plan_code, message), cast_to=PlanChangeRequest
            ),
        )

    async def cancel_request(self, request_id: Id) -> PlanChangeRequest:
        """Async variant of :meth:`Subscriptions.cancel_request`."""

        return cast(
            PlanChangeRequest,
            await self._client.request(
                "subscription.cancel_request", path_params={"request_id": request_id}, cast_to=PlanChangeRequest
            ),
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
