from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.database.models import (
    AuditLog,
    PricingPlan,
    RegistrationRequest,
    SecurityEvent,
    Tenant,
    TenantResourceQuota,
    TenantSubscription,
    TenantUser,
)
from graphrec_core.auth.setup_tokens import issue_setup_token
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.registration import (
    TenantRegistrationRequest,
    TenantRegistrationResponse,
)
from graphrec_core.settings import Settings

NEXT_STEP = "Complete account setup with the one-time setup_token before it expires"


@dataclass(frozen=True)
class RegistrationResult:
    response: TenantRegistrationResponse
    replayed: bool


@dataclass(frozen=True)
class _StoredRegistration:
    tenant_id: UUID
    request_hash: str
    response_body: dict


class RegistrationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def register(
        self,
        request: TenantRegistrationRequest,
        *,
        idempotency_key: str,
        correlation_id: UUID,
        source: str,
    ) -> RegistrationResult:
        key_hash = self._plain_hash(idempotency_key)
        request_hash = self._request_hash(request)

        try:
            existing_key = self._registration_by_key(key_hash)
            if existing_key is not None:
                if existing_key.request_hash != request_hash:
                    self._add_security_event(
                        tenant_id=existing_key.tenant_id,
                        event_type="registration_idempotency_conflict",
                        severity="warning",
                        source=source,
                        detail={"correlation_id": str(correlation_id)},
                    )
                    self.session.commit()
                    raise ApiError(
                        409,
                        "idempotency_conflict",
                        "The idempotency key was already used for a different registration request",
                    )
                response = TenantRegistrationResponse.model_validate(existing_key.response_body)
                self._add_security_event(
                    tenant_id=existing_key.tenant_id,
                    event_type="registration_replayed",
                    severity="info",
                    source=source,
                    detail={"correlation_id": str(correlation_id)},
                )
                self.session.commit()
                return RegistrationResult(response=response, replayed=True)

            existing_request = self._registration_by_request(request_hash)
            if existing_request is not None:
                self._add_security_event(
                    tenant_id=existing_request.tenant_id,
                    event_type="registration_duplicate_denied",
                    severity="warning",
                    source=source,
                    detail={
                        "correlation_id": str(correlation_id),
                        "administrator_email_hash": self._protected_hash(request.admin_email),
                    },
                )
                self.session.commit()
                raise self._duplicate_error()

            # UC-01: an administrator email that already belongs to a tenant user
            # is a duplicate registration. Without this check an anonymous caller
            # could register another tenant with someone's email and make their
            # sign-in ambiguous (login resolves users by email across tenants).
            existing_user = self.session.execute(
                text("SELECT 1 FROM resolve_login_identities(:email) LIMIT 1"),
                {"email": request.admin_email},
            ).first()
            # D10: tenant names are unique case-insensitively (SRS gap: the SRS
            # only says duplicate registrations are rejected).
            name_taken = bool(self.session.scalar(
                text("SELECT public.tenant_name_in_use(:name)"), {"name": request.name}))
            if existing_user is not None or name_taken:
                self._add_security_event(
                    tenant_id=None,
                    event_type="registration_duplicate_denied",
                    severity="warning",
                    source=source,
                    detail={
                        "correlation_id": str(correlation_id),
                        "administrator_email_hash": self._protected_hash(request.admin_email),
                    },
                )
                self.session.commit()
                raise self._duplicate_error(name_taken=name_taken, email_taken=existing_user is not None)

            return self._create_registration(
                request,
                key_hash=key_hash,
                request_hash=request_hash,
                correlation_id=correlation_id,
                source=source,
            )
        except ApiError:
            raise
        except IntegrityError:
            self.session.rollback()
            return self._resolve_concurrent_result(
                key_hash=key_hash,
                request_hash=request_hash,
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ApiError(
                503,
                "service_unavailable",
                "Registration is temporarily unavailable",
                retryable=True,
                retry_after_seconds=5,
            ) from exc

    def record_rate_limit_denial(
        self, *, correlation_id: UUID, source: str, retry_after_seconds: int
    ) -> None:
        try:
            self._add_security_event(
                tenant_id=None,
                event_type="registration_rate_limited",
                severity="warning",
                source=source,
                detail={
                    "correlation_id": str(correlation_id),
                    "retry_after_seconds": retry_after_seconds,
                },
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

    def _create_registration(
        self,
        request: TenantRegistrationRequest,
        *,
        key_hash: str,
        request_hash: str,
        correlation_id: UUID,
        source: str,
    ) -> RegistrationResult:
        now = datetime.now(timezone.utc)
        tenant_id = uuid4()
        user_id = uuid4()
        plan = self.session.scalar(
            select(PricingPlan).where(PricingPlan.code == "free", PricingPlan.is_active.is_(True))
        )
        if plan is None:
            raise ApiError(
                503,
                "service_unavailable",
                "Registration is temporarily unavailable",
                retryable=True,
                retry_after_seconds=5,
            )

        set_local_tenant(self.session, tenant_id)
        tenant = Tenant(
            id=tenant_id,
            slug=self._tenant_slug(request.name, tenant_id),
            name=request.name,
            status="active",
            created_at=now,
        )
        self.session.add(tenant)
        self.session.flush()
        response = TenantRegistrationResponse(
            id=tenant_id,
            name=request.name,
            status="active",
            created_at=now,
            administrator_email=request.admin_email,
            next_step=NEXT_STEP,
        )
        self.session.add_all(
            [
                TenantUser(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=request.admin_email,
                    display_name=request.admin_email.split("@", 1)[0],
                    credential_digest=None,
                    role="tenant_administrator",
                    status="invited",
                    created_at=now,
                    last_authenticated_at=None,
                ),
                TenantSubscription(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    plan_id=plan.id,
                    status="active",
                    period_start=now,
                    period_end=now + timedelta(days=30),
                    project_defaults=True,
                    created_at=now,
                ),
                TenantResourceQuota(
                    tenant_id=tenant_id,
                    limits=dict(plan.limits),
                    overrides={},
                    created_at=now,
                ),
                AuditLog(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    actor_type="prospective_tenant_administrator",
                    actor_reference=None,
                    action_type="tenant_registration",
                    resource_type="tenant",
                    resource_reference=tenant_id,
                    outcome="succeeded",
                    correlation_reference=correlation_id,
                    redacted_details={
                        "administrator_email_hash": self._protected_hash(request.admin_email),
                        "account_status": "invited",
                    },
                    occurred_at=now,
                ),
                RegistrationRequest(
                    id=uuid4(),
                    idempotency_key_hash=key_hash,
                    request_hash=request_hash,
                    tenant_id=tenant_id,
                    response_body=response.model_dump(mode="json"),
                    created_at=now,
                ),
                SecurityEvent(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    event_type="registration_succeeded",
                    severity="info",
                    source_hash=self._protected_hash(source),
                    sanitized_detail={
                        "correlation_id": str(correlation_id),
                        "administrator_email_hash": self._protected_hash(request.admin_email),
                    },
                    occurred_at=now,
                ),
            ]
        )
        # The invited administrator must exist before a setup token can reference it.
        self.session.flush()
        setup_token, setup_token_expires_at = issue_setup_token(
            self.session,
            tenant_id=tenant_id,
            user_id=user_id,
            ttl_seconds=self.settings.account_setup_token_ttl_seconds,
            now=now,
        )
        self.session.commit()
        # The replay body stored above never contains the token; only this first
        # response does, and the database keeps nothing but its hash.
        return RegistrationResult(
            response=response.model_copy(
                update={
                    "setup_token": setup_token,
                    "setup_token_expires_at": setup_token_expires_at,
                }
            ),
            replayed=False,
        )

    def _resolve_concurrent_result(
        self, *, key_hash: str, request_hash: str
    ) -> RegistrationResult:
        existing_key = self._registration_by_key(key_hash)
        if existing_key is not None and existing_key.request_hash == request_hash:
            return RegistrationResult(
                response=TenantRegistrationResponse.model_validate(existing_key.response_body),
                replayed=True,
            )
        if existing_key is not None:
            raise ApiError(
                409,
                "idempotency_conflict",
                "The idempotency key was already used for a different registration request",
            )
        existing_request = self._registration_by_request(request_hash)
        if existing_request is not None:
            raise self._duplicate_error()
        raise ApiError(
            503,
            "service_unavailable",
            "Registration is temporarily unavailable",
            retryable=True,
            retry_after_seconds=5,
        )

    def _add_security_event(
        self,
        *,
        tenant_id: UUID | None,
        event_type: str,
        severity: str,
        source: str,
        detail: dict[str, Any],
    ) -> None:
        self.session.add(
            SecurityEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                event_type=event_type,
                severity=severity,
                source_hash=self._protected_hash(source),
                sanitized_detail=detail,
                occurred_at=datetime.now(timezone.utc),
            )
        )

    # A-17: registration_requests is tenant-scoped (RLS) and the runtime role
    # cannot read it directly; these SECURITY DEFINER lookups answer only the
    # hash-keyed questions registration needs, before any tenant is known.
    def _registration_by_key(self, key_hash: str) -> "_StoredRegistration | None":
        row = self.session.execute(text("SELECT * FROM public.registration_by_idempotency_key(:h)"),
                                   {"h": key_hash}).mappings().one_or_none()
        return _StoredRegistration(**row) if row else None

    def _registration_by_request(self, request_hash: str) -> "_StoredRegistration | None":
        row = self.session.execute(text("SELECT * FROM public.registration_by_request_hash(:h)"),
                                   {"h": request_hash}).mappings().one_or_none()
        return _StoredRegistration(**row) if row else None

    def _request_hash(self, request: TenantRegistrationRequest) -> str:
        canonical = json.dumps(
            {"admin_email": request.admin_email, "name": request.name},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return self._plain_hash(canonical)

    def _protected_hash(self, value: str) -> str:
        return hmac.new(
            self.settings.audit_hash_secret.encode(), value.encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _plain_hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _tenant_slug(name: str, tenant_id: UUID) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tenant"
        return f"{base[:48]}-{tenant_id.hex[:8]}"

    @staticmethod
    def _duplicate_error(name_taken: bool = True, email_taken: bool = True) -> ApiError:
        # D15: say which field needs correcting (UC-01 "correction guidance")
        # without echoing the submitted values back.
        fields = []
        if name_taken:
            fields.append({"field": "name", "message": "This business name is already registered. Choose a different name."})
        if email_taken:
            fields.append({"field": "admin_email", "message": "This email cannot be used to register a new tenant. If you already have an account, sign in, or ask your operator for a new setup link."})
        return ApiError(
            409,
            "duplicate_resource",
            "This registration cannot be completed with the supplied information",
            details={"fields": fields},
        )
