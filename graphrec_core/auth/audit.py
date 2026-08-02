from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from graphrec_core.database.models import SecurityEvent
from graphrec_core.database.session import SessionLocal
from graphrec_core.settings import get_settings


def protected_auth_hash(value: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.audit_hash_secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def record_public_login_denial(
    *, event_type: str, correlation_id: UUID, source: str, detail: dict[str, Any]
) -> None:
    with SessionLocal() as session:
        try:
            session.add(
                SecurityEvent(
                    id=uuid4(),
                    tenant_id=None,
                    event_type=event_type,
                    severity="warning",
                    source_hash=protected_auth_hash(source),
                    sanitized_detail={"correlation_id": str(correlation_id), **detail},
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        except SQLAlchemyError:
            session.rollback()
