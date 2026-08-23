"""Answering a recommendation request: which lane, in what order, and why.

The funnel is in `funnel`; this module decides what goes into it. Four lanes
feed it, and which lanes run is the `strategy` the response reports — ER-F-05
makes that mandatory, and the reason is here: a tenant whose click-through fell
last Tuesday needs to know whether they were served by the model or by
popularity, and no amount of latency data answers that.

**The strategy is a consequence, not a parameter.** A caller cannot ask for
`personalized`; they supply a customer or a session, and what the system knows
about them decides. That keeps the field honest — it describes what happened
rather than what was requested.

**`fallback` means degradation; `cold_start` does not.** Both answer from
popularity. The difference is that `cold_start` is the correct answer to a
request about someone the system has never seen, and `fallback` is a model that
should have answered and could not (ER-F-10). Collapsing them would make the
fallback rate on `/service-status` (dc.html L1837) unreadable — it would rise
every time a tenant acquired new customers.

**The query vector is the mean of the recent items' embeddings.** The bundle
ships item embeddings and not the DGSR encoder (Phase 10), so the serving-time
user state is an aggregate of what the caller just looked at rather than a
forward pass over the interaction graph. That is a real approximation and it is
recorded as one in the Phase 11 report; it is also the reason `recent_events`
is applied "without retraining" as the plan requires — the last fifty events
change the query directly.

**Nothing here can reach another tenant's data.** Every query runs on the
tenant's own session under RLS, and the candidate index is keyed by
`(tenant, version)` so a search cannot even name another tenant's matrix. The
cross-tenant test asserts the outcome; the design is what makes it true.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from graphrec.common.enums import ModelVersionStatus, UsageType
from graphrec.common.error_copy import ERROR_COPY
from graphrec.common.errors import UnavailableError, ValidationError
from graphrec.db.models import (
    Customer,
    InteractionEvent,
    ModelVersion,
    Product,
    RecommendationRequest,
    RecommendationResult,
)
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering import ledger, quota
from graphrec.domain.metering.periods import current_period
from graphrec.domain.serving import funnel
from graphrec.ml.index import IndexNotLoadedError
from graphrec.serving.states import (
    CandidateSource,
    RequestStatus,
    ServingErrorClass,
    Strategy,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.domain.metering.counters import UsageCounters
    from graphrec.ml.index import CandidateIndex, IndexKey

logger = logging.getLogger(__name__)

#: How many of a customer's stored events form the query. The plan bounds
#: caller-supplied `recent_events` at 50; the stored history is bounded to the
#: same number so a customer with ten years of purchases does not produce a
#: query vector that is the catalogue average.
HISTORY_WINDOW = 50

#: How far back popularity looks. Thirty days rather than all time: a "top
#: seller" computed over the whole history of a catalogue is a list of things
#: that sold well in 2023, which is a worse cold-start answer than a list of
#: things selling now.
POPULARITY_WINDOW_DAYS = 30

#: How many candidates each lane retrieves before the funnel filters. Larger
#: than any `top_n` the API accepts, because exclusions and eligibility both
#: remove items after retrieval and a lane that returned exactly `top_n` would
#: return short lists to precisely the callers who filtered most.
LANE_DEPTH = 200


@dataclass(frozen=True, slots=True)
class RecentEvent:
    """One event the caller supplied inline, applied without retraining."""

    external_product_id: str
    event_type: str | None = None
    occurred_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class RecommendationInput:
    """A validated `POST /v1/recommendations` body.

    `session_id` is taken and immediately hashed — see `session_hash`. It is
    never stored and never logged, because it is the tenant's customer's
    tracking key and this system has no use for it beyond telling two sessions
    apart.
    """

    external_request_id: str
    top_n: int
    external_customer_id: str | None = None
    session_id: str | None = None
    recent_events: tuple[RecentEvent, ...] = ()
    exclude_product_ids: tuple[str, ...] = ()
    allow_fallback: bool = True
    context: dict[str, Any] = field(default_factory=dict)

    def session_hash(self) -> str | None:
        """SHA-256 of the session identifier, or `None`.

        Unsalted on purpose: the value is compared for equality within one
        tenant and never reversed, and a per-tenant salt would make the column
        useless for the one query it exists to support — "was this the same
        session?" — without making a low-entropy identifier meaningfully harder
        to guess for anyone who already has the tenant's event stream.
        """
        if self.session_id is None:
            return None
        return hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()

    def identity_hash(self) -> str | None:
        """What goes in `session_hash` when there is no customer row to point at.

        `ck_recommendation_requests_identified` requires every request to be
        attributable to *somebody*, and the most common cold-start request is a
        customer identifier the platform has never seen — a first-time visitor
        the tenant already has an id for. Resolving that to `NULL` and stopping
        would mean the one case ER-F-05's `cold_start` strategy exists for could
        not be recorded at all.

        So the identifier is hashed, exactly as a session id is and for exactly
        the same reasons: unsalted, compared only for equality within one
        tenant, and never reversed. The column then means "the identity this
        request came from, when it is not a row" — which is what makes two
        requests from the same unresolved customer comparable.
        """
        if self.session_id is not None:
            return self.session_hash()
        if self.external_customer_id is None:
            return None
        return hashlib.sha256(self.external_customer_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RecommendedItem:
    """One item on the wire."""

    external_product_id: str
    rank: int
    score: float
    candidate_source: CandidateSource


@dataclass(frozen=True, slots=True)
class Recommendation:
    """The whole response, before it is a Pydantic model.

    `model_version_id` and `model_version_number` are `None` only on a
    `fallback` answer, which is the one case in which no model produced
    anything. ER-F-05 still requires the field to be present — as `null`, which
    is a statement, rather than absent, which is an omission.
    """

    external_request_id: str
    strategy: Strategy
    fallback_applied: bool
    items: tuple[RecommendedItem, ...]
    model_version_id: uuid.UUID | None
    model_version_number: int | None
    ordering_policy_version: int
    latency_ms: int
    request_id: uuid.UUID


class RecommendationService:
    """The data plane's one read path.

    Holds the candidate index because that is the only expensive thing it needs
    and because an inference process has exactly one. The session is passed per
    call, as everywhere else.
    """

    def __init__(
        self, *, index: CandidateIndex | None = None, pinned_version_id: uuid.UUID | None = None
    ) -> None:
        self._index = index
        #: Set in an inference process, which serves exactly one version and
        #: knows which. `None` anywhere else, where "the active one" is the only
        #: answer available.
        self._pinned = pinned_version_id

    async def recommend(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        request: RecommendationInput,
        counters: UsageCounters | None = None,
        now: dt.datetime | None = None,
    ) -> Recommendation:
        """Choose a lane, run the funnel, record what was returned.

        The quota check runs *first*, before any lane is built. dc.html L1170's
        promise is about ordering — a refused call must not have done the work —
        and a `429` returned after a vector search is a `429` the tenant paid
        for in latency.
        """
        started = dt.datetime.now(dt.UTC)
        moment = now or started
        if request.external_customer_id is None and request.session_id is None:
            # The plan's `400`. A request identifying nobody is not a cold-start
            # request; it is a request the caller cannot attribute feedback to.
            raise ValidationError("event_identifiers_required")

        if counters is not None:
            await quota.assert_within(
                session,
                counters,
                tenant_id=tenant_id,
                usage_type=UsageType.RECOMMENDATIONS,
                requested=1,
                now=moment,
            )

        version = await self._active_version(session)
        customer = await self._customer(session, external_id=request.external_customer_id)
        history = await self._history(session, customer=customer)
        recent = tuple(event.external_product_id for event in request.recent_events)
        # Caller-supplied events lead: they are what the customer is doing right
        # now, and the stored history is what they did before.
        query_refs = _dedupe(recent + history)

        plan = _choose(
            version=version,
            index=self._index,
            has_history=bool(query_refs),
            from_customer=bool(history),
            allow_fallback=request.allow_fallback,
        )

        lanes, policy = await self._lanes(
            session,
            tenant_id=tenant_id,
            strategy=plan,
            version=version,
            query_refs=query_refs,
            now=moment,
        )
        eligible = await self._eligible_refs(session)
        # The caller's own exclusions plus everything already in the query. An
        # item the customer just viewed is the single most likely thing the
        # graph lane returns and the single least useful thing to show back.
        exclude = frozenset(request.exclude_product_ids) | frozenset(recent)
        items = funnel.run(
            lanes,
            top_n=request.top_n,
            policy=policy,
            eligible=eligible,
            exclude=exclude,
        )

        latency_ms = max(0, int((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000))
        recorded = await self._record(
            session,
            tenant_id=tenant_id,
            request=request,
            customer=customer,
            version=version if plan is not Strategy.FALLBACK else None,
            strategy=plan,
            items=items,
            latency_ms=latency_ms,
            now=moment,
        )
        if counters is not None:
            await self._meter(
                session,
                counters,
                tenant_id=tenant_id,
                external_request_id=request.external_request_id,
                now=moment,
            )
        return Recommendation(
            external_request_id=request.external_request_id,
            strategy=plan,
            fallback_applied=plan is Strategy.FALLBACK,
            items=tuple(
                RecommendedItem(
                    external_product_id=item.item_ref,
                    rank=rank,
                    score=round(item.final_score, 6),
                    candidate_source=item.source,
                )
                for rank, item in enumerate(items, start=1)
            ),
            model_version_id=(
                version.model_version_id if version and plan is not Strategy.FALLBACK else None
            ),
            model_version_number=(
                version.version_number if version and plan is not Strategy.FALLBACK else None
            ),
            ordering_policy_version=policy.version,
            latency_ms=latency_ms,
            request_id=recorded,
        )

    async def record_refusal(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        request: RecommendationInput,
        error_class: ServingErrorClass,
        reason_key: str,
    ) -> uuid.UUID | None:
        """Record a request that was refused rather than answered.

        Called on its **own** session, after the failing transaction has rolled
        back. That is the whole reason it is a separate method: a refusal
        written inside the transaction that raised would be rolled back with it,
        and `/service-status` would report a serving path that never failed.

        Returns `None` when even this write fails. A metrics row is not worth
        turning a `503` into a `500`.
        """
        try:
            customer = await self._customer(session, external_id=request.external_customer_id)
            row = RecommendationRequest(
                tenant_id=tenant_id,
                external_request_id=request.external_request_id,
                # Resolved again on this session, because the one that knew it
                # is gone. An unknown customer with no session leaves the row
                # unidentified, the `CHECK` refuses it, and the `except` below
                # turns that into a log line rather than a second failure.
                customer_id=customer.customer_id if customer else None,
                session_hash=(
                    request.session_hash() or (None if customer else request.identity_hash())
                ),
                model_version_id=None,
                # A refusal produced nothing, and `cold_start` would claim it
                # answered from popularity. `fallback` is the honest label for
                # "the model should have answered and did not" (ER-F-10) even
                # when the caller declined the fallback itself.
                strategy=Strategy.FALLBACK.value,
                fallback_applied=True,
                requested_count=request.top_n,
                returned_count=0,
                latency_ms=None,
                status=RequestStatus.REFUSED.value,
                error_class=error_class.value,
                error_reason=ERROR_COPY[reason_key],
            )
            session.add(row)
            await session.flush()
        except SQLAlchemyError:
            logger.warning("refusal_not_recorded", exc_info=True)
            return None
        return row.request_id

    @staticmethod
    async def _meter(
        session: AsyncSession,
        counters: UsageCounters,
        *,
        tenant_id: uuid.UUID,
        external_request_id: str,
        now: dt.datetime,
    ) -> None:
        """One recommendation, metered once.

        The caller's own `request_id` is the idempotency key (Ultimate §27), so
        a client retrying after a timeout is charged once. `ledger.grant`
        reports whether the row was new, and the cached counter moves only when
        it was — a counter incremented on a duplicate would drift above the
        ledger and refuse a tenant who is inside their limit.
        """
        written = await ledger.grant(
            session,
            tenant_id=tenant_id,
            usage_type=UsageType.RECOMMENDATIONS,
            quantity=1,
            idempotency_key=f"rec:{external_request_id}",
            occurred_at=now,
            source_ref=external_request_id,
        )
        if written:
            await counter_ops.note_granted(
                counters,
                tenant_id=tenant_id,
                usage_type=UsageType.RECOMMENDATIONS,
                period=current_period(now),
                quantity=1,
            )

    # ------------------------------------------------------------------ lanes

    async def _lanes(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        strategy: Strategy,
        version: ModelVersion | None,
        query_refs: Sequence[str],
        now: dt.datetime,
    ) -> tuple[list[list[funnel.ScoredItem]], funnel.OrderingPolicy]:
        """Which lanes run, in trust order.

        The list order is the merge's tie-break, so the most trusted lane is
        first. Popularity is always last and always present: it is what makes a
        response non-empty for a catalogue the model has never seen, and a lane
        that is sometimes absent is a lane whose absence is a bug nobody
        notices until a page is empty.
        """
        policy = funnel.OrderingPolicy.default()
        lanes: list[list[funnel.ScoredItem]] = []

        if strategy in {Strategy.PERSONALIZED, Strategy.SESSION} and version is not None:
            graph = self._graph_lane(
                key=(tenant_id, version.model_version_id),
                query_refs=query_refs,
                source=(
                    CandidateSource.GRAPH
                    if strategy is Strategy.PERSONALIZED
                    else CandidateSource.SESSION
                ),
            )
            if graph:
                lanes.append(graph)

        if query_refs:
            category = await self._category_lane(session, query_refs=query_refs, now=now)
            if category:
                lanes.append(category)

        lanes.append(await self._popularity_lane(session, now=now))
        return lanes, policy

    def _graph_lane(
        self, *, key: IndexKey, query_refs: Sequence[str], source: CandidateSource
    ) -> list[funnel.ScoredItem]:
        """The model's own answer, or nothing.

        `IndexNotLoadedError` is caught rather than raised: a missing index is
        the condition that produces a fallback, and `_choose` has already
        decided whether that is acceptable. Raising here would turn a
        degradation into a `500` between two lines that both know better.
        """
        if self._index is None:
            return []
        try:
            rows = self._index.vectors(key, query_refs)
            query = _mean_vector(rows)
            if query is None:
                return []
            candidates = self._index.search(key, query, top_k=LANE_DEPTH, exclude=query_refs)
        except IndexNotLoadedError:
            return []
        return [
            funnel.ScoredItem(item_ref=candidate.item_ref, score=candidate.score, source=source)
            for candidate in candidates
        ]

    async def _popularity_lane(
        self, session: AsyncSession, *, now: dt.datetime
    ) -> list[funnel.ScoredItem]:
        """The platform's popularity ranker, as a serving lane.

        The same idea CON-01 calls "a floor, not a peer" — here it is the floor
        under every response rather than the yardstick a version is measured
        against. Scores are normalised into `(0, 1]` so a merge with the graph
        lane does not have a popularity count of 4,000 outrank a dot product of
        0.9.
        """
        since = now - dt.timedelta(days=POPULARITY_WINDOW_DAYS)
        rows = (
            await session.execute(
                sa.select(
                    Product.external_product_id,
                    sa.func.count(InteractionEvent.event_id).label("events"),
                    Product.category_id,
                )
                .join(InteractionEvent, InteractionEvent.product_id == Product.product_id)
                .where(InteractionEvent.occurred_at >= since)
                .group_by(Product.external_product_id, Product.category_id)
                .order_by(sa.desc("events"), Product.external_product_id)
                .limit(LANE_DEPTH)
            )
        ).all()
        if not rows:
            return []
        top = float(rows[0][1]) or 1.0
        return [
            funnel.ScoredItem(
                item_ref=ref,
                score=float(count) / top,
                source=CandidateSource.POPULARITY,
                category=str(category_id) if category_id else None,
            )
            for ref, count, category_id in rows
        ]

    async def _category_lane(
        self, session: AsyncSession, *, query_refs: Sequence[str], now: dt.datetime
    ) -> list[funnel.ScoredItem]:
        """Products in the categories the caller has just been looking at.

        Scored below popularity by construction — the scores are in `(0, 0.5]` —
        because "same category" is a weaker signal than "everyone is buying
        this", and the merge keeps the higher score when both lanes return an
        item.
        """
        categories = (
            await session.scalars(
                sa.select(Product.category_id)
                .where(
                    Product.external_product_id.in_(list(query_refs)),
                    Product.category_id.is_not(None),
                )
                .distinct()
            )
        ).all()
        if not categories:
            return []
        since = now - dt.timedelta(days=POPULARITY_WINDOW_DAYS)
        rows = (
            await session.execute(
                sa.select(
                    Product.external_product_id,
                    sa.func.count(InteractionEvent.event_id).label("events"),
                    Product.category_id,
                )
                .outerjoin(
                    InteractionEvent,
                    sa.and_(
                        InteractionEvent.product_id == Product.product_id,
                        InteractionEvent.occurred_at >= since,
                    ),
                )
                .where(Product.category_id.in_(list(categories)))
                .group_by(Product.external_product_id, Product.category_id)
                .order_by(sa.desc("events"), Product.external_product_id)
                .limit(LANE_DEPTH)
            )
        ).all()
        top = max((float(row[1]) for row in rows), default=0.0) or 1.0
        return [
            funnel.ScoredItem(
                item_ref=ref,
                score=0.5 * float(count) / top,
                source=CandidateSource.CATEGORY,
                category=str(category_id) if category_id else None,
            )
            for ref, count, category_id in rows
        ]

    # ------------------------------------------------------------------ reads

    async def _active_version(self, session: AsyncSession) -> ModelVersion | None:
        """The version this process answers from.

        A pinned process answers from the version it loaded, not from whichever
        row currently says `active`. During an activation those are different by
        design: the new replica has v8 resident while v7 is still the active row
        (load-before-swap), and a process that consulted the row would find no
        index for v7 and serve fallback for the whole of the window ER-F-06
        exists to make invisible.
        """
        if self._pinned is not None:
            pinned: ModelVersion | None = await session.get(ModelVersion, self._pinned)
            return pinned
        found: ModelVersion | None = await session.scalar(
            sa.select(ModelVersion).where(ModelVersion.status == ModelVersionStatus.ACTIVE.value)
        )
        return found

    async def _customer(self, session: AsyncSession, *, external_id: str | None) -> Customer | None:
        if external_id is None:
            return None
        found: Customer | None = await session.scalar(
            sa.select(Customer).where(Customer.external_customer_id == external_id)
        )
        return found

    async def _history(
        self, session: AsyncSession, *, customer: Customer | None
    ) -> tuple[str, ...]:
        """The customer's most recent items, newest first."""
        if customer is None:
            return ()
        rows = (
            await session.scalars(
                sa.select(Product.external_product_id)
                .join(InteractionEvent, InteractionEvent.product_id == Product.product_id)
                .where(InteractionEvent.customer_id == customer.customer_id)
                .order_by(InteractionEvent.occurred_at.desc())
                .limit(HISTORY_WINDOW)
            )
        ).all()
        return tuple(rows)

    async def _eligible_refs(self, session: AsyncSession) -> frozenset[str]:
        """What the catalogue says may be recommended.

        Read as a set rather than joined into each lane: three lanes would
        otherwise carry the same predicate, and a lane that forgot it would
        return an out-of-stock product with no test failing.
        """
        rows = (
            await session.scalars(
                sa.select(Product.external_product_id).where(
                    Product.is_active.is_(True),
                    Product.deleted_at.is_(None),
                )
            )
        ).all()
        return frozenset(rows)

    # ----------------------------------------------------------------- writes

    async def _record(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        request: RecommendationInput,
        customer: Customer | None,
        version: ModelVersion | None,
        strategy: Strategy,
        items: Sequence[funnel.ScoredItem],
        latency_ms: int,
        now: dt.datetime,
    ) -> uuid.UUID:
        """Write the request and its results.

        A repeat of the same `request_id` is refused by
        `uq_recommendation_requests_ref`, which is what makes the metering
        counter idempotent. The caller sees the integrity error as a conflict;
        it does not see a second charge.
        """
        row = RecommendationRequest(
            tenant_id=tenant_id,
            external_request_id=request.external_request_id,
            customer_id=customer.customer_id if customer else None,
            # The session hash when there is one; otherwise the customer
            # identifier's, and only when no customer row resolved. An unknown
            # customer id must still satisfy
            # `ck_recommendation_requests_identified`, and a first-time visitor
            # is the whole of the cold-start case.
            session_hash=request.session_hash() or (None if customer else request.identity_hash()),
            model_version_id=version.model_version_id if version else None,
            strategy=strategy.value,
            fallback_applied=strategy is Strategy.FALLBACK,
            requested_count=request.top_n,
            returned_count=len(items),
            latency_ms=latency_ms,
            status=(
                RequestStatus.DEGRADED.value
                if strategy is Strategy.FALLBACK
                else RequestStatus.SERVED.value
            ),
            # A fallback answer is a degraded one, and `/service-status` says so
            # in the tenant's own copy. Written here rather than derived on read
            # so that the errors panel is a `SELECT` over rows and not a second
            # implementation of "what counts as an error".
            error_class=(
                ServingErrorClass.UNAVAILABLE.value if strategy is Strategy.FALLBACK else None
            ),
            error_reason=(ERROR_COPY["model_not_ready"] if strategy is Strategy.FALLBACK else None),
            requested_at=now,
        )
        session.add(row)
        await session.flush()

        if items:
            product_ids = await self._product_ids(session, refs=[item.item_ref for item in items])
            for rank, item in enumerate(items, start=1):
                product_id = product_ids.get(item.item_ref)
                if product_id is None:  # pragma: no cover - eligibility filtered these
                    continue
                session.add(
                    RecommendationResult(
                        tenant_id=tenant_id,
                        request_id=row.request_id,
                        rank_position=rank,
                        product_id=product_id,
                        # `None` on a lane that did not score with a model. Zero
                        # would be a score, and an average over it would be a
                        # lie about how the model performed.
                        model_score=(
                            _as_decimal(item.score)
                            if item.source is CandidateSource.GRAPH
                            else None
                        ),
                        final_score=_as_decimal(item.final_score),
                        candidate_source=item.source.value,
                    )
                )
            await session.flush()
        return row.request_id

    async def _product_ids(
        self, session: AsyncSession, *, refs: Sequence[str]
    ) -> dict[str, uuid.UUID]:
        rows = (
            await session.execute(
                sa.select(Product.external_product_id, Product.product_id).where(
                    Product.external_product_id.in_(list(refs))
                )
            )
        ).all()
        return dict(rows)  # type: ignore[arg-type]


# ------------------------------------------------------------------- helpers


def _choose(
    *,
    version: ModelVersion | None,
    index: CandidateIndex | None,
    has_history: bool,
    from_customer: bool,
    allow_fallback: bool,
) -> Strategy:
    """The one place the strategy is decided.

    Read as a table:

    | model loadable | history | strategy      |
    |----------------|---------|---------------|
    | no             | —       | `fallback`, or `503`   |
    | yes            | none    | `cold_start`  |
    | yes            | stored  | `personalized`|
    | yes            | inline  | `session`     |

    The `503` is the plan's: refused only when nothing can answer *and* the
    caller said they would rather have an error than a degraded answer.
    """
    if version is None or index is None:
        if not allow_fallback:
            raise UnavailableError("model_not_ready")
        return Strategy.FALLBACK
    if not has_history:
        return Strategy.COLD_START
    return Strategy.PERSONALIZED if from_customer else Strategy.SESSION


def _dedupe(refs: Sequence[str]) -> tuple[str, ...]:
    """First occurrence wins, order preserved, bounded.

    Order matters because the mean is unweighted but the truncation is not: the
    fifty kept items are the fifty most recent, and a `set` would keep an
    arbitrary fifty.
    """
    seen: dict[str, None] = {}
    for ref in refs:
        if ref not in seen:
            seen[ref] = None
        if len(seen) >= HISTORY_WINDOW:
            break
    return tuple(seen)


def _mean_vector(rows: NDArray[np.float32]) -> NDArray[np.float32] | None:
    """The serving-time user state: the L2-normalised mean of recent items.

    `None` when no row is known, which is a caller whose entire history is
    products this model was never trained on — a real state after a catalogue
    replacement, and one that must produce a cold-start answer rather than a
    query vector of zeros that ranks the catalogue by nothing.
    """
    if rows.shape[0] == 0:
        return None
    mean = rows.mean(axis=0, dtype=np.float32)
    norm = float(np.linalg.norm(mean))
    if norm == 0.0:  # pragma: no cover - orthogonal embeddings summing to zero
        return None
    return (mean / norm).astype(np.float32)


def _as_decimal(value: float) -> Any:
    import decimal

    # Six places, matching `NUMERIC(12, 6)`. Quantising here rather than letting
    # PostgreSQL round means the number a test asserts on is the number stored.
    return decimal.Decimal(str(round(value, 6)))


__all__ = [
    "HISTORY_WINDOW",
    "LANE_DEPTH",
    "POPULARITY_WINDOW_DAYS",
    "Recommendation",
    "RecommendationInput",
    "RecommendationService",
    "RecommendedItem",
    "RecentEvent",
]
