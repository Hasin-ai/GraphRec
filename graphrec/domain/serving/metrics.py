"""What `/service-status` reports, computed from rows rather than scraped.

BACKEND_PLAN L1200 sources these numbers from Prometheus and caches them for
about fifteen seconds. This build computes them from `recommendation_requests`
instead, and the reason is the sentence immediately after: *"If Prometheus is
unreachable, return `measurement_status: 'unavailable'` rather than zeros."* The
rows are already written — the request table exists for metering and for
`/feedback/*` to reference — so a scrape would add a second source that can be
unreachable, for numbers the first source already has. When Prometheus arrives
it can replace this implementation behind the same shape; `measurement_status`
is on the wire from the start precisely so that replacement is not a contract
change.

**A window with no traffic is `measurement delayed`, never zero.** A tenant who
sent no requests yesterday has an availability nobody measured, and `99.94%` and
`0%` are both inventions. This is the same discipline `graphrec.domain.metering`
follows for usage, and it is the reason `availability`, `latency_p95_ms` and
`fallback_rate` are all nullable here.

**The errors panel reads two columns and no others.** dc.html L1842: *"Error
classes only. Request payloads and recommendation results are never rendered
here."* `error_class` is a closed enum and `error_reason` is written from
`graphrec.common.error_copy` at insert time, so there is no path by which a
caller's string reaches this endpoint — the redaction is structural, not a
filter someone has to remember to apply.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import MEASUREMENT_STATUS_LABELS, MeasurementStatus
from graphrec.db.models import RecommendationRequest
from graphrec.serving.states import RequestStatus, ServingErrorClass

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The console's default range (dc.html L1830 offers 24 hours, 7 days, 30 days).
DEFAULT_WINDOW = dt.timedelta(hours=24)

#: How many redacted error rows the panel draws. dc.html shows three; twenty
#: gives a reader enough to see a pattern without paginating a panel that has no
#: pagination control.
ERROR_LIMIT = 20


@dataclass(frozen=True, slots=True)
class ServingMetrics:
    """`GET /v1/metrics/summary`, and six of the stats on `/service-status`.

    Every measurement is nullable and `measurement_status` explains the nulls.
    A caller that wants a number for a chart should read `status` first; a
    caller that treats `None` as `0` has reintroduced the defect the plan names
    at L1200.
    """

    window: dt.timedelta
    requests: int
    errors: int
    availability: float | None
    latency_p95_ms: int | None
    fallback_rate: float | None
    status: MeasurementStatus
    freshness_seconds: int | None

    @property
    def status_label(self) -> str:
        """The console's own words for the status (`MEASUREMENT_STATUS_LABELS`)."""
        return MEASUREMENT_STATUS_LABELS[self.status]

    @property
    def window_hours(self) -> int:
        return int(self.window.total_seconds() // 3600)


@dataclass(frozen=True, slots=True)
class ServingError:
    """One row of the redacted panel (dc.html L1841-1843).

    `reference` is a short handle a tenant can quote in a support request. It is
    derived from the request id rather than being a second identifier, and it is
    truncated so that quoting it in a ticket does not hand over a key that
    addresses the row.
    """

    occurred_at: dt.datetime
    error_class: ServingErrorClass
    reason: str
    reference: str


class MetricsService:
    """Two reads, both tenant-scoped by RLS."""

    async def summary(
        self,
        session: AsyncSession,
        *,
        window: dt.timedelta = DEFAULT_WINDOW,
        now: dt.datetime | None = None,
    ) -> ServingMetrics:
        """Availability, latency and fallback rate over one window.

        One query, four aggregates. Four queries would be four instants, and a
        board that reported 1,000 requests and a fallback rate computed against
        1,003 would be wrong in a way nobody could see.
        """
        moment = now or dt.datetime.now(dt.UTC)
        since = moment - window

        refused = RequestStatus.REFUSED.value
        row = (
            await session.execute(
                sa.select(
                    sa.func.count().label("requests"),
                    sa.func.count()
                    .filter(RecommendationRequest.status != RequestStatus.SERVED.value)
                    .label("errors"),
                    sa.func.count()
                    .filter(RecommendationRequest.status == refused)
                    .label("refused"),
                    sa.func.count()
                    .filter(RecommendationRequest.fallback_applied.is_(True))
                    .label("fallbacks"),
                    # `percentile_cont` over the whole window rather than a
                    # bucketed approximation: the volumes here are one tenant's
                    # and an exact percentile costs a sort nobody will notice.
                    sa.func.percentile_cont(0.95)
                    .within_group(RecommendationRequest.latency_ms.asc())
                    .label("p95"),
                    sa.func.max(RecommendationRequest.requested_at).label("latest"),
                ).where(RecommendationRequest.requested_at >= since)
            )
        ).one()

        requests = int(row.requests)
        if requests == 0:
            # Not an outage and not perfect uptime — an unmeasured window.
            return ServingMetrics(
                window=window,
                requests=0,
                errors=0,
                availability=None,
                latency_p95_ms=None,
                fallback_rate=None,
                status=MeasurementStatus.DELAYED,
                freshness_seconds=None,
            )

        latency = row.p95
        return ServingMetrics(
            window=window,
            requests=requests,
            errors=int(row.errors),
            # A degraded request was answered, so it counts as available. Only a
            # refusal is unavailability — which is also why `fallback_rate` is
            # reported beside it rather than folded in: they are different
            # failures and the console draws them as different stats (L1831,
            # L1837).
            availability=(requests - int(row.refused)) / requests,
            latency_p95_ms=int(latency) if latency is not None else None,
            fallback_rate=int(row.fallbacks) / requests,
            status=MeasurementStatus.MEASURED,
            freshness_seconds=_freshness(row.latest, moment),
        )

    async def errors(
        self, session: AsyncSession, *, limit: int = ERROR_LIMIT
    ) -> list[ServingError]:
        """The most recent refusals and degradations, newest first."""
        rows = (
            await session.execute(
                sa.select(
                    RecommendationRequest.request_id,
                    RecommendationRequest.requested_at,
                    RecommendationRequest.error_class,
                    RecommendationRequest.error_reason,
                )
                .where(RecommendationRequest.error_class.is_not(None))
                .order_by(RecommendationRequest.requested_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            ServingError(
                occurred_at=row.requested_at,
                error_class=ServingErrorClass(row.error_class),
                reason=row.error_reason or "",
                reference=reference_for(row.request_id),
            )
            for row in rows
        ]


def reference_for(request_id: uuid.UUID) -> str:
    """`err-3f81` — the console's format, from the request's own id.

    Four hex characters is not unique and is not meant to be. It is a handle for
    a conversation ("the err-3f81 one"), and the id it came from is what an
    operator looks the row up by.
    """
    return f"err-{request_id.hex[:4]}"


def _freshness(latest: dt.datetime | None, now: dt.datetime) -> int | None:
    """Seconds since the newest row the numbers were computed from.

    dc.html L1839 draws this as "12 s ago". It is the age of the *data*, not the
    age of the query: a board refreshed every second over an hour-old row is
    stale, and saying "1 s ago" would hide exactly that.
    """
    if latest is None:
        return None
    if latest.tzinfo is None:  # pragma: no cover - the column is timestamptz
        latest = latest.replace(tzinfo=dt.UTC)
    return max(0, int((now - latest).total_seconds()))


__all__ = [
    "DEFAULT_WINDOW",
    "ERROR_LIMIT",
    "MetricsService",
    "ServingError",
    "ServingMetrics",
    "reference_for",
]
