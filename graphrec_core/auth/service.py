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
from graphrec_core.auth.passwords import hash_password, verify_password
from graphrec_core.auth.setup_tokens import revoke_open_setup_tokens, setup_token_hash
from graphrec_core.database.models import (
    AccountSetupToken,
    AuditLog,
    RefreshSession,
    SecurityEvent,
    TenantUser,
)
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.auth import AuthTokenPair, LoginRequest, SetupPasswordRequest
from graphrec_core.settings import Settings

# Bearer-token scopes per console role. Domain routes enforce these with
# ``AuthenticatedPrincipal.require_scope``; sign in again after changing them,
# because access tokens carry the scopes granted at login.
ROLE_SCOPES: dict[str, list[str]] = {
    "tenant_administrator": [
        "keys:write",
        "billing:read",
        "usage:read",
        "catalog:read",
        "catalog:write",
        "events:read",
        "events:write",
        "training:read",
        "training:write",
        "models:read",
        "models:write",
        "models:deploy",
        "recommendations:read",
        "deployments:read",
        "metrics:read",
    ],
    "tenant_developer": [
        "keys:write",
        "catalog:read",
        "catalog:write",
        "events:read",
        "events:write",
        # Lets the data-upload page confirm the snapshot its import produced.
        "training:read",
    ],
}


@dataclass(frozen=True)
class SetupTokenRecord:
    token_id: UUID
    tenant_id: UUID
    user_id: UUID
    normalized_email: str
    user_status: str
    user_role: str
    has_credential: bool
    tenant_status: str
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


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
        """Activate an invited account with a one-time setup token.

        Every rejection returns the same 401 so callers cannot learn whether a
        token exists, expired, was used, or belongs to another address.
        """

        try:
            record = self._resolve_setup_token(setup_token_hash(payload.setup_token))
            now = datetime.now(timezone.utc)
            reason = self._setup_denial_reason(record, payload, now)
            if record is None or reason is not None:
                self._record_setup_failure(
                    correlation_id=correlation_id,
                    source=source,
                    reason=reason or "unknown_token",
                    tenant_id=record.tenant_id if record is not None else None,
                )
                self.session.commit()
                raise self._setup_failed()

            # Hash before taking row locks; the guarded updates below make the
            # token single-use even when two requests race.
            credential_digest = hash_password(payload.password)
            set_local_tenant(self.session, record.tenant_id)
            consumed = self.session.execute(
                update(AccountSetupToken)
                .where(
                    AccountSetupToken.tenant_id == record.tenant_id,
                    AccountSetupToken.id == record.token_id,
                    AccountSetupToken.used_at.is_(None),
                    AccountSetupToken.revoked_at.is_(None),
                    AccountSetupToken.expires_at > now,
                )
                .values(used_at=now)
            ).rowcount
            activated = 0
            if consumed == 1:
                activated = self.session.execute(
                    update(TenantUser)
                    .where(
                        TenantUser.tenant_id == record.tenant_id,
                        TenantUser.id == record.user_id,
                        TenantUser.status == "invited",
                        TenantUser.credential_digest.is_(None),
                    )
                    .values(credential_digest=credential_digest, status="active")
                ).rowcount
            if consumed != 1 or activated != 1:
                self.session.rollback()
                self._record_setup_failure(
                    correlation_id=correlation_id,
                    source=source,
                    reason="concurrent_use",
                    tenant_id=record.tenant_id,
                )
                self.session.commit()
                raise self._setup_failed()

            revoke_open_setup_tokens(
                self.session, tenant_id=record.tenant_id, user_id=record.user_id, now=now
            )
            self.session.add(
                AuditLog(
                    id=uuid4(),
                    tenant_id=record.tenant_id,
                    actor_type="tenant_user",
                    actor_reference=record.user_id,
                    action_type="account_setup",
                    resource_type="tenant_user",
                    resource_reference=record.user_id,
                    outcome="succeeded",
                    correlation_reference=correlation_id,
                    redacted_details={"role": record.user_role},
                    occurred_at=now,
                )
            )
            identity = LoginIdentity(
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                normalized_email=record.normalized_email,
                credential_digest=credential_digest,
                user_status="active",
                tenant_status=record.tenant_status,
                user_role=record.user_role,
            )
            # Commits the token consumption, activation, audit and new session together.
            return self._issue_session(
                identity,
                correlation_id=correlation_id,
                source=source,
                email=record.normalized_email,
            )
        except ApiError:
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ApiError(
                503,
                "service_unavailable",
                "Account setup is temporarily unavailable",
                retryable=True,
                retry_after_seconds=5,
            ) from exc

    def record_setup_rate_limit_denial(
        self,
        *,
        correlation_id: UUID,
        source: str,
        retry_after_seconds: int,
    ) -> None:
        try:
            self._record_setup_failure(
                correlation_id=correlation_id,
                source=source,
                reason="rate_limited",
                extra={"retry_after_seconds": retry_after_seconds},
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

    def _resolve_setup_token(self, token_hash: str) -> SetupTokenRecord | None:
        row = (
            self.session.execute(
                text(
                    """
                    SELECT token_id, tenant_id, user_id, normalized_email, user_status,
                           user_role, has_credential, tenant_status, expires_at,
                           used_at, revoked_at
                    FROM resolve_account_setup_token(:token_hash)
                    """
                ),
                {"token_hash": token_hash},
            )
            .mappings()
            .first()
        )
        return SetupTokenRecord(**dict(row)) if row is not None else None

    @staticmethod
    def _setup_denial_reason(
        record: SetupTokenRecord | None, payload: SetupPasswordRequest, now: datetime
    ) -> str | None:
        if record is None:
            return "unknown_token"
        if record.revoked_at is not None:
            return "revoked_token"
        if record.used_at is not None:
            return "used_token"
        if record.expires_at <= now:
            return "expired_token"
        if payload.email is not None and payload.email != record.normalized_email:
            return "email_mismatch"
        if record.user_status != "invited" or record.has_credential:
            return "account_not_invited"
        if record.tenant_status != "active":
            return "tenant_inactive"
        if record.user_role not in ROLE_SCOPES:
            return "role_not_allowed"
        return None

    def _record_setup_failure(
        self,
        *,
        correlation_id: UUID,
        source: str,
        reason: str,
        tenant_id: UUID | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            SecurityEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                event_type="account_setup_denied",
                severity="warning",
                source_hash=protected_auth_hash(source),
                sanitized_detail={
                    "correlation_id": str(correlation_id),
                    "reason": reason,
                    **(extra or {}),
                },
                occurred_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _setup_failed() -> ApiError:
        return ApiError(
            401,
            "invalid_setup_token",
            "The setup token is invalid, expired, or already used",
        )

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
