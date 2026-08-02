from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.api_keys.crypto import api_key_digest, generate_api_key
from graphrec_core.api_keys.scopes import ADMIN_DELEGATED_SCOPES, DEVELOPER_DELEGATED_SCOPES
from graphrec_core.auth.principal import AuthenticatedPrincipal
from graphrec_core.database.models import ApiKey, AuditLog
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.api_keys import (
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeyRotateRequest,
    ApiKeySecretResponse,
)
from graphrec_core.settings import Settings

class ApiKeyService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def list_keys(
        self, principal: AuthenticatedPrincipal, *, correlation_id: UUID
    ) -> ApiKeyListResponse:
        try:
            rows = self.session.scalars(
                select(ApiKey)
                .where(ApiKey.tenant_id == principal.tenant_id)
                .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            ).all()
            response = ApiKeyListResponse(items=[self._public(row) for row in rows])
            self._audit(principal, correlation_id, "api_keys_listed", None, {"count": len(rows)})
            self.session.commit()
            return response
        except ApiError:
            self.session.rollback()
            raise
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            self.session.rollback()
            raise self._unavailable() from exc

    def get_key(
        self, principal: AuthenticatedPrincipal, key_id: UUID, *, correlation_id: UUID
    ) -> ApiKeyResponse:
        try:
            row = self._owned(key_id)
            self._audit(principal, correlation_id, "api_key_read", row.id, {"prefix": row.key_prefix})
            response = self._public(row)
            self.session.commit()
            return response
        except ApiError as exc:
            self._audit_failure(principal, correlation_id, "api_key_read_failed", exc.code)
            raise
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            self.session.rollback()
            raise self._unavailable() from exc

    def create_key(
        self,
        principal: AuthenticatedPrincipal,
        request: ApiKeyCreateRequest,
        *,
        correlation_id: UUID,
    ) -> ApiKeySecretResponse:
        now = datetime.now(timezone.utc)
        try:
            self._validate_expiry(request.expires_at, now)
            self._validate_delegation(principal, request.scopes)
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
                {"tenant_id": str(principal.tenant_id)},
            )
            duplicate = self.session.scalar(
                select(ApiKey.id).where(
                    ApiKey.tenant_id == principal.tenant_id,
                    ApiKey.name == request.name,
                )
            )
            if duplicate is not None:
                raise ApiError(409, "duplicate_resource", "An API key with this name already exists")
            active_count = self.session.scalar(
                select(func.count()).select_from(ApiKey).where(
                    ApiKey.tenant_id == principal.tenant_id,
                    ApiKey.revoked_at.is_(None),
                    or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
                )
            )
            if int(active_count or 0) >= self.settings.max_active_api_keys_per_tenant:
                raise ApiError(429, "quota_exceeded", "The active API-key quota is exhausted")

            secret, prefix = generate_api_key()
            row = ApiKey(
                id=uuid4(),
                tenant_id=principal.tenant_id,
                name=request.name,
                key_prefix=prefix,
                key_hash=api_key_digest(secret, self.settings.api_key_hmac_pepper),
                hash_version=self.settings.api_key_hash_version,
                scopes=list(request.scopes),
                expires_at=request.expires_at,
                created_at=now,
                last_used_at=None,
                revoked_at=None,
                previous_key_prefix=None,
                previous_key_hash=None,
                previous_hash_version=None,
                grace_expires_at=None,
            )
            self.session.add(row)
            self._audit(
                principal,
                correlation_id,
                "api_key_created",
                row.id,
                {"prefix": prefix, "scopes": list(request.scopes), "expires_at": self._iso(request.expires_at)},
            )
            response = self._secret(row, secret)
            self.session.commit()
            return response
        except ApiError as exc:
            self._audit_failure(principal, correlation_id, "api_key_create_failed", exc.code)
            raise
        except IntegrityError as exc:
            self._audit_failure(
                principal, correlation_id, "api_key_create_failed", "duplicate_resource"
            )
            raise ApiError(409, "duplicate_resource", "An API key with this name already exists") from exc
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            self.session.rollback()
            raise self._unavailable() from exc

    def rotate_key(
        self,
        principal: AuthenticatedPrincipal,
        key_id: UUID,
        request: ApiKeyRotateRequest,
        *,
        correlation_id: UUID,
    ) -> ApiKeySecretResponse:
        now = datetime.now(timezone.utc)
        try:
            row = self.session.scalar(
                select(ApiKey).where(ApiKey.id == key_id).with_for_update()
            )
            if row is None:
                raise self._not_found()
            if row.revoked_at is not None or (row.expires_at is not None and row.expires_at <= now):
                raise ApiError(409, "state_conflict", "The API key cannot be rotated in its current state")
            if row.grace_expires_at is not None and row.grace_expires_at > now:
                raise ApiError(409, "state_conflict", "An API-key rotation grace period is already active")

            old_prefix = row.key_prefix
            secret, prefix = generate_api_key()
            if request.grace_period_seconds > 0:
                row.previous_key_prefix = row.key_prefix
                row.previous_key_hash = row.key_hash
                row.previous_hash_version = row.hash_version
                row.grace_expires_at = now + timedelta(seconds=request.grace_period_seconds)
            else:
                row.previous_key_prefix = None
                row.previous_key_hash = None
                row.previous_hash_version = None
                row.grace_expires_at = None
            row.key_prefix = prefix
            row.key_hash = api_key_digest(secret, self.settings.api_key_hmac_pepper)
            row.hash_version = self.settings.api_key_hash_version
            self._audit(
                principal,
                correlation_id,
                "api_key_rotated",
                row.id,
                {
                    "old_prefix": old_prefix,
                    "new_prefix": prefix,
                    "grace_expires_at": self._iso(row.grace_expires_at),
                    "reason": self._redact_reason(request.reason),
                },
            )
            response = self._secret(row, secret)
            self.session.commit()
            return response
        except ApiError as exc:
            self._audit_failure(principal, correlation_id, "api_key_rotate_failed", exc.code)
            raise
        except (IntegrityError, SQLAlchemyError, ValueError, TypeError) as exc:
            self.session.rollback()
            raise self._unavailable() from exc

    def revoke_key(
        self, principal: AuthenticatedPrincipal, key_id: UUID, *, correlation_id: UUID
    ) -> ApiKeyResponse:
        now = datetime.now(timezone.utc)
        try:
            row = self.session.scalar(
                select(ApiKey).where(ApiKey.id == key_id).with_for_update()
            )
            if row is None:
                raise self._not_found()
            if row.revoked_at is None:
                row.revoked_at = now
            row.previous_key_hash = None
            row.previous_hash_version = None
            row.previous_key_prefix = None
            row.grace_expires_at = None
            self._audit(
                principal,
                correlation_id,
                "api_key_revoked",
                row.id,
                {"prefix": row.key_prefix, "already_revoked": row.revoked_at < now},
            )
            response = self._public(row, now=now)
            self.session.commit()
            return response
        except ApiError as exc:
            self._audit_failure(principal, correlation_id, "api_key_revoke_failed", exc.code)
            raise
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            self.session.rollback()
            raise self._unavailable() from exc

    def _owned(self, key_id: UUID) -> ApiKey:
        row = self.session.scalar(select(ApiKey).where(ApiKey.id == key_id))
        if row is None:
            raise self._not_found()
        return row

    def _validate_delegation(self, principal: AuthenticatedPrincipal, scopes: list[str]) -> None:
        allowed = (
            ADMIN_DELEGATED_SCOPES
            if principal.role == "tenant_administrator"
            else DEVELOPER_DELEGATED_SCOPES
        )
        if not set(scopes).issubset(allowed):
            raise ApiError(403, "insufficient_scope", "The requested API-key scopes cannot be delegated")

    @staticmethod
    def _validate_expiry(expires_at: datetime | None, now: datetime) -> None:
        if expires_at is None:
            return
        if expires_at.tzinfo is None or expires_at.utcoffset() is None or expires_at <= now:
            raise ApiError(
                422,
                "validation_failed",
                "API-key expiry must be a future UTC timestamp",
                details={"fields": [{"field": "expires_at", "message": "Must be in the future"}]},
            )

    @staticmethod
    def _status(row: ApiKey, now: datetime) -> str:
        if row.revoked_at is not None:
            return "revoked"
        if row.expires_at is not None and row.expires_at <= now:
            return "expired"
        return "active"

    def _public(self, row: ApiKey, *, now: datetime | None = None) -> ApiKeyResponse:
        current = now or datetime.now(timezone.utc)
        return ApiKeyResponse(
            id=row.id,
            name=row.name,
            prefix=row.key_prefix,
            scopes=row.scopes,
            status=self._status(row, current),
            expires_at=row.expires_at,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
            grace_expires_at=row.grace_expires_at if row.grace_expires_at and row.grace_expires_at > current else None,
        )

    def _secret(self, row: ApiKey, secret: str) -> ApiKeySecretResponse:
        return ApiKeySecretResponse(**self._public(row).model_dump(), secret=secret)

    def _audit(
        self,
        principal: AuthenticatedPrincipal,
        correlation_id: UUID,
        action: str,
        resource_id: UUID | None,
        details: dict[str, object],
    ) -> None:
        self.session.add(
            AuditLog(
                id=uuid4(),
                tenant_id=principal.tenant_id,
                actor_type=principal.actor_type,
                actor_reference=principal.actor_reference,
                action_type=action,
                resource_type="api_key",
                resource_reference=resource_id,
                outcome="succeeded",
                correlation_reference=correlation_id,
                redacted_details=details,
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _audit_failure(
        self,
        principal: AuthenticatedPrincipal,
        correlation_id: UUID,
        action: str,
        error_code: str,
    ) -> None:
        self.session.rollback()
        try:
            if not self.session.in_transaction():
                self.session.begin()
            set_local_tenant(self.session, principal.tenant_id)
            self.session.add(
                AuditLog(
                    id=uuid4(),
                    tenant_id=principal.tenant_id,
                    actor_type=principal.actor_type,
                    actor_reference=principal.actor_reference,
                    action_type=action,
                    resource_type="api_key",
                    resource_reference=None,
                    outcome="failed",
                    correlation_reference=correlation_id,
                    redacted_details={"error_code": error_code},
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _redact_reason(value: str) -> str:
        return re.sub(r"gr_live_[A-Za-z0-9_-]+", "<redacted>", value)

    @staticmethod
    def _not_found() -> ApiError:
        return ApiError(404, "resource_not_found", "The requested resource was not found")

    @staticmethod
    def _unavailable() -> ApiError:
        return ApiError(
            503,
            "service_unavailable",
            "API-key management is temporarily unavailable",
            retryable=True,
            retry_after_seconds=5,
        )
