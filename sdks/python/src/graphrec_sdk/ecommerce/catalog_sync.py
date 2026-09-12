"""Catalog synchronisation from a source of truth (PIM, ERP, Shopify/WooCommerce export...).

::

    from graphrec_sdk.ecommerce import CatalogSync

    report = CatalogSync(client).run(
        ({"external_id": row.sku, "title": row.name, "price": row.price,
          "category": row.category, "metadata": {"brand": row.brand}} for row in rows),
        disable_missing=True,     # products absent from this feed stop being recommended
    )
    print(report.summary())
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Set

from pydantic import Field

from .._validation import coerce_input
from ..errors import APIError, InputValidationError
from ..models._base import GraphRecModel
from ..models.catalog import ProductBulkUpsertResult, ProductInput
from ..resources.products import ProductLike

if TYPE_CHECKING:
    from .._client import AsyncGraphRec, GraphRec

__all__ = ["AsyncCatalogSync", "CatalogSync", "CatalogSyncReport"]


class CatalogSyncReport(GraphRecModel):
    upsert: ProductBulkUpsertResult
    #: Active products that were not in the feed and have been disabled.
    disabled_ids: List[str] = Field(default_factory=list)
    #: Products that could not be disabled, with the error message.
    disable_failures: Dict[str, str] = Field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.upsert.failures and not self.disable_failures

    def summary(self) -> str:
        u = self.upsert
        return (
            f"created={u.created_count} updated={u.updated_count} rejected={u.rejected_count} "
            f"disabled={len(self.disabled_ids)} disable_failures={len(self.disable_failures)} "
            f"requests={u.request_count} in {self.duration_seconds:.1f}s"
        )


def _prepare(
    products: Iterable[ProductLike], allow_empty: bool, disable_missing: bool
) -> List[ProductInput]:
    items = [coerce_input(ProductInput, product) for product in products]
    if not items and disable_missing and not allow_empty:
        raise InputValidationError(
            "Refusing to sync an empty feed with disable_missing=True (it would disable the "
            "whole catalog). Pass allow_empty=True if that is intended."
        )
    return items


class CatalogSync:
    def __init__(self, client: GraphRec) -> None:
        self._client = client

    def run(
        self,
        products: Iterable[ProductLike],
        *,
        disable_missing: bool = False,
        allow_empty: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> CatalogSyncReport:
        started = time.monotonic()
        items = _prepare(products, allow_empty, disable_missing)
        upsert = (
            self._client.products.bulk_upsert(items, idempotency_key=idempotency_key)
            if items
            else ProductBulkUpsertResult(request_count=0)
        )
        disabled: List[str] = []
        failures: Dict[str, str] = {}
        if disable_missing:
            feed: Set[str] = {item.external_id for item in items}
            for product in self._client.products.list():
                if product.is_active and product.external_id not in feed:
                    try:
                        self._client.products.disable(product.external_id)
                        disabled.append(product.external_id)
                    except APIError as exc:
                        failures[product.external_id] = str(exc)
        return CatalogSyncReport(
            upsert=upsert,
            disabled_ids=disabled,
            disable_failures=failures,
            duration_seconds=time.monotonic() - started,
        )


class AsyncCatalogSync:
    def __init__(self, client: AsyncGraphRec) -> None:
        self._client = client

    async def run(
        self,
        products: Iterable[ProductLike],
        *,
        disable_missing: bool = False,
        allow_empty: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> CatalogSyncReport:
        started = time.monotonic()
        items = _prepare(products, allow_empty, disable_missing)
        upsert = (
            await self._client.products.bulk_upsert(items, idempotency_key=idempotency_key)
            if items
            else ProductBulkUpsertResult(request_count=0)
        )
        disabled: List[str] = []
        failures: Dict[str, str] = {}
        if disable_missing:
            feed: Set[str] = {item.external_id for item in items}
            for product in await self._client.products.list():
                if product.is_active and product.external_id not in feed:
                    try:
                        await self._client.products.disable(product.external_id)
                        disabled.append(product.external_id)
                    except APIError as exc:
                        failures[product.external_id] = str(exc)
        return CatalogSyncReport(
            upsert=upsert,
            disabled_ids=disabled,
            disable_failures=failures,
            duration_seconds=time.monotonic() - started,
        )
