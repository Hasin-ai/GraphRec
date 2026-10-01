from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProductUpsert(BaseModel):
    external_id: str = Field(..., max_length=100)
    title: str = Field(..., max_length=255)
    description: str | None = None
    price: Decimal = Field(default=Decimal("0.00"), ge=0)
    category: str | None = Field(default=None, max_length=100)
    is_active: bool = True
    # Only "available" products are servable; reject unknown values instead of
    # silently storing them (e.g. "in_stock" made products invisible to recommendations).
    availability_status: Literal["available", "unavailable", "out_of_stock", "discontinued"] = "available"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductBulkUpsertRequest(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    products: list[ProductUpsert] = Field(..., min_length=1, max_length=1000)


class ProductBulkFailure(BaseModel):
    external_id: str
    reason: str


class ProductBulkUpsertResponse(BaseModel):
    sync_id: UUID | None = None
    status: str = "completed"
    request_id: str | None = None
    accepted_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    rejected_count: int
    failures: list[ProductBulkFailure] = Field(default_factory=list)
    outcomes: list[dict[str, str]] = Field(default_factory=list)


class CatalogSyncResource(ProductBulkUpsertResponse):
    created_at: datetime


class ProductResource(BaseModel):
    id: UUID
    external_id: str
    title: str
    description: str | None = None
    price: Decimal
    category: str | None = None
    is_active: bool
    availability_status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    items: list[ProductResource]
    total: int
