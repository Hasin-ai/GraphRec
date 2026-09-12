from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.catalog.service import CatalogService
from graphrec_core.database.session import get_db
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
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    principal.require_scope("catalog:read")
    service = CatalogService(db)
    items = service.list_products(principal.tenant_id)
    return ProductListResponse(items=items, total=len(items))


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
