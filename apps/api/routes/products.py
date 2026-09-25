from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.catalog.service import CatalogService
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.schemas.products import (
    ProductBulkUpsertRequest,
    ProductBulkUpsertResponse,
    ProductListResponse,
    ProductResource,
    ProductUpsert,
)

router = APIRouter(tags=["catalog"])


@router.post("/v1/products:bulk-upsert", response_model=ProductBulkUpsertResponse)
def bulk_upsert_products(
    payload: ProductBulkUpsertRequest,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductBulkUpsertResponse:
    principal.require_scope("catalog:write")
    service = CatalogService(db)
    return service.bulk_upsert(principal.tenant_id, payload)


@router.get("/v1/products", response_model=ProductListResponse)
def list_products(
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ids: str | None = Query(
        default=None,
        max_length=8000,
        description="Comma-separated external ids (at most 200) to fetch directly",
    ),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    """List products newest first. ``total`` counts every match, not just this page."""
    principal.require_scope("catalog:read")
    external_ids: list[str] | None = None
    if ids is not None:
        external_ids = list(dict.fromkeys(value.strip() for value in ids.split(",") if value.strip()))
        if len(external_ids) > 200:
            raise ApiError(422, "validation_failed", "ids accepts at most 200 external ids")
    service = CatalogService(db)
    items = service.list_products(
        principal.tenant_id, limit=limit, offset=offset, external_ids=external_ids
    )
    total = service.count_products(principal.tenant_id, external_ids)
    return ProductListResponse(items=items, total=total)


@router.get("/v1/products/{external_id}", response_model=ProductResource)
def get_product(
    external_id: str,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductResource:
    principal.require_scope("catalog:read")
    service = CatalogService(db)
    return service.get_product(principal.tenant_id, external_id)


@router.put("/v1/products/{external_id}", response_model=ProductResource)
def put_product(
    external_id: str,
    payload: ProductUpsert,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductResource:
    principal.require_scope("catalog:write")
    service = CatalogService(db)
    return service.update_product(principal.tenant_id, external_id, payload)


@router.patch("/v1/products/{external_id}", response_model=ProductResource)
def patch_product(
    external_id: str,
    payload: ProductUpsert,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductResource:
    principal.require_scope("catalog:write")
    service = CatalogService(db)
    return service.update_product(principal.tenant_id, external_id, payload)


@router.post("/v1/products/{external_id}:disable", response_model=ProductResource)
def disable_product(
    external_id: str,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductResource:
    principal.require_scope("catalog:write")
    service = CatalogService(db)
    return service.disable_product(principal.tenant_id, external_id)
