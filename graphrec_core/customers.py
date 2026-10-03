"""Register external shopper identities within an authenticated tenant."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from graphrec_core.database.models import Customer


def ensure_customers(db: Session, tenant_id: UUID, external_ids: set[str]) -> None:
    if not external_ids:
        return
    now = datetime.now(timezone.utc)
    db.execute(insert(Customer).values([
        {"id": uuid4(), "tenant_id": tenant_id, "external_id": external_id, "created_at": now}
        for external_id in sorted(external_ids)
    ]).on_conflict_do_nothing(index_elements=["tenant_id", "external_id"]))
