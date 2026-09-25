"""Catalog access with a short-lived cache, and hydration of recommendation IDs."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from .schemas import ProductOut, RecommendedProduct


class ProductsResource(Protocol):
    async def list(
        self,
        *,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        external_ids: Optional[Sequence[str]] = None,
    ) -> object: ...
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


#: How many products the shop page shows; GraphRec pages at 1000.
CATALOG_PAGE = 1000
#: Largest ``ids`` filter GraphRec accepts on one product-list request.
LOOKUP_BATCH = 200


class CatalogCache:
    """The first catalog page cached for ``ttl`` seconds, plus products looked up by id.

    A demo tenant may hold a handful of products or a whole public dataset
    (tens of thousands). The shop page lists the newest ``CATALOG_PAGE``;
    recommendation and cart ids are hydrated with ``ids`` lookups and kept for
    the cache lifetime.
    """

    def __init__(self, products: ProductsResource, ttl: float = 30.0) -> None:
        self._products = products
        self._ttl = ttl
        self._items: List[ProductOut] = []
        self._by_id: Dict[str, ProductOut] = {}
        self._total = 0
        self._expires = 0.0
        self._lock = asyncio.Lock()

    @property
    def total(self) -> int:
        return self._total

    def invalidate(self) -> None:
        self._expires = 0.0

    async def all(self) -> List[ProductOut]:
        if time.monotonic() < self._expires:
            return self._items
        async with self._lock:
            if time.monotonic() < self._expires:
                return self._items
            result = await self._products.list(limit=CATALOG_PAGE)
            items = [to_product_out(p) for p in getattr(result, "items", result)]
            self._items = items
            self._by_id = {p.external_id: p for p in items}
            self._total = int(getattr(result, "total", len(items)))
            self._expires = time.monotonic() + self._ttl
            return items

    async def lookup(self, external_ids: Sequence[str]) -> Dict[str, ProductOut]:
        """Products for ``external_ids`` (cached page first, then ``ids`` lookups)."""

        await self.all()
        wanted = list(dict.fromkeys(external_ids))
        missing = [eid for eid in wanted if eid not in self._by_id]
        for start in range(0, len(missing), LOOKUP_BATCH):
            batch = missing[start : start + LOOKUP_BATCH]
            result = await self._products.list(external_ids=batch)
            for product in getattr(result, "items", result):
                out = to_product_out(product)
                self._by_id[out.external_id] = out
        return {eid: self._by_id[eid] for eid in wanted if eid in self._by_id}

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

        products = await self.lookup([external_id for external_id, _ in ranked_ids])
        out: List[RecommendedProduct] = []
        omitted = 0
        for external_id, position in ranked_ids:
            product = products.get(external_id)
            if product is None or not product.available:
                omitted += 1
                continue
            out.append(RecommendedProduct(**product.model_dump(by_alias=False), position=position))
        return out, omitted
