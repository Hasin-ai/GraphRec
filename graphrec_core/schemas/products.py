from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProductUpsert(BaseModel):
    external_id: str = Field(..., max_length=100)
    title: str = Field(..., max_length=255)
    description: str | None = None
    price: Decimal = Field(default=Decimal("0.00"), ge=0)
    category: str | None = Field(default=None, max_length=100)
    is_active: bool = True
    availability_status: str = Field(default="available", max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductBulkUpsertRequest(BaseModel):
    products: list[ProductUpsert] = Field(..., min_items=1)


class ProductBulkFailure(BaseModel):
    external_id: str
    reason: str


class ProductBulkUpsertResponse(BaseModel):
    accepted_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    rejected_count: int
    failures: list[ProductBulkFailure] = Field(default_factory=list)


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
