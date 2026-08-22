"""Catalogue reads and writes.

Three write verbs, and the difference between them is the whole of D9:

  * `create` refuses a duplicate with a `409`. It serves `/products/new`, whose
    conflict path is "A product with identifier SKU-4471 already exists."
    (dc.html L1604) — a message a `PUT` upsert can never produce.
  * `upsert` is idempotent and serves integrations, which retry.
  * `patch` changes named fields and leaves the rest, and serves
    `/products/:productId`, where the form is pre-filled and a blank field means
    "unchanged" rather than "clear this".

The quota check runs **inside the creating transaction** (ER-F-11: limits are
enforced *before* a bounded operation is accepted). Counting in one transaction
and inserting in another is how two concurrent creates both see 49,999 and
commit the 50,001st product.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.enums import Availability, UsageType
from graphrec.common.error_copy import resolve_field_copy
from graphrec.common.errors import ConflictError, LimitError, NotFoundError, ValidationError
from graphrec.db.models import Product, ProductCategory
from graphrec.domain import quotas

if TYPE_CHECKING:
    import datetime as dt
    import decimal
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

#: L1341's placeholder is "Discontinued by supplier" and BACKEND_PLAN §12 sets a
#: floor of four characters for every audited reason. Repeated as a constant
#: because the same floor applies to five unrelated actions.
MIN_REASON_LENGTH = 4
MAX_REASON_LENGTH = 500

#: Sentinel for `patch`: distinguishes "not mentioned" from "set to null".
#: `None` cannot do that job, because `brand: null` is a legitimate clear.
UNSET: Any = object()


@dataclasses.dataclass(frozen=True, slots=True)
class ProductWrite:
    """The writable surface of a product. `UNSET` fields are left alone."""

    title: str | Any = UNSET
    category: str | None | Any = UNSET
    brand: str | None | Any = UNSET
    price: decimal.Decimal | None | Any = UNSET
    availability: str | Any = UNSET
    description: str | None | Any = UNSET
    is_active: bool | Any = UNSET
    attributes: dict[str, Any] | Any = UNSET

    def mentioned(self) -> dict[str, Any]:
        return {
            field.name: getattr(self, field.name)
            for field in dataclasses.fields(self)
            if getattr(self, field.name) is not UNSET
        }


@dataclasses.dataclass(frozen=True, slots=True)
class ProductFilter:
    """The console's three filters (dc.html L1314), and nothing else."""

    category: str | None = None
    availability: str | None = None
    search: str | None = None
    #: `False` excludes products removed by retention. The console never shows
    #: them, so it is the default; a report might want them.
    include_removed: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Page:
    """D10 for console lists: `limit`/`offset` and a **total**.

    The total is not optional. Every console table renders a count of the form
    "8 of 12" (`count: list.length + ' of ' + s.products.length`, L1316), and a
    cursor cannot produce one.
    """

    items: Sequence[Product]
    total: int
    limit: int
    offset: int


class CatalogService:
    """Products and their categories, within one tenant."""

    def __init__(self, *, max_page_size: int = 200, default_page_size: int = 50) -> None:
        self._max_page_size = max_page_size
        self._default_page_size = default_page_size

    # ------------------------------------------------------------------ read

    async def get(self, session: AsyncSession, *, external_product_id: str) -> Product:
        """A foreign product and an absent one are the same `404` (gate 4)."""
        product = await session.scalar(
            sa.select(Product).where(Product.external_product_id == external_product_id)
        )
        if product is None or product.deleted_at is not None:
            raise NotFoundError("not_found")
        return product

    async def list_products(
        self,
        session: AsyncSession,
        *,
        filters: ProductFilter | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Page:
        # Not `list`: a method of that name shadows the builtin in class scope,
        # and every `list[...]` annotation in the class then resolves to it.
        filters = filters or ProductFilter()
        limit = self._page_size(limit)
        if offset < 0:
            raise ValidationError("invalid_request").with_field(
                "offset", "Must be zero or greater."
            )

        conditions = self._conditions(filters)
        # Counted with the same predicate list, built once. Two hand-written
        # WHERE clauses is how a list comes to say "8 of 12" while showing nine.
        total = await session.scalar(
            sa.select(sa.func.count()).select_from(Product).where(*conditions)
        )
        rows = await session.scalars(
            sa.select(Product)
            .where(*conditions)
            # `updated_at DESC` is what the console's Updated column sorts by;
            # `external_product_id` breaks ties so that two products written in
            # the same transaction paginate deterministically (ER-NF-06).
            .order_by(Product.updated_at.desc(), Product.external_product_id)
            .limit(limit)
            .offset(offset)
        )
        return Page(items=list(rows), total=int(total or 0), limit=limit, offset=offset)

    async def eligible_ids(
        self, session: AsyncSession, *, limit: int | None = None
    ) -> Sequence[uuid.UUID]:
        """The serving path's call site.

        `Product.eligible` compiles to `product_ineligibility(...) IS NULL`,
        which is the predicate of `ix_products_eligible`. This is the second of
        the two call sites Phase 5's exit criterion names, and it reaches the
        rule through the same expression the first one does.
        """
        statement = sa.select(Product.product_id).where(Product.eligible)
        if limit is not None:
            statement = statement.order_by(Product.product_id).limit(limit)
        return list(await session.scalars(statement))

    def _page_size(self, limit: int | None) -> int:
        if limit is None:
            return self._default_page_size
        if limit < 1 or limit > self._max_page_size:
            raise ValidationError("invalid_request").with_field(
                "limit", f"Must be between 1 and {self._max_page_size}."
            )
        return limit

    def _conditions(self, filters: ProductFilter) -> list[Any]:
        conditions: list[Any] = []
        if not filters.include_removed:
            conditions.append(Product.deleted_at.is_(None))
        if filters.category is not None:
            conditions.append(
                Product.category_id.in_(
                    sa.select(ProductCategory.category_id).where(
                        ProductCategory.external_category_id == filters.category
                    )
                )
            )
        if filters.availability is not None:
            conditions.append(Product.availability == self._availability(filters.availability))
        if filters.search is not None and filters.search.strip():
            # "identifier or title" (L1314). `ilike` with an escaped pattern, so
            # a tenant searching for "50%" is searching for a literal percent.
            pattern = "%" + _escape_like(filters.search.strip()) + "%"
            conditions.append(
                sa.or_(
                    Product.external_product_id.ilike(pattern, escape="\\"),
                    Product.title.ilike(pattern, escape="\\"),
                )
            )
        return conditions

    # ----------------------------------------------------------------- write

    async def create(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        external_product_id: str,
        write: ProductWrite,
        now: dt.datetime | None = None,
    ) -> Product:
        """`POST /v1/products`. Create only — a duplicate is a `409`."""
        now = now or quotas.utcnow()
        external_product_id = self._external_id(external_product_id)
        title = self._title(write)

        existing = await session.scalar(
            sa.select(Product.product_id).where(Product.external_product_id == external_product_id)
        )
        if existing is not None:
            raise ConflictError(
                "product_already_exists",
                copy_args={"external_product_id": external_product_id},
            ).with_field("external_product_id", resolve_field_copy("product_already_exists") or "")

        await self._assert_product_quota(session, tenant_id=tenant_id, now=now)

        product = Product(
            tenant_id=tenant_id,
            external_product_id=external_product_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        await self._apply(session, product, write, tenant_id=tenant_id, now=now)
        session.add(product)
        await session.flush()
        return product

    async def upsert(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        external_product_id: str,
        write: ProductWrite,
        now: dt.datetime | None = None,
    ) -> tuple[Product, bool]:
        """`PUT /v1/products/{external_id}`. Returns `(product, created)`.

        Idempotent by the external identifier, which dc.html L1320 states *is*
        the idempotency key. An integration that retries a timed-out `PUT` gets
        the same product and the same answer, not a second one and not a `409`.
        """
        now = now or quotas.utcnow()
        external_product_id = self._external_id(external_product_id)
        title = self._title(write)

        product = await session.scalar(
            sa.select(Product).where(Product.external_product_id == external_product_id)
        )
        if product is None:
            await self._assert_product_quota(session, tenant_id=tenant_id, now=now)
            product = Product(
                tenant_id=tenant_id,
                external_product_id=external_product_id,
                title=title,
                created_at=now,
                updated_at=now,
            )
            session.add(product)
            created = True
        else:
            product.title = title
            created = False

        # A PUT replaces: fields the caller omitted go back to their defaults
        # rather than keeping whatever a previous write left. That is the
        # difference between PUT and PATCH, and an integration that relies on
        # the other reading will silently keep stale data forever.
        await self._apply(session, product, self._complete(write), tenant_id=tenant_id, now=now)
        await session.flush()
        return product, created

    async def patch(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        external_product_id: str,
        write: ProductWrite,
        now: dt.datetime | None = None,
    ) -> Product:
        """`PATCH /v1/products/{external_id}`. Named fields only."""
        now = now or quotas.utcnow()
        product = await self.get(session, external_product_id=external_product_id)

        if "title" in write.mentioned():
            product.title = self._title(write)
        await self._apply(session, product, write, tenant_id=tenant_id, now=now)
        await session.flush()
        return product

    async def disable(
        self,
        session: AsyncSession,
        *,
        external_product_id: str,
        reason: str,
        now: dt.datetime | None = None,
    ) -> Product:
        """`POST /v1/products/{external_id}:disable`.

        "A disabled product stops being returned by serving immediately. The
        record is retained and can be re-enabled by an update." (L1339-L1340) —
        so this sets a flag; it does not delete, and there is no `DELETE` grant
        that would let it.
        """
        now = now or quotas.utcnow()
        reason = self._reason(reason)
        product = await self.get(session, external_product_id=external_product_id)

        if not product.is_active:
            raise ConflictError("product_already_disabled")

        product.is_active = False
        product.disabled_reason = reason
        product.disabled_at = now
        product.updated_at = now
        await session.flush()
        return product

    # ------------------------------------------------------------- internals

    async def _apply(
        self,
        session: AsyncSession,
        product: Product,
        write: ProductWrite,
        *,
        tenant_id: uuid.UUID,
        now: dt.datetime,
    ) -> None:
        mentioned = write.mentioned()

        if "category" in mentioned:
            # Assigned through the relationship, not through `category_id`, so
            # the object the router renders already has the category loaded.
            # Setting the foreign key alone leaves `product.category` stale, and
            # a stale relationship on an async session raises on access rather
            # than quietly re-reading.
            product.category = await self._category(
                session, tenant_id=tenant_id, external_category_id=mentioned["category"], now=now
            )
        if "brand" in mentioned:
            product.brand = mentioned["brand"]
        if "price" in mentioned:
            price = mentioned["price"]
            if price is not None and price < 0:
                # L1614 reports "price is not a positive decimal" per item
                # during a sync, and 0007 has the same rule as a check
                # constraint. Named here so a single write is refused with the
                # same words a bulk one is.
                raise ValidationError("invalid_request").with_field(
                    "price", "Must be a positive decimal."
                )
            product.price = price
        if "availability" in mentioned:
            product.availability = self._availability(mentioned["availability"])
        if "description" in mentioned:
            product.description = mentioned["description"]
        if "attributes" in mentioned:
            product.attributes = mentioned["attributes"] or {}
        if "is_active" in mentioned:
            self._set_active(product, active=bool(mentioned["is_active"]), now=now)

        product.updated_at = now

    def _set_active(self, product: Product, *, active: bool, now: dt.datetime) -> None:
        if active and not product.is_active:
            # "can be re-enabled by an update" (L1340). The disable reason goes
            # with the state it explained — the audit record is what retains it,
            # and a stale reason on a live product reads as if it still applied.
            product.is_active = True
            product.disabled_reason = None
            product.disabled_at = None
        elif not active and product.is_active:
            # An update that deactivates without a reason still has to satisfy
            # `ck_products_disabled_has_reason`. `:disable` is the route that
            # collects one, so this path records why the reason is generic.
            product.is_active = False
            product.disabled_reason = "Deactivated by a catalog update."
            product.disabled_at = now

    async def _category(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        external_category_id: str | None,
        now: dt.datetime,
    ) -> ProductCategory | None:
        """Categories are created on reference.

        The console offers a fixed select (L1322) and has no category-management
        screen, and a sync carries category names inline (L1173). Requiring a
        category to be created first would make both of those two calls.
        """
        if external_category_id is None or not external_category_id.strip():
            return None
        external_category_id = external_category_id.strip()
        if len(external_category_id) > 120:
            # L1614: "category exceeds 120 characters".
            raise ValidationError("invalid_request").with_field(
                "category", "Must be 120 characters or fewer."
            )

        existing = await session.scalar(
            sa.select(ProductCategory).where(
                ProductCategory.external_category_id == external_category_id
            )
        )
        if existing is not None:
            return existing

        category = ProductCategory(
            tenant_id=tenant_id,
            external_category_id=external_category_id,
            name=external_category_id,
            created_at=now,
            updated_at=now,
        )
        session.add(category)
        await session.flush()
        return category

    async def _assert_product_quota(
        self, session: AsyncSession, *, tenant_id: uuid.UUID, now: dt.datetime
    ) -> None:
        """L1603, with the counts in the message.

        Runs in the caller's transaction, immediately before the insert. The
        count it takes is therefore the count that insert is measured against —
        `READ COMMITTED` still lets two concurrent creates both pass at the
        boundary, which is a one-product overshoot on a 50,000-product limit and
        is accepted deliberately; serialising every catalogue write behind a
        lock to prevent it would cost far more than it saves.
        """
        limit = await quotas.effective_limit(
            session, tenant_id=tenant_id, usage_type=UsageType.PRODUCTS, now=now
        )
        if limit is None:
            return

        used = int(
            await session.scalar(
                sa.select(sa.func.count()).select_from(Product).where(Product.deleted_at.is_(None))
            )
            or 0
        )
        if used < limit:
            return

        code = await quotas.plan_code(session, tenant_id=tenant_id)
        raise LimitError(
            "product_quota_exhausted",
            copy_args={"used": f"{used:,}", "limit": f"{limit:,}", "plan_code": code},
        )

    def _complete(self, write: ProductWrite) -> ProductWrite:
        """Fill a `PUT`'s omissions with defaults. See `upsert`."""
        mentioned = write.mentioned()
        return ProductWrite(
            title=mentioned.get("title", UNSET),
            category=mentioned.get("category", None),
            brand=mentioned.get("brand", None),
            price=mentioned.get("price", None),
            availability=mentioned.get("availability", Availability.IN_STOCK.value),
            description=mentioned.get("description", None),
            is_active=mentioned.get("is_active", True),
            attributes=mentioned.get("attributes", {}),
        )

    def _external_id(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValidationError("external_id_required").with_field(
                "external_product_id", resolve_field_copy("external_id_required") or ""
            )
        if len(value) > 120:
            raise ValidationError("invalid_request").with_field(
                "external_product_id", "Must be 120 characters or fewer."
            )
        return value

    def _title(self, write: ProductWrite) -> str:
        title = write.mentioned().get("title")
        if title is None or not str(title).strip():
            raise ValidationError("title_required").with_field(
                "title", resolve_field_copy("title_required") or ""
            )
        title = str(title).strip()
        if len(title) > 500:
            raise ValidationError("invalid_request").with_field(
                "title", "Must be 500 characters or fewer."
            )
        return title

    def _availability(self, value: str) -> str:
        try:
            return Availability(value).value
        except ValueError:
            # The rejected value is not echoed. A caller's string in an error
            # body is a caller's string in a log line (NR-NF-06).
            raise ValidationError("invalid_request").with_field(
                "availability", "Not a recognised availability."
            ) from None

    def _reason(self, reason: str) -> str:
        reason = (reason or "").strip()
        if len(reason) < MIN_REASON_LENGTH:
            # L1342, which is what `dlgDisable` returns when the field holds
            # fewer than four characters: "A reason is required for this
            # action." The dialog's *consequence* line (L1340) says the reason
            # is written to the audit history — that is a description of what
            # happens, not the refusal, and using it here would put the wrong
            # sentence on the wrong event.
            raise ValidationError("reason_required").with_field("reason", "Required.")
        if len(reason) > MAX_REASON_LENGTH:
            raise ValidationError("invalid_request").with_field(
                "reason", f"Must be {MAX_REASON_LENGTH} characters or fewer."
            )
        return reason


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["MAX_REASON_LENGTH", "MIN_REASON_LENGTH", "UNSET", "CatalogService"]
