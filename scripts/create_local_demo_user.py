from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from graphrec_core.auth.passwords import hash_password
from graphrec_core.database.models import AuditLog, TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.registration.service import RegistrationService
from graphrec_core.schemas.auth import LoginRequest
from graphrec_core.schemas.registration import TenantRegistrationRequest
from graphrec_core.settings import get_settings


def main() -> None:
    tenant_name = os.environ.get("DEMO_TENANT_NAME", "GraphRec Local Demo")
    registration_email = os.environ.get(
        "DEMO_REGISTRATION_EMAIL", "owner-demo@example.org"
    )
    login_email = os.environ.get("DEMO_LOGIN_EMAIL", "demo-admin@example.org")
    login_password = os.environ.get("DEMO_LOGIN_PASSWORD")
    if not login_password:
        raise SystemExit("DEMO_LOGIN_PASSWORD is required")

    registration = TenantRegistrationRequest(
        name=tenant_name,
        admin_email=registration_email,
    )
    login = LoginRequest(email=login_email, password=login_password)
    correlation_id = uuid4()
    settings = get_settings()

    with SessionLocal() as session:
        result = RegistrationService(session, settings).register(
            registration,
            idempotency_key="graphrec-local-demo-tenant-v1",
            correlation_id=correlation_id,
            source="local-demo-bootstrap",
        )
        tenant_id = result.response.id

        with session.begin():
            set_local_tenant(session, tenant_id)
            existing = session.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.email == login.email,
                )
            )
            if existing is not None:
                print(f"Demo login already exists for {login.email}")
                return

            now = datetime.now(timezone.utc)
            user_id = uuid4()
            session.add_all(
                [
                    TenantUser(
                        id=user_id,
                        tenant_id=tenant_id,
                        email=login.email,
                        display_name="Local Demo Administrator",
                        credential_digest=hash_password(login.password),
                        role="tenant_administrator",
                        status="active",
                        created_at=now,
                        last_authenticated_at=None,
                    ),
                    AuditLog(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        actor_type="system_process",
                        actor_reference=None,
                        action_type="local_demo_user_bootstrap",
                        resource_type="tenant_user",
                        resource_reference=user_id,
                        outcome="succeeded",
                        correlation_reference=correlation_id,
                        redacted_details={"role": "tenant_administrator"},
                        occurred_at=now,
                    ),
                ]
            )
        print(f"Created local demo login for {login.email}")


if __name__ == "__main__":
    main()
