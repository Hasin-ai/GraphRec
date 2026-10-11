from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from fixtures.products import CATEGORIES

from ..dependencies import services
from ..errors import StoreError
from ..graphrec import Services
from ..schemas import Envelope, ProductOut

router = APIRouter(tags=["catalog"])


@router.get("/products", response_model=Envelope[List[ProductOut]])
async def list_products(category: Optional[str] = Query(default=None, max_length=40), svc: Services = Depends(services)) -> Envelope[List[ProductOut]]:
    if category and category not in CATEGORIES:
        raise StoreError(422, "unknown_category", f"Unknown category '{category}'. Use one of: {', '.join(CATEGORIES)}.")
    items = await svc.catalog.listed(category)
    return Envelope(data=items, meta={"count": len(items), "categories": list(CATEGORIES)})


@router.get("/products/{external_id}", response_model=Envelope[ProductOut])
async def get_product(external_id: str, svc: Services = Depends(services)) -> Envelope[ProductOut]:
    product = await svc.catalog.get(external_id)  # NotFoundError -> 404 via the error handlers
    if product is None:
        raise StoreError(404, "not_found", "That product does not exist in this store.")
    return Envelope(data=product)
