"""Applying a validated submission — one statement per target table.

This module is where "staging then a single merge transaction" is cashed out.
By the time anything here runs, every item in `ingest_staging_items` has already
been through `validation.py`; what remains are the failures only the database
can see — a product identifier that names nothing, an identifier that names a
product the tenant has disabled, the same identifier sent twice in one
collection — and those are decided in SQL, in set operations over the staging
rows, rather than by five thousand round trips.

That is not only a speed argument. A per-item loop has to decide what to do when
item four thousand fails, and every answer is bad: abandon the batch and the
tenant loses the 3,999 that were fine, or commit as you go and a retry
double-applies. Doing it as one statement per table inside one transaction makes
the question not arise. Either the whole merge lands or none of it does, and the
per-item failures are recorded as part of the same commit.

**Counts are a partition, not a tally.** For every submission:

    received = accepted + updated + skipped + failed

The console adds them up (L1380 divides their sum by `received` to draw the
progress rail), so a double-counted item shows as a rail past 100%. Each item
lands in exactly one bucket, and the bucket is decided once.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa

from graphrec.common.error_copy import resolve_item_copy

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: Written to `products.disabled_reason` when a synchronization in "upsert and
#: disable missing" mode (dc.html L1357) retires an entry the collection omits.
#: A disable requires a reason and the reason is audited (L1340) — a bulk
#: disable is no exception, and "because it was not in the file" is exactly what
#: an operator reading the audit later needs to be told.
DISABLE_MISSING_REASON = (
    "Absent from synchronization {reference}, submitted in 'upsert and disable missing' mode."
)


def _affected(result: Any) -> int:
    """Rows a DML statement touched.

    `session.execute` is typed as returning `Result`, which has no `rowcount`;
    what it actually returns for an `INSERT` or `UPDATE` is a `CursorResult`,
    which does. The cast is the narrowing, in one place, rather than an ignore
    comment at each call site.
    """
    return cast("sa.CursorResult[Any]", result).rowcount or 0


@dataclasses.dataclass(frozen=True, slots=True)
class MergeCounts:
    """What the merge did. Added to whatever the validation pass already counted."""

    accepted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0

    def __add__(self, other: MergeCounts) -> MergeCounts:
        return MergeCounts(
            accepted=self.accepted + other.accepted,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
        )


class ErrorRecorder:
    """Keeps at most `cap` failure samples, and counts all of them.

    The cap is why `failed_count` and `error_count` are separate columns. A
    5,000-item batch can fail 5,000 times; a tenant reading the submission page
    needs the first hundred and the true total, not a hundred rows and a total
    of a hundred.
    """

    def __init__(self, *, tenant_id: uuid.UUID, submission_id: uuid.UUID, cap: int) -> None:
        self.tenant_id = tenant_id
        self.submission_id = submission_id
        self.cap = cap
        self.kept = 0

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.kept)

    async def record(
        self, session: AsyncSession, *, ordinal: int, item_reference: str, code: str
    ) -> None:
        """Keep one sample, if there is room. Callers count failures themselves."""
        if self.remaining <= 0:
            return
        await session.execute(
            sa.text(
                "INSERT INTO submission_errors "
                "(tenant_id, submission_id, ordinal, item_reference, code, reason) "
                "VALUES (:tenant_id, :submission_id, :ordinal, :item_reference, :code, :reason) "
                "ON CONFLICT (submission_id, ordinal) DO NOTHING"
            ),
            {
                "tenant_id": self.tenant_id,
                "submission_id": self.submission_id,
                "ordinal": ordinal,
                "item_reference": item_reference,
                "code": code,
                # Resolved here, from the approved catalogue, by code. Never a
                # formatted exception and never any part of the item (L1391).
                "reason": resolve_item_copy(code),
            },
        )
        self.kept += 1

    async def record_set(
        self,
        session: AsyncSession,
        *,
        select_sql: str,
        params: dict[str, Any],
        code: str,
    ) -> int:
        """Sample a whole category of failures identified in SQL, and count it.

        `select_sql` must yield `(ordinal, item_reference)` ordered by ordinal.
        Two statements: one to count the category exactly, one to keep at most
        `remaining` of it. Counting from the capped insert instead would make
        `failed_count` silently top out at the cap.
        """
        total = await session.scalar(
            sa.text(f"SELECT count(*) FROM ({select_sql}) AS category"), params
        )
        total = int(total or 0)
        if total and self.remaining:
            result = await session.execute(
                sa.text(
                    "INSERT INTO submission_errors "
                    "(tenant_id, submission_id, ordinal, item_reference, code, reason) "
                    "SELECT :tenant_id, :submission_id, category.ordinal, "
                    "       left(category.item_reference, 200), :code, :reason "
                    f"FROM ({select_sql}) AS category "
                    "ORDER BY category.ordinal "
                    "LIMIT :sample_limit "
                    "ON CONFLICT (submission_id, ordinal) DO NOTHING"
                ),
                {
                    **params,
                    "tenant_id": self.tenant_id,
                    "code": code,
                    "reason": resolve_item_copy(code),
                    "sample_limit": self.remaining,
                },
            )
            self.kept += _affected(result)
        return total


# --------------------------------------------------------------------- events

#: The staged event, projected out of JSONB into the column types the merge
#: writes. Every cast here is one the validator has already guaranteed, so a
#: failure at this point is a bug in `validation.py` rather than bad input.
_STAGED_EVENTS = """
    SELECT s.ordinal,
           s.item ->> 'external_event_id'    AS external_event_id,
           s.item ->> 'external_customer_id' AS external_customer_id,
           s.item ->> 'external_product_id'  AS external_product_id,
           s.item ->> 'event_type'           AS event_type,
           (s.item ->> 'occurred_at')::timestamptz AS occurred_at,
           (s.item ->> 'value')::numeric(12, 2)    AS value,
           COALESCE(s.item -> 'context', '{}'::jsonb) AS context
    FROM ingest_staging_items s
    WHERE s.submission_id = :submission_id
"""

#: An event may name a product that is out of stock, low on stock or disabled —
#: all of those are still things that happened, and history is not edited to
#: match the current catalogue. Only a *removed* product is unknown, because its
#: row is on its way out.
_EVENT_PRODUCT_JOIN = "p.external_product_id = st.external_product_id AND p.deleted_at IS NULL"


async def merge_events(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    submission_id: uuid.UUID,
    now: dt.datetime,
    recorder: ErrorRecorder,
) -> MergeCounts:
    """Apply a staged event batch. Duplicates are successes, not errors."""
    params = {"submission_id": submission_id, "tenant_id": tenant_id, "now": now}

    unknown = await recorder.record_set(
        session,
        select_sql=(
            f"SELECT st.ordinal, st.external_event_id AS item_reference FROM ({_STAGED_EVENTS}) st "
            "WHERE NOT EXISTS (SELECT 1 FROM products p WHERE " + _EVENT_PRODUCT_JOIN + ")"
        ),
        params={"submission_id": submission_id},
        code="item_unknown_product",
    )

    # Customers are created on first reference, like categories in Phase 5. A
    # tenant does not register their customers with us and should not have to:
    # the identifier in the event is the whole of what we know about them.
    #
    # Aggregated before the insert, not merely deduplicated. `ON CONFLICT DO
    # UPDATE` refuses to touch the same row twice in one statement, and a batch
    # that mentions one customer forty times is the ordinary case.
    await session.execute(
        sa.text(
            "INSERT INTO customers "
            "(tenant_id, external_customer_id, first_seen_at, last_seen_at) "
            "SELECT :tenant_id, st.external_customer_id, "
            "       min(st.occurred_at), max(st.occurred_at) "
            f"FROM ({_STAGED_EVENTS}) st "
            "WHERE EXISTS (SELECT 1 FROM products p WHERE " + _EVENT_PRODUCT_JOIN + ") "
            "GROUP BY st.external_customer_id "
            "ON CONFLICT (tenant_id, external_customer_id) DO UPDATE SET "
            "    first_seen_at = LEAST(customers.first_seen_at, EXCLUDED.first_seen_at), "
            "    last_seen_at = GREATEST(customers.last_seen_at, EXCLUDED.last_seen_at), "
            "    updated_at = :now"
        ),
        params,
    )

    # The merge. `DO NOTHING` is the whole of "the same event_id twice yields
    # one row and two successes" (BUILD_PROMPT Phase 6): the conflicting row is
    # passed over rather than raising, and the caller counts it as skipped —
    # which the console renders under the heading "Duplicates" (L1389).
    #
    # It also settles duplicates *within* one batch, which `DO UPDATE` could
    # not: a speculative insertion that collides with a tuple this same
    # statement just wrote is simply dropped.
    applied = await session.execute(
        sa.text(
            "INSERT INTO interaction_events "
            "(tenant_id, external_event_id, customer_id, product_id, event_type, "
            " occurred_at, received_at, value, context, submission_id) "
            "SELECT :tenant_id, st.external_event_id, c.customer_id, p.product_id, "
            "       st.event_type, st.occurred_at, :now, st.value, st.context, :submission_id "
            f"FROM ({_STAGED_EVENTS}) st "
            "JOIN customers c ON c.external_customer_id = st.external_customer_id "
            "JOIN products p ON " + _EVENT_PRODUCT_JOIN + " "
            "ON CONFLICT (tenant_id, external_event_id) DO NOTHING "
            "RETURNING 1"
        ),
        params,
    )
    accepted = len(applied.fetchall())

    staged = await session.scalar(
        sa.text(f"SELECT count(*) FROM ({_STAGED_EVENTS}) st"), {"submission_id": submission_id}
    )
    # Everything staged, minus what was written, minus what named nothing. A
    # duplicate is the only remaining explanation, and it is a success.
    skipped = int(staged or 0) - accepted - unknown
    return MergeCounts(accepted=accepted, skipped=skipped, failed=unknown)


# ------------------------------------------------------------------- products

_STAGED_PRODUCTS = """
    SELECT s.ordinal,
           s.item ->> 'external_product_id' AS external_product_id,
           s.item ->> 'title'        AS title,
           s.item ->> 'category'     AS category,
           s.item ->> 'brand'        AS brand,
           (s.item ->> 'price')::numeric(12, 2) AS price,
           (s.item ->> 'is_active')::boolean    AS is_active,
           s.item ->> 'availability' AS availability,
           s.item ->> 'description'  AS description,
           COALESCE(s.item -> 'attributes', '{}'::jsonb) AS attributes,
           row_number() OVER (
               PARTITION BY s.item ->> 'external_product_id' ORDER BY s.ordinal DESC
           ) AS rn
    FROM ingest_staging_items s
    WHERE s.submission_id = :submission_id
"""

#: The last mention of an identifier wins, and the earlier ones are reported.
#: Last rather than first because a collection is a statement of the catalogue's
#: current contents, and the later line is the tenant's later word on it.
_SUPERSEDED = (
    f"SELECT r.ordinal, r.external_product_id AS item_reference "
    f"FROM ({_STAGED_PRODUCTS}) r WHERE r.rn > 1"
)

#: "external identifier already disabled" (L689) is a *failure*, not a silent
#: re-enable. A synchronization is a bulk instrument and re-enabling a product
#: someone deliberately withdrew is not something it should be able to do by
#: accident; `PATCH /v1/products/{id}` is the deliberate route (L1340).
_DISABLED_TARGET = f"""
    SELECT r.ordinal, r.external_product_id AS item_reference
    FROM ({_STAGED_PRODUCTS}) r
    WHERE r.rn = 1
      AND EXISTS (
          SELECT 1 FROM products p
          WHERE p.external_product_id = r.external_product_id
            AND NOT p.is_active
            AND p.deleted_at IS NULL
      )
"""

_WINNERS = f"""
    SELECT r.* FROM ({_STAGED_PRODUCTS}) r
    WHERE r.rn = 1
      AND NOT EXISTS (
          SELECT 1 FROM products p
          WHERE p.external_product_id = r.external_product_id
            AND NOT p.is_active
            AND p.deleted_at IS NULL
      )
"""


async def count_staged(session: AsyncSession, *, submission_id: uuid.UUID) -> int:
    """How many items survived validation and are waiting to be merged.

    The event quota is checked against this rather than against the submitted
    count: an item the validator already rejected will never become a row, and
    charging a tenant's allowance for it would mean a malformed file costs the
    same as a good one.
    """
    total = await session.scalar(
        sa.text("SELECT count(*) FROM ingest_staging_items WHERE submission_id = :submission_id"),
        {"submission_id": submission_id},
    )
    return int(total or 0)


async def count_new_products(session: AsyncSession, *, submission_id: uuid.UUID) -> int:
    """How many staged winners name a product that does not exist yet.

    Read before the merge so the product quota is checked against what the
    submission would create, not against what it created. A quota enforced after
    the fact is not a quota.
    """
    total = await session.scalar(
        sa.text(
            f"SELECT count(*) FROM ({_WINNERS}) w "
            "WHERE NOT EXISTS (SELECT 1 FROM products p "
            "                  WHERE p.external_product_id = w.external_product_id)"
        ),
        {"submission_id": submission_id},
    )
    return int(total or 0)


async def merge_products(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    submission_id: uuid.UUID,
    reference: str,
    now: dt.datetime,
    disable_missing: bool,
    recorder: ErrorRecorder,
) -> MergeCounts:
    """Apply a staged product synchronization."""
    params = {"submission_id": submission_id, "tenant_id": tenant_id, "now": now}

    superseded = await recorder.record_set(
        session,
        select_sql=_SUPERSEDED,
        params={"submission_id": submission_id},
        code="item_repeated_in_submission",
    )
    disabled = await recorder.record_set(
        session,
        select_sql=_DISABLED_TARGET,
        params={"submission_id": submission_id},
        code="item_product_disabled",
    )

    # Categories first, and by name: a synchronization names a category the way
    # a tenant thinks of it ("Hardware"), and the first mention creates it. Same
    # rule as `CatalogService._category`, so the two write paths cannot produce
    # two different categories for one name.
    await session.execute(
        sa.text(
            "INSERT INTO product_categories (tenant_id, external_category_id, name) "
            "SELECT DISTINCT :tenant_id, w.category, w.category "
            f"FROM ({_WINNERS}) w WHERE w.category IS NOT NULL "
            "ON CONFLICT (tenant_id, external_category_id) DO NOTHING"
        ),
        params,
    )

    # `xmax = 0` distinguishes the rows this statement inserted from the ones it
    # updated. It is the only way to tell them apart in a single `ON CONFLICT`
    # statement, and the console needs them apart: "Accepted" and "Updated" are
    # separate figures on the synchronization result (L1345).
    result = await session.execute(
        sa.text(
            "INSERT INTO products "
            "(tenant_id, external_product_id, title, category_id, brand, price, "
            " is_active, availability, description, attributes, created_at, updated_at) "
            "SELECT :tenant_id, w.external_product_id, w.title, c.category_id, w.brand, "
            "       w.price, w.is_active, w.availability, w.description, w.attributes, "
            "       :now, :now "
            f"FROM ({_WINNERS}) w "
            "LEFT JOIN product_categories c ON c.external_category_id = w.category "
            "ON CONFLICT (tenant_id, external_product_id) DO UPDATE SET "
            "    title = EXCLUDED.title, "
            "    category_id = EXCLUDED.category_id, "
            "    brand = EXCLUDED.brand, "
            "    price = EXCLUDED.price, "
            "    is_active = EXCLUDED.is_active, "
            "    availability = EXCLUDED.availability, "
            "    description = EXCLUDED.description, "
            "    attributes = EXCLUDED.attributes, "
            "    updated_at = :now "
            "RETURNING (xmax = 0) AS inserted"
        ),
        params,
    )
    rows = result.fetchall()
    accepted = sum(1 for row in rows if row[0])
    updated = len(rows) - accepted

    if disable_missing:
        updated += await _disable_missing(session, params=params, reference=reference)

    return MergeCounts(accepted=accepted, updated=updated, skipped=superseded, failed=disabled)


async def _disable_missing(session: AsyncSession, *, params: dict[str, Any], reference: str) -> int:
    """Retire every active product the collection did not mention.

    Compared against the *staged* set rather than the winners, deliberately. An
    item that failed because its target is already disabled still mentioned that
    product, and disabling it again — or rather, leaving it out of the mentioned
    set so that this statement re-disables it — would overwrite a reason someone
    wrote by hand with a generated one.
    """
    result = await session.execute(
        sa.text(
            "UPDATE products p SET is_active = false, "
            "    disabled_reason = :disabled_reason, disabled_at = :now, updated_at = :now "
            "WHERE p.is_active AND p.deleted_at IS NULL "
            "  AND NOT EXISTS (SELECT 1 FROM ingest_staging_items s "
            "                  WHERE s.submission_id = :submission_id "
            "                    AND s.item ->> 'external_product_id' = p.external_product_id)"
        ),
        {**params, "disabled_reason": DISABLE_MISSING_REASON.format(reference=reference)},
    )
    return _affected(result)


__all__ = [
    "DISABLE_MISSING_REASON",
    "ErrorRecorder",
    "MergeCounts",
    "count_new_products",
    "merge_events",
    "merge_products",
]
