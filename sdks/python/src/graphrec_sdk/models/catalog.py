from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel, InputModel, ItemList

__all__ = [
    "BulkUpsertFailure",
    "Product",
    "ProductBulkUpsertResult",
    "ProductInput",
    "ProductList",
]


class ProductInput(InputModel):
    """A catalog item to create or update (``ProductUpsert`` on the server)."""

    #: Your own SKU / product identifier, unique within the tenant.
    external_id: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(default=Decimal("0.00"), ge=0)
    category: Optional[str] = Field(default=None, max_length=100)
    #: Inactive products are never recommended.
    is_active: bool = True
    #: e.g. ``available``, ``out_of_stock``, ``discontinued``.
    availability_status: str = Field(default="available", max_length=32)
    #: Free-form attributes (brand, tags, image URL...) used for cold start.
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Product(GraphRecModel):
    id: UUID
    external_id: str
    title: str
    description: Optional[str] = None
    price: Decimal
    category: Optional[str] = None
    is_active: bool
    availability_status: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    def to_input(self, **changes: Any) -> ProductInput:
        """Copy this product into a :class:`ProductInput`, applying ``changes``."""

        data: Dict[str, Any] = {
            "external_id": self.external_id,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "category": self.category,
            "is_active": self.is_active,
            "availability_status": self.availability_status,
            "metadata": dict(self.metadata),
        }
        data.update(changes)
        return ProductInput.model_validate(data)


class ProductList(ItemList[Product]):
    total: int = 0


class BulkUpsertFailure(GraphRecModel):
    external_id: str
    reason: str


class ProductBulkUpsertResult(GraphRecModel):
    accepted_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    rejected_count: int = 0
    failures: List[BulkUpsertFailure] = Field(default_factory=list)
    #: Number of HTTP requests the SDK used (payloads are split to fit the body limit).
    request_count: int = 1

    @classmethod
    def merge(cls, results: Iterable[ProductBulkUpsertResult]) -> ProductBulkUpsertResult:
        items = list(results)
        return cls(
            accepted_count=sum(r.accepted_count for r in items),
            created_count=sum(r.created_count for r in items),
            updated_count=sum(r.updated_count for r in items),
            skipped_count=sum(r.skipped_count for r in items),
            rejected_count=sum(r.rejected_count for r in items),
            failures=[failure for r in items for failure in r.failures],
            request_count=sum(r.request_count for r in items) if items else 0,
        )
