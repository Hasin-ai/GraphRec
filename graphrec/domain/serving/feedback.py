"""Impressions, clicks and conversions — recorded, and deliberately inert.

ASM-05: feedback is informational and never auto-activates a model. Nothing in
this module writes to `model_versions`, `model_deployments` or the training
queue, and nothing reads this data back into a ranking. That is the assumption
made structural: a future change that wanted feedback to influence serving would
have to add an import here, which is a reviewable event.

**A repeat is a success, not a conflict.** The tenant's `event_id` is the
idempotency key and a retried batch is the normal consequence of a timeout on
their side. `duplicate_confirmed` counts the item as accepted and moves on,
exactly as ingestion does — the plan uses the same word for both.

**Feedback must name a request this tenant made.** `request_id` is resolved
against `recommendation_requests` under RLS, so a foreign identifier resolves to
nothing and is refused as unknown. Saying "that request belongs to someone else"
would be a cross-tenant disclosure dressed up as a helpful error.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from graphrec.common.errors import NotFoundError
from graphrec.db.models import (
    Product,
    RecommendationFeedback,
    RecommendationImpression,
    RecommendationRequest,
)
from graphrec.serving.states import FeedbackType

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImpressionItem:
    """One shown item. `position` is the rank the tenant actually rendered,
    which is not necessarily the rank returned — a page can drop an item."""

    external_event_id: str
    external_product_id: str
    position: int


@dataclass(frozen=True, slots=True)
class FeedbackItem:
    """One click or conversion. `value` is present on conversions only."""

    external_feedback_id: str
    external_product_id: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class FeedbackReceipt:
    """What the endpoint returns.

    `duplicates` is reported separately from `accepted` rather than folded into
    it, because a client retrying a whole batch wants to see that the retry was
    recognised — a receipt saying "20 accepted" twice is indistinguishable from
    double-counting.
    """

    accepted: int
    duplicates: int
    unknown_products: tuple[str, ...] = ()

    @property
    def received(self) -> int:
        return self.accepted + self.duplicates + len(self.unknown_products)


class FeedbackService:
    """Three endpoints, one write path."""

    async def record_impressions(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        external_request_id: str,
        items: Sequence[ImpressionItem],
        now: dt.datetime | None = None,
    ) -> FeedbackReceipt:
        request_id = await self._request_id(session, external_request_id=external_request_id)
        products = await self._product_ids(
            session, refs=[item.external_product_id for item in items]
        )
        moment = now or dt.datetime.now(dt.UTC)

        accepted = 0
        duplicates = 0
        unknown: list[str] = []
        for item in items:
            product_id = products.get(item.external_product_id)
            if product_id is None:
                unknown.append(item.external_product_id)
                continue
            inserted = await self._insert(
                session,
                statement=pg_insert(RecommendationImpression).values(
                    tenant_id=tenant_id,
                    external_event_id=item.external_event_id,
                    request_id=request_id,
                    product_id=product_id,
                    position=item.position,
                    occurred_at=moment,
                ),
                index_elements=["tenant_id", "external_event_id"],
            )
            if inserted:
                accepted += 1
            else:
                duplicates += 1
        return FeedbackReceipt(
            accepted=accepted, duplicates=duplicates, unknown_products=tuple(unknown)
        )

    async def record_feedback(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        external_request_id: str,
        feedback_type: FeedbackType,
        items: Sequence[FeedbackItem],
        now: dt.datetime | None = None,
    ) -> FeedbackReceipt:
        """Clicks and conversions, which differ only in the type and the value.

        One method rather than two: the two endpoints exist because the
        `/integration` page documents them separately, and a second copy of this
        loop would be a second place for the idempotency rule to be wrong.
        """
        request_id = await self._request_id(session, external_request_id=external_request_id)
        products = await self._product_ids(
            session, refs=[item.external_product_id for item in items]
        )
        impressions = await self._impressions_for(session, request_id=request_id)
        moment = now or dt.datetime.now(dt.UTC)

        accepted = 0
        duplicates = 0
        unknown: list[str] = []
        for item in items:
            product_id = products.get(item.external_product_id)
            if product_id is None:
                unknown.append(item.external_product_id)
                continue
            inserted = await self._insert(
                session,
                statement=pg_insert(RecommendationFeedback).values(
                    tenant_id=tenant_id,
                    external_feedback_id=item.external_feedback_id,
                    request_id=request_id,
                    # Linked when the tenant reported the impression first, and
                    # `NULL` when they did not. Not required: a tenant who sends
                    # clicks and no impressions is sending less data, not
                    # invalid data.
                    impression_id=impressions.get(product_id),
                    product_id=product_id,
                    feedback_type=feedback_type.value,
                    value=item.value if feedback_type is FeedbackType.CONVERSION else None,
                    occurred_at=moment,
                ),
                index_elements=["tenant_id", "external_feedback_id"],
            )
            if inserted:
                accepted += 1
            else:
                duplicates += 1
        return FeedbackReceipt(
            accepted=accepted, duplicates=duplicates, unknown_products=tuple(unknown)
        )

    # ------------------------------------------------------------------ parts

    async def _insert(
        self, session: AsyncSession, *, statement: Any, index_elements: list[str]
    ) -> bool:
        """`ON CONFLICT DO NOTHING`, reporting whether the row landed.

        The database decides, not a prior `SELECT`. Two concurrent retries of
        the same batch would both see "absent" and both insert; here one of them
        is told nothing was written, which is the truth.

        **The verdict is `RETURNING`, not `rowcount`.** An ORM insert against an
        entity with a generated key already carries an implicit `RETURNING`, and
        on such a statement psycopg reports `rowcount` as `-1` until the rows are
        consumed — which is truthy, so every duplicate would be counted as an
        acceptance and the receipt would tell an integrator their retry had been
        stored twice. Asking for the key back and looking at whether one arrived
        is unambiguous: `DO NOTHING` returns no row.
        """
        table = statement.table
        key = next(iter(table.primary_key.columns))
        result = await session.execute(
            statement.on_conflict_do_nothing(index_elements=index_elements).returning(key)
        )
        return result.first() is not None

    async def _request_id(self, session: AsyncSession, *, external_request_id: str) -> uuid.UUID:
        found = await session.scalar(
            sa.select(RecommendationRequest.request_id).where(
                RecommendationRequest.external_request_id == external_request_id
            )
        )
        if found is None:
            raise NotFoundError("recommendation_request_unknown")
        return found

    async def _product_ids(
        self, session: AsyncSession, *, refs: Sequence[str]
    ) -> dict[str, uuid.UUID]:
        if not refs:
            return {}
        rows = (
            await session.execute(
                sa.select(Product.external_product_id, Product.product_id).where(
                    Product.external_product_id.in_(list(refs))
                )
            )
        ).all()
        return dict(rows)  # type: ignore[arg-type]

    async def _impressions_for(
        self, session: AsyncSession, *, request_id: uuid.UUID
    ) -> dict[uuid.UUID, uuid.UUID]:
        """`product -> impression` for one request.

        The last impression of a product wins if a tenant reported it twice at
        two positions, which is arbitrary and harmless: the link is a
        convenience for analysis, and the impression rows themselves are all
        still there.
        """
        rows = (
            await session.execute(
                sa.select(
                    RecommendationImpression.product_id,
                    RecommendationImpression.impression_id,
                ).where(RecommendationImpression.request_id == request_id)
            )
        ).all()
        return dict(rows)  # type: ignore[arg-type]


__all__ = [
    "FeedbackItem",
    "FeedbackReceipt",
    "FeedbackService",
    "ImpressionItem",
]
