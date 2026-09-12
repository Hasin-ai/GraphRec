"""Catalog access with a short-lived cache, and hydration of recommendation IDs."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from .schemas import ProductOut, RecommendedProduct


class ProductsResource(Protocol):
    async def list(self) -> object: ...
    async def get(self, external_id: str) -> object: ...


def to_product_out(product: object) -> ProductOut:
    """Map an SDK ``Product`` (or any object with its fields) to the browser shape."""

    meta = getattr(product, "metadata", None) or {}
    status = str(getattr(product, "availability_status", "available"))
    active = bool(getattr(product, "is_active", True))
    tags = meta.get("tags") or []
    return ProductOut(
        external_id=product.external_id,  # type: ignore[attr-defined]
        title=product.title,  # type: ignore[attr-defined]
        description=getattr(product, "description", None),
        price=str(getattr(product, "price", "0")),
        category=str(getattr(product, "category", None) or "other"),
        is_active=active,
        availability_status=status,
        available=active and status == "available",
        brand=meta.get("brand"),
        size=meta.get("size"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        accent=meta.get("accent"),
    )


class CatalogCache:
    """The whole catalog (24-32 products, no pagination upstream) cached for ``ttl`` seconds."""

    def __init__(self, products: ProductsResource, ttl: float = 30.0) -> None:
        self._products = products
        self._ttl = ttl
        self._items: List[ProductOut] = []
        self._by_id: Dict[str, ProductOut] = {}
        self._expires = 0.0
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._expires = 0.0

    async def all(self) -> List[ProductOut]:
        if time.monotonic() < self._expires:
            return self._items
        async with self._lock:
            if time.monotonic() < self._expires:
                return self._items
            result = await self._products.list()
            items = [to_product_out(p) for p in getattr(result, "items", result)]
            self._items = items
            self._by_id = {p.external_id: p for p in items}
            self._expires = time.monotonic() + self._ttl
            return items

    async def listed(self, category: Optional[str] = None) -> List[ProductOut]:
        """Products a shopper can see: active and available, optionally one category."""

        items = [p for p in await self.all() if p.available]
        if category:
            items = [p for p in items if p.category == category]
        return items

    async def get(self, external_id: str) -> Optional[ProductOut]:
        await self.all()
        found = self._by_id.get(external_id)
        if found is not None:
            return found
        product = await self._products.get(external_id)  # raises NotFoundError upstream
        return to_product_out(product)

    async def hydrate(self, ranked_ids: Sequence[Tuple[str, int]]) -> Tuple[List[RecommendedProduct], int]:
        """Join ranked ``(external_id, position)`` pairs to products, preserving rank order.

        Unknown or unavailable products are omitted and counted.
        """

        await self.all()
        out: List[RecommendedProduct] = []
        omitted = 0
        for external_id, position in ranked_ids:
            product = self._by_id.get(external_id)
            if product is None or not product.available:
                omitted += 1
                continue
            out.append(RecommendedProduct(**product.model_dump(by_alias=False), position=position))
        return out, omitted
