from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from sqlalchemy import text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.passwords import verify_password
from graphrec_core.database.models import AuditLog, RefreshSession, SecurityEvent, TenantUser
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.auth import AuthTokenPair, LoginRequest
from graphrec_core.settings import Settings

ROLE_SCOPES: dict[str, list[str]] = {
    "tenant_administrator": [
        "keys:write",
        "billing:read",
        "usage:read",
        "training:read",
        "training:write",
        "models:read",
        "models:write",
        "models:deploy",
        "deployments:read",
        "metrics:read",
    ],
    "tenant_developer": [
        "keys:write",
        "catalog:read",
        "catalog:write",
        "events:read",
        "events:write",
    ],
}


@dataclass(frozen=True)
class LoginIdentity:
    user_id: UUID
    tenant_id: UUID
    normalized_email: str
    credential_digest: str | None
    user_status: str
    tenant_status: str
    user_role: str


class AuthenticationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def login(
        self,
        request: LoginRequest,
        *,
        correlation_id: UUID,
        source: str,
    ) -> AuthTokenPair:
        try:
            identities = self._resolve_identities(request.email)
            if len(identities) != 1:
                for identity in identities or [None]:
                    verify_password(
                        identity.credential_digest if identity is not None else None,
                        request.password,
                    )
                self._record_failure(
                    correlation_id=correlation_id,
                    source=source,
                    email=request.email,
                    reason="ambiguous_or_unknown",
                )
                self.session.commit()
                raise self._authentication_failed()

            identity = identities[0]
            password_valid = verify_password(identity.credential_digest, request.password)
            account_valid = (
                identity.user_status == "active"
                and identity.tenant_status == "active"
                and identity.user_role in ROLE_SCOPES
            )
            if not password_valid or not account_valid:
                self._record_failure(
                    correlation_id=correlation_id,
                    source=source,
                    email=request.email,
                    reason="credentials_or_status",
                    tenant_id=identity.tenant_id,
                )
                self.session.commit()
                raise self._authentication_failed()

            return self._issue_session(
                identity,
                correlation_id=correlation_id,
                source=source,
                email=request.email,
            )
        except ApiError:
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ApiError(
                503,
                "service_unavailable",
                "Authentication is temporarily unavailable",
                retryable=True,
                retry_after_seconds=5,
            ) from exc

    def setup_password(
        self,
        payload: SetupPasswordRequest,
        *,
        correlation_id: UUID,
        source: str,
    ) -> AuthTokenPair:
        try:
            identities = self._resolve_identities(payload.email)
            if not identities:
                raise ApiError(404, "resource_not_found", "No user found with the specified email.")

            identity = identities[0]
            # Update password and activate user
            from graphrec_core.auth.passwords import hash_password
            new_digest = hash_password(payload.password)

            set_local_tenant(self.session, identity.tenant_id)
            self.session.execute(
                update(TenantUser)
                .where(
                    TenantUser.tenant_id == identity.tenant_id,
                    TenantUser.id == identity.user_id,
                )
                .values(
                    credential_digest=new_digest,
                    status="active",
                )
            )

            # Re-fetch identity and issue session
            updated_identity = LoginIdentity(
                user_id=identity.user_id,
                tenant_id=identity.tenant_id,
                normalized_email=identity.normalized_email,
                credential_digest=new_digest,
                user_status="active",
                tenant_status=identity.tenant_status,
                user_role=identity.user_role,
            )
            return self._issue_session(
                updated_identity,
                correlation_id=correlation_id,
                source=source,
                email=payload.email,
            )
        except ApiError:
            raise
        except Exception as exc:
            self.session.rollback()
            print("EXCEPT IN setup_password:", type(exc), exc)
            raise ApiError(
                503,
                "service_unavailable",
                f"Password setup is temporarily unavailable: {exc}",
                retryable=True,
                retry_after_seconds=5,
            ) from exc

    def record_rate_limit_denial(
        self,
        *,
        email: str,
        correlation_id: UUID,
        source: str,
        retry_after_seconds: int,
    ) -> None:
        try:
            self._record_failure(
                correlation_id=correlation_id,
                source=source,
                email=email,
                reason="rate_limited",
                extra={"retry_after_seconds": retry_after_seconds},
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

    def _resolve_identities(self, email: str) -> list[LoginIdentity]:
        rows = self.session.execute(
            text(
                """
                SELECT user_id, tenant_id, normalized_email, credential_digest,
                       user_status, tenant_status, user_role
                FROM resolve_login_identities(:email)
                """
            ),
            {"email": email},
        ).mappings()
        return [LoginIdentity(**dict(row)) for row in rows]

    def _issue_session(
        self,
        identity: LoginIdentity,
        *,
        correlation_id: UUID,
        source: str,
        email: str,
    ) -> AuthTokenPair:
        now = datetime.now(timezone.utc)
        access_expires = now + timedelta(seconds=self.settings.access_token_ttl_seconds)
        refresh_expires = now + timedelta(seconds=self.settings.refresh_token_ttl_seconds)
        scopes = list(ROLE_SCOPES[identity.user_role])
        refresh_token = secrets.token_urlsafe(48)
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        access_token = jwt.encode(
            {
                "sub": str(identity.user_id),
                "tid": str(identity.tenant_id),
                "role": identity.user_role,
                "scopes": scopes,
                "iat": now,
                "exp": access_expires,
                "jti": str(uuid4()),
                "iss": "graphrec",
                "aud": "graphrec-api",
            },
            self.settings.jwt_signing_secret,
            algorithm="HS256",
        )

        set_local_tenant(self.session, identity.tenant_id)
        self.session.execute(
            update(TenantUser)
            .where(
                TenantUser.tenant_id == identity.tenant_id,
                TenantUser.id == identity.user_id,
            )
            .values(last_authenticated_at=now)
        )
        self.session.add_all(
            [
                RefreshSession(
                    id=uuid4(),
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    token_hash=refresh_hash,
                    created_at=now,
                    expires_at=refresh_expires,
                    revoked_at=None,
                    rotated_from_id=None,
                ),
                AuditLog(
                    id=uuid4(),
                    tenant_id=identity.tenant_id,
                    actor_type="tenant_user",
                    actor_reference=identity.user_id,
                    action_type="authentication",
                    resource_type="refresh_session",
                    resource_reference=None,
                    outcome="succeeded",
                    correlation_reference=correlation_id,
                    redacted_details={"role": identity.user_role},
                    occurred_at=now,
                ),
                SecurityEvent(
                    id=uuid4(),
                    tenant_id=identity.tenant_id,
                    event_type="login_succeeded",
                    severity="info",
                    source_hash=protected_auth_hash(source),
                    sanitized_detail={
                        "correlation_id": str(correlation_id),
                        "email_hash": protected_auth_hash(email),
                    },
                    occurred_at=now,
                ),
            ]
        )
        self.session.commit()
        return AuthTokenPair(
            access_token=access_token,
            token_type="Bearer",
            expires_in=self.settings.access_token_ttl_seconds,
            refresh_token=refresh_token,
            user_role=identity.user_role,  # type: ignore[arg-type]
            scopes=scopes,
        )

    def _record_failure(
        self,
        *,
        correlation_id: UUID,
        source: str,
        email: str,
        reason: str,
        tenant_id: UUID | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            SecurityEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                event_type="login_denied",
                severity="warning",
                source_hash=protected_auth_hash(source),
                sanitized_detail={
                    "correlation_id": str(correlation_id),
                    "email_hash": protected_auth_hash(email),
                    "reason": reason,
                    **(extra or {}),
                },
                occurred_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _authentication_failed() -> ApiError:
        return ApiError(
            401,
            "authentication_failed",
            "Authentication failed",
        )
