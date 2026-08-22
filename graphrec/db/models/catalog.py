"""The catalog's two tables.

Mirrors migration 0007. Note what is *not* here: an `eligible` column and a
`why` column. Eligibility is derived (BACKEND_PLAN §3.5) and the derivation
lives in SQL, in `product_ineligibility`, so that the API's badge, the serving
path's filter and the partial index that filter walks are the same expression
rather than three copies of one rule.

`Product.ineligibility` below is therefore a *hybrid* — Python for an object
already in memory, SQL for a query — and both spellings compile to the same
`CASE`. See `graphrec/catalog/eligibility.py`.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, Text, case, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from graphrec.common.enums import Availability
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column


class ProductCategory(Base, TenantOwned):
    """A tenant's own category, addressed by the tenant's own identifier."""

    __tablename__ = "product_categories"

    category_id: Mapped[uuid.UUID] = pk_uuid()
    external_category_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<ProductCategory {self.category_id}>"


class Product(Base, TenantOwned):
    """One catalogue entry, addressed on the wire by `external_product_id`."""

    __tablename__ = "products"

    product_id: Mapped[uuid.UUID] = pk_uuid()
    external_product_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_categories.category_id", ondelete="SET NULL")
    )
    #: Eagerly loaded, because every render of a product needs the tenant's own
    #: category identifier and a lazy load on an async session raises rather
    #: than emitting a query. One extra `SELECT ... IN (...)` per page, not one
    #: per row.
    category: Mapped[ProductCategory | None] = relationship(lazy="selectin")
    brand: Mapped[str | None] = mapped_column(Text)
    #: `numeric(12,2)`. Never a float: a price that cannot be represented
    #: exactly is a price a tenant will eventually be billed against.
    price: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    availability: Mapped[str] = mapped_column(Text, default=Availability.IN_STOCK.value)
    description: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    #: Tenant deletion and retention, not `:disable`. See migration 0007.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    disabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    @hybrid_property
    def ineligibility(self) -> str | None:
        """The reason this product is excluded from serving, or `None`.

        The Python branch is for an instance already loaded; the SQL branch is
        what a query emits. They are kept identical by
        `tests/catalog/test_eligibility.py`, which evaluates every combination
        of the three inputs through both and compares.
        """
        if self.deleted_at is not None:
            return "product_removed"
        if not self.is_active:
            return "product_inactive"
        if self.availability == Availability.OUT_OF_STOCK.value:
            return "product_out_of_stock"
        return None

    @ineligibility.inplace.expression
    @classmethod
    def _ineligibility_expression(cls) -> Any:
        # The database function, not a re-implementation of it. Calling it here
        # is also what lets the planner match `ix_products_eligible`, whose
        # predicate is this same call.
        return func.product_ineligibility(cls.is_active, cls.availability, cls.deleted_at)

    @hybrid_property
    def eligible(self) -> bool:
        return self.ineligibility is None

    @eligible.inplace.expression
    @classmethod
    def _eligible_expression(cls) -> Any:
        # `cls.ineligibility` here is the SQL expression above, not the
        # Python branch — the hybrid resolves by access type, not by name.
        return case((cls.ineligibility.is_(None), True), else_=False)

    def __repr__(self) -> str:
        # No title, no price. A repr reaches logs, and a catalogue is a tenant's
        # commercially sensitive data (NR-NF-06).
        return f"<Product {self.product_id}>"
