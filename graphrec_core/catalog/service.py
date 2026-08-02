from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import Product, UsageEvent
from graphrec_core.errors import ApiError
from graphrec_core.schemas.products import (
    ProductBulkFailure,
    ProductBulkUpsertRequest,
    ProductBulkUpsertResponse,
    ProductResource,
    ProductUpsert,
)


class CatalogService:
    def __init__(self, db: Session):
        self.db = db

    def bulk_upsert(
        self, tenant_id: UUID, payload: ProductBulkUpsertRequest
    ) -> ProductBulkUpsertResponse:
        now = datetime.now(timezone.utc)
        created_count = 0
        updated_count = 0
        skipped_count = 0
        rejected_count = 0
        failures: list[ProductBulkFailure] = []

        seen_ids: set[str] = set()

        for item in payload.products:
            if item.external_id in seen_ids:
                rejected_count += 1
                failures.append(
                    ProductBulkFailure(
                        external_id=item.external_id,
                        reason="Duplicate item external_id within batch",
                    )
                )
                continue
            seen_ids.add(item.external_id)

            existing = self.db.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id, Product.external_id == item.external_id
                )
            ).scalar_one_or_none()

            if existing:
                existing.title = item.title
                existing.description = item.description
                existing.price = item.price
                existing.category = item.category
                existing.is_active = item.is_active
                existing.availability_status = item.availability_status
                existing.metadata_json = item.metadata
                existing.updated_at = now
                updated_count += 1
            else:
                product = Product(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    external_id=item.external_id,
                    title=item.title,
                    description=item.description,
                    price=item.price,
                    category=item.category,
                    is_active=item.is_active,
                    availability_status=item.availability_status,
                    metadata_json=item.metadata,
                    created_at=now,
                    updated_at=now,
                )
                self.db.add(product)
                created_count += 1

        accepted_count = created_count + updated_count

        if created_count > 0:
            usage_record = UsageEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                usage_type="stored_products",
                quantity=Decimal(created_count),
                source_id=f"bulk-upsert-{now.timestamp()}",
                idempotency_key=str(uuid4()),
                occurred_at=now,
            )
            self.db.add(usage_record)

        self.db.commit()

        return ProductBulkUpsertResponse(
            accepted_count=accepted_count,
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            rejected_count=rejected_count,
            failures=failures,
        )

    def list_products(self, tenant_id: UUID) -> list[ProductResource]:
        products = (
            self.db.execute(
                select(Product)
                .where(Product.tenant_id == tenant_id)
                .order_by(Product.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [
            ProductResource(
                id=p.id,
                external_id=p.external_id,
                title=p.title,
                description=p.description,
                price=p.price,
                category=p.category,
                is_active=p.is_active,
                availability_status=p.availability_status,
                metadata=p.metadata_json or {},
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in products
        ]

    def disable_product(self, tenant_id: UUID, external_id: str) -> ProductResource:
        product = self.db.execute(
            select(Product).where(
                Product.tenant_id == tenant_id, Product.external_id == external_id
            )
        ).scalar_one_or_none()

        if not product:
            raise ApiError(404, "resource_not_found", f"Product '{external_id}' not found.")

        product.is_active = False
        product.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        return ProductResource(
            id=product.id,
            external_id=product.external_id,
            title=product.title,
            description=product.description,
            price=product.price,
            category=product.category,
            is_active=product.is_active,
            availability_status=product.availability_status,
            metadata=product.metadata_json or {},
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

    def get_product(self, tenant_id: UUID, external_id: str) -> ProductResource:
        product = self.db.execute(
            select(Product).where(
                Product.tenant_id == tenant_id, Product.external_id == external_id
            )
        ).scalar_one_or_none()

        if not product:
            raise ApiError(404, "resource_not_found", f"Product '{external_id}' not found.")

        return ProductResource(
            id=product.id,
            external_id=product.external_id,
            title=product.title,
            description=product.description,
            price=product.price,
            category=product.category,
            is_active=product.is_active,
            availability_status=product.availability_status,
            metadata=product.metadata_json or {},
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

    def update_product(
        self, tenant_id: UUID, external_id: str, payload: ProductUpsert
    ) -> ProductResource:
        now = datetime.now(timezone.utc)
        product = self.db.execute(
            select(Product).where(
                Product.tenant_id == tenant_id, Product.external_id == external_id
            )
        ).scalar_one_or_none()

        if not product:
            product = Product(
                id=uuid4(),
                tenant_id=tenant_id,
                external_id=external_id,
                title=payload.title,
                description=payload.description,
                price=payload.price,
                category=payload.category,
                is_active=payload.is_active,
                availability_status=payload.availability_status,
                metadata_json=payload.metadata,
                created_at=now,
                updated_at=now,
            )
            self.db.add(product)
        else:
            product.title = payload.title
            if payload.description is not None:
                product.description = payload.description
            product.price = payload.price
            if payload.category is not None:
                product.category = payload.category
            product.is_active = payload.is_active
            product.availability_status = payload.availability_status
            if payload.metadata:
                product.metadata_json = payload.metadata
            product.updated_at = now

        self.db.commit()
        return ProductResource(
            id=product.id,
            external_id=product.external_id,
            title=product.title,
            description=product.description,
            price=product.price,
            category=product.category,
            is_active=product.is_active,
            availability_status=product.availability_status,
            metadata=product.metadata_json or {},
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

