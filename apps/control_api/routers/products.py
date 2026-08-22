"""The catalogue — every route developer-only.

All four `/products*` screens are declared `[DEV]` in the prototype's route
table (dc.html L645-646), and L1256 states an administrator has "No catalog
access and no event submission." **Read included.** That is unusual — read is
open to both roles on `/users` — and it is deliberate here: the catalogue is the
tenant's commercial data, and the SRS separates who runs the business from who
integrates with it.

Three write verbs, and the difference between them is the whole of D9 (ADR
0012). `POST` refuses a duplicate so the Add product form can render L1604's
conflict; `PUT` is idempotent because integrations retry; `PATCH` changes named
fields because the detail form is pre-filled and a blank input there means
"unchanged", not "clear it".

No handler filters by `tenant_id`. The principal's session is bound, so a
foreign external id returns no row and becomes a 404 that does not name what was
not found (gate 4).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from apps.control_api.deps import TenantPrincipal, require_role
from apps.control_api.schemas import (
    CreateProductRequest,
    DisableProductRequest,
    ProductBody,
    ProductListResponse,
    ProductResponse,
)
from graphrec.catalog.eligibility import exclusion_reason
from graphrec.common.enums import Availability, TenantRole
from graphrec.common.error_copy import ERROR_COPY
from graphrec.db.models import Product
from graphrec.domain.catalog import CatalogService, ProductFilter, ProductWrite

router = APIRouter(prefix="/products", tags=["catalog"])

#: Gate 3, on every route in this module including the reads.
RequireDeveloper = Annotated[TenantPrincipal, Depends(require_role(TenantRole.TENANT_DEVELOPER))]


def _service() -> CatalogService:
    return CatalogService()


Service = Annotated[CatalogService, Depends(_service)]


def _render(product: Product) -> ProductResponse:
    """No `product_id` and no `tenant_id`.

    The external identifier is the product's name on the wire — the prototype
    addresses every product by it (L1301) and calls it "the idempotency key for
    later updates" (L1320). Publishing the internal key as well would give
    integrations a second identifier to key on, and the two would be used
    interchangeably until one of them was needed to be stable.
    """
    code = product.ineligibility
    return ProductResponse(
        external_id=product.external_product_id,
        title=product.title,
        category=product.category.external_category_id if product.category else None,
        brand=product.brand,
        price=product.price,
        active=product.is_active,
        availability=Availability(product.availability),
        description=product.description,
        attributes=product.attributes or {},
        eligible=code is None,
        ineligibility=code,
        exclusion_reason=exclusion_reason(code),
        can_disable=product.is_active,
        # The server's reason for the disabled control, so the console renders
        # it rather than deciding for itself (L1332).
        blocked_reason=None if product.is_active else ERROR_COPY["product_already_disabled"],
        disabled_reason=product.disabled_reason,
        disabled_at=product.disabled_at,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _write(body: ProductBody) -> ProductWrite:
    """Turn the request into a write, preserving what the caller left out.

    `exclude_unset` is the whole mechanism: a field the caller did not send is
    absent from the mapping and stays `UNSET`, while a field sent as `null` is
    present and clears the column. Without it, `PATCH {"title": "..."}` would
    also blank the brand, the price and the description, and nothing would
    error.
    """
    sent = body.model_dump(exclude_unset=True)
    return ProductWrite(
        **{
            target: sent[field]
            for field, target in (
                ("title", "title"),
                ("category", "category"),
                ("brand", "brand"),
                ("price", "price"),
                ("availability", "availability"),
                ("description", "description"),
                ("active", "is_active"),
                ("attributes", "attributes"),
            )
            if field in sent
        }
    )


@router.get("", response_model=ProductListResponse, summary="The tenant's catalogue")
async def list_products(
    principal: RequireDeveloper,
    service: Service,
    category: Annotated[str | None, Query(max_length=120)] = None,
    availability: Annotated[Availability | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200, alias="q")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductListResponse:
    """The catalogue table's three filters (L1314) and D10's paging.

    `q` is the query name the prototype's search control uses; `search` is its
    Python name. Removed products are never listed — they are not in any view
    the console draws.
    """
    page = await service.list_products(
        principal.session,
        filters=ProductFilter(
            category=category,
            availability=availability.value if availability else None,
            search=search,
        ),
        limit=limit,
        offset=offset,
    )
    return ProductListResponse(
        products=[_render(product) for product in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product",
)
async def create_product(
    body: CreateProductRequest, principal: RequireDeveloper, service: Service
) -> ProductResponse:
    """May refuse with 409 `product_already_exists` or 429 `product_quota_exhausted`."""
    product = await service.create(
        principal.session,
        tenant_id=principal.tenant_id,
        external_product_id=body.external_id,
        write=_write(body),
    )
    return _render(product)


@router.get("/{external_id}", response_model=ProductResponse, summary="One product")
async def get_product(
    external_id: str, principal: RequireDeveloper, service: Service
) -> ProductResponse:
    product = await service.get(principal.session, external_product_id=external_id)
    return _render(product)


@router.put("/{external_id}", response_model=ProductResponse, summary="Create or replace")
async def upsert_product(
    external_id: str,
    body: ProductBody,
    principal: RequireDeveloper,
    service: Service,
    response: Response,
) -> ProductResponse:
    """Idempotent by the external identifier, which is the idempotency key (L1320).

    `201` the first time and `200` afterwards: a retried `PUT` must be able to
    tell whether it was the call that created the product, and the status line
    is the only place that fits without inventing a body field.
    """
    product, created = await service.upsert(
        principal.session,
        tenant_id=principal.tenant_id,
        external_product_id=external_id,
        write=_write(body),
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _render(product)


@router.patch("/{external_id}", response_model=ProductResponse, summary="Update a product")
async def patch_product(
    external_id: str, body: ProductBody, principal: RequireDeveloper, service: Service
) -> ProductResponse:
    """The detail page's Update product form (L1337).

    Every field there is pre-filled, so a field the console sends unchanged is
    still sent; a field it omits was never on the form. `PATCH` is what makes
    that distinction expressible — `PUT` would blank the description, which the
    detail form does not carry.
    """
    product = await service.patch(
        principal.session,
        tenant_id=principal.tenant_id,
        external_product_id=external_id,
        write=_write(body),
    )
    return _render(product)


@router.post("/{external_id}:disable", response_model=ProductResponse, summary="Disable a product")
async def disable_product(
    external_id: str,
    body: DisableProductRequest,
    principal: RequireDeveloper,
    service: Service,
) -> ProductResponse:
    """Gate 5. 409 `product_already_disabled` when it is already inactive.

    "A disabled product stops being returned by serving immediately. The record
    is retained and can be re-enabled by an update." (L1339-L1340) — so this is
    not a delete, and there is no `DELETE` grant on `products` that would let it
    become one.
    """
    product = await service.disable(
        principal.session, external_product_id=external_id, reason=body.reason
    )
    return _render(product)
