from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union, cast

from .._base_client import OMIT
from .._batching import chunk_items
from .._ids import new_idempotency_key
from .._serialization import to_jsonable
from .._validation import coerce_input, enum_value
from ..errors import APIError, InputValidationError
from ..models.catalog import (
    BulkUpsertFailure,
    Product,
    ProductBulkUpsertResult,
    ProductInput,
    ProductList,
)
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncProducts", "Products"]

ProductLike = Union[ProductInput, Mapping[str, Any]]
_DUPLICATE_REASON = "Duplicate item external_id within batch"


def _plan_bulk(
    products: Iterable[ProductLike], *, max_bytes: int, max_items: int
) -> Tuple[List[List[Dict[str, Any]]], List[BulkUpsertFailure]]:
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    duplicates: List[BulkUpsertFailure] = []
    for raw in products:
        item = coerce_input(ProductInput, raw)
        if item.external_id in seen:
            duplicates.append(
                BulkUpsertFailure(external_id=item.external_id, reason=_DUPLICATE_REASON)
            )
            continue
        seen.add(item.external_id)
        unique.append(to_jsonable(item))
    if not unique:
        raise InputValidationError("bulk_upsert() needs at least one product")
    chunks = chunk_items(
        unique,
        envelope_key="products",
        max_bytes=max_bytes,
        max_items=max_items,
        describe="Product",
    )
    return chunks, duplicates


def _chunk_key(base: Optional[str], index: int, total: int) -> str:
    if base is None:
        return new_idempotency_key()
    return base if total == 1 else f"{base}:{index + 1}/{total}"


def _combine(
    results: List[ProductBulkUpsertResult], duplicates: List[BulkUpsertFailure]
) -> ProductBulkUpsertResult:
    merged = ProductBulkUpsertResult.merge(results)
    if duplicates:
        merged.rejected_count += len(duplicates)
        merged.failures = [*merged.failures, *duplicates]
    return merged


def _update_input(current: Product, changes: Dict[str, Any]) -> Dict[str, Any]:
    if not changes:
        raise InputValidationError("update() needs at least one field to change")
    data = current.to_input().model_dump()
    data.update({key: enum_value(value) for key, value in changes.items()})
    return cast(Dict[str, Any], to_jsonable(coerce_input(ProductInput, data)))


def _changes(**fields: Any) -> Dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not OMIT}


class Products(SyncResource):
    """Tenant catalog. Scopes: ``catalog:read`` / ``catalog:write``."""

    def bulk_upsert(
        self, products: Iterable[ProductLike], *, idempotency_key: Optional[str] = None
    ) -> ProductBulkUpsertResult:
        """Create or update many products (``POST /v1/products:bulk-upsert``).

        The input is validated locally, de-duplicated by ``external_id`` (later
        duplicates are reported as rejected, like the server does), and split
        into requests that fit the server's body limit. Counts are summed across
        requests. If a request fails, the raised :class:`~graphrec_sdk.APIError`
        carries ``partial_result`` with the totals applied so far.
        """

        chunks, duplicates = _plan_bulk(
            products, max_bytes=self._client.max_body_bytes, max_items=self._client.max_batch_items
        )
        results: List[ProductBulkUpsertResult] = []
        for index, chunk in enumerate(chunks):
            try:
                result = self._client.request(
                    "products.bulk_upsert",
                    json={"products": chunk},
                    idempotency_key=_chunk_key(idempotency_key, index, len(chunks)),
                    cast_to=ProductBulkUpsertResult,
                )
            except APIError as exc:
                exc.partial_result = _combine(results, duplicates)  # type: ignore[attr-defined]
                raise
            results.append(cast(ProductBulkUpsertResult, result))
        return _combine(results, duplicates)

    def list(self) -> ProductList:
        """All products, newest first (``GET /v1/products``)."""

        return cast(ProductList, self._client.request("products.list", cast_to=ProductList))

    def get(self, external_id: str) -> Product:
        """``GET /v1/products/{external_id}``. Raises :class:`~graphrec_sdk.NotFoundError`."""

        return cast(
            Product,
            self._client.request(
                "products.get", path_params={"external_id": external_id}, cast_to=Product
            ),
        )

    def upsert(self, product: ProductLike) -> Product:
        """Create or fully replace one product (``PUT /v1/products/{external_id}``)."""

        item = coerce_input(ProductInput, product)
        return cast(
            Product,
            self._client.request(
                "products.upsert",
                path_params={"external_id": item.external_id},
                json=item,
                cast_to=Product,
            ),
        )

    def update(
        self,
        external_id: str,
        *,
        title: str = OMIT,
        description: str = OMIT,
        price: Union[Decimal, float, int, str] = OMIT,
        category: str = OMIT,
        is_active: bool = OMIT,
        availability_status: str = OMIT,
        metadata: Mapping[str, Any] = OMIT,
    ) -> Product:
        """Change selected fields of an existing product (``PATCH /v1/products/{external_id}``).

        The server's PATCH expects a complete product, so the SDK reads the
        current product, applies your changes and sends the result (two
        requests, not atomic). ``metadata`` replaces the whole metadata object.
        """

        changes = _changes(
            title=title,
            description=description,
            price=price,
            category=category,
            is_active=is_active,
            availability_status=availability_status,
            metadata=metadata,
        )
        body = _update_input(self.get(external_id), changes)
        return cast(
            Product,
            self._client.request(
                "products.update",
                path_params={"external_id": external_id},
                json=body,
                cast_to=Product,
            ),
        )

    def disable(self, external_id: str) -> Product:
        """Stop recommending a product (``POST /v1/products/{external_id}:disable``)."""

        return cast(
            Product,
            self._client.request(
                "products.disable", path_params={"external_id": external_id}, cast_to=Product
            ),
        )


class AsyncProducts(AsyncResource):
    async def bulk_upsert(
        self, products: Iterable[ProductLike], *, idempotency_key: Optional[str] = None
    ) -> ProductBulkUpsertResult:
        """Async variant of :meth:`Products.bulk_upsert`."""

        chunks, duplicates = _plan_bulk(
            products, max_bytes=self._client.max_body_bytes, max_items=self._client.max_batch_items
        )
        results: List[ProductBulkUpsertResult] = []
        for index, chunk in enumerate(chunks):
            try:
                result = await self._client.request(
                    "products.bulk_upsert",
                    json={"products": chunk},
                    idempotency_key=_chunk_key(idempotency_key, index, len(chunks)),
                    cast_to=ProductBulkUpsertResult,
                )
            except APIError as exc:
                exc.partial_result = _combine(results, duplicates)  # type: ignore[attr-defined]
                raise
            results.append(cast(ProductBulkUpsertResult, result))
        return _combine(results, duplicates)

    async def list(self) -> ProductList:
        """Async variant of :meth:`Products.list`."""

        return cast(ProductList, await self._client.request("products.list", cast_to=ProductList))

    async def get(self, external_id: str) -> Product:
        """Async variant of :meth:`Products.get`."""

        return cast(
            Product,
            await self._client.request(
                "products.get", path_params={"external_id": external_id}, cast_to=Product
            ),
        )

    async def upsert(self, product: ProductLike) -> Product:
        """Async variant of :meth:`Products.upsert`."""

        item = coerce_input(ProductInput, product)
        return cast(
            Product,
            await self._client.request(
                "products.upsert",
                path_params={"external_id": item.external_id},
                json=item,
                cast_to=Product,
            ),
        )

    async def update(
        self,
        external_id: str,
        *,
        title: str = OMIT,
        description: str = OMIT,
        price: Union[Decimal, float, int, str] = OMIT,
        category: str = OMIT,
        is_active: bool = OMIT,
        availability_status: str = OMIT,
        metadata: Mapping[str, Any] = OMIT,
    ) -> Product:
        """Async variant of :meth:`Products.update`."""

        changes = _changes(
            title=title,
            description=description,
            price=price,
            category=category,
            is_active=is_active,
            availability_status=availability_status,
            metadata=metadata,
        )
        body = _update_input(await self.get(external_id), changes)
        return cast(
            Product,
            await self._client.request(
                "products.update",
                path_params={"external_id": external_id},
                json=body,
                cast_to=Product,
            ),
        )

    async def disable(self, external_id: str) -> Product:
        """Async variant of :meth:`Products.disable`."""

        return cast(
            Product,
            await self._client.request(
                "products.disable", path_params={"external_id": external_id}, cast_to=Product
            ),
        )
