from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import jwt
from fastapi import Depends, Request
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.api_keys.crypto import api_key_digest, has_valid_secret_shape
from graphrec_core.api_keys.scopes import API_KEY_COMPATIBLE_SCOPES
from graphrec_core.auth.service import ROLE_SCOPES
from graphrec_core.database.models import ApiKey, Tenant, TenantUser
from graphrec_core.database.session import get_db
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.settings import Settings, get_settings


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID | None
    api_key_id: UUID | None
    tenant_id: UUID
    role: str
    scopes: frozenset[str]
    credential_type: str

    @property
    def actor_type(self) -> str:
        return "tenant_user" if self.credential_type == "bearer" else "api_key"

    @property
    def actor_reference(self) -> UUID:
        reference = self.user_id if self.credential_type == "bearer" else self.api_key_id
        if reference is None:
            raise RuntimeError("Authenticated principal has no actor reference")
        return reference

    @property
    def limiter_subject(self) -> str:
        return f"{self.tenant_id}:{self.actor_reference}"

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise ApiError(
                403,
                "insufficient_scope",
                "The credential does not grant the required permission",
            )

    def require_bearer(self) -> None:
        if self.credential_type != "bearer":
            raise _authentication_failed()


def authenticated_principal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedPrincipal:
    raw_header = request.headers.get("Authorization", "")
    scheme, separator, token = raw_header.partition(" ")
    if not separator or not token.strip():
        raise _authentication_failed()
    if scheme.lower() == "bearer":
        return _bearer_principal(token.strip(), db, settings)
    if scheme.lower() == "apikey":
        return _api_key_principal(token.strip(), db, settings)
    raise _authentication_failed()


def _bearer_principal(token: str, db: Session, settings: Settings) -> AuthenticatedPrincipal:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_signing_secret,
            algorithms=["HS256"],
            audience="graphrec-api",
            issuer="graphrec",
            options={"require": ["sub", "tid", "role", "scopes", "iat", "exp", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "token_expired", "Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _authentication_failed() from exc

    try:
        user_id = UUID(str(claims["sub"]))
        tenant_id = UUID(str(claims["tid"]))
        claimed_role = str(claims["role"])
        claimed_scopes = claims["scopes"]
        if not isinstance(claimed_scopes, list) or not all(
            isinstance(scope, str) for scope in claimed_scopes
        ):
            raise ValueError("invalid scope claims")
    except (KeyError, TypeError, ValueError) as exc:
        raise _authentication_failed() from exc

    try:
        if not db.in_transaction():
            db.begin()
        set_local_tenant(db, tenant_id)
        identity = db.execute(
            select(
                TenantUser.role.label("role"),
                TenantUser.status.label("user_status"),
                Tenant.status.label("tenant_status"),
            )
            .join(Tenant, Tenant.id == TenantUser.tenant_id)
            .where(TenantUser.id == user_id, TenantUser.tenant_id == tenant_id)
        ).one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        raise _authorization_unavailable() from exc

    if (
        identity is None
        or identity.user_status != "active"
        or identity.tenant_status != "active"
        or identity.role != claimed_role
        or identity.role not in ROLE_SCOPES
    ):
        raise _authentication_failed()

    return AuthenticatedPrincipal(
        user_id=user_id,
        api_key_id=None,
        tenant_id=tenant_id,
        role=identity.role,
        scopes=frozenset(claimed_scopes).intersection(ROLE_SCOPES[identity.role]),
        credential_type="bearer",
    )


def _api_key_principal(secret: str, db: Session, settings: Settings) -> AuthenticatedPrincipal:
    if not has_valid_secret_shape(secret):
        raise _authentication_failed()
    digest = api_key_digest(secret, settings.api_key_hmac_pepper)
    now = datetime.now(timezone.utc)
    try:
        candidate = db.execute(
            text(
                "SELECT key_id, tenant_id FROM public.resolve_api_key_candidate"
                "(:key_hash, :hash_version)"
            ),
            {"key_hash": digest, "hash_version": settings.api_key_hash_version},
        ).mappings().one_or_none()
        if candidate is None:
            raise _authentication_failed()
        key_id = UUID(str(candidate["key_id"]))
        tenant_id = UUID(str(candidate["tenant_id"]))
        if not db.in_transaction():
            db.begin()
        set_local_tenant(db, tenant_id)
        row = db.scalar(select(ApiKey).where(ApiKey.id == key_id))
        if row is None:
            raise _authentication_failed()
        current_matches = row.hash_version == settings.api_key_hash_version and hmac.compare_digest(
            row.key_hash, digest
        )
        previous_matches = (
            row.previous_key_hash is not None
            and row.previous_hash_version == settings.api_key_hash_version
            and row.grace_expires_at is not None
            and row.grace_expires_at > now
            and hmac.compare_digest(row.previous_key_hash, digest)
        )
        if (
            not (current_matches or previous_matches)
            or row.revoked_at is not None
            or (row.expires_at is not None and row.expires_at <= now)
            or not isinstance(row.scopes, list)
            or not all(isinstance(scope, str) for scope in row.scopes)
            or not set(row.scopes).issubset(API_KEY_COMPATIBLE_SCOPES)
        ):
            raise _authentication_failed()
        row.last_used_at = now
    except ApiError:
        db.rollback()
        raise
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        db.rollback()
        raise _authorization_unavailable() from exc

    return AuthenticatedPrincipal(
        user_id=None,
        api_key_id=key_id,
        tenant_id=tenant_id,
        role="api_key",
        scopes=frozenset(row.scopes),
        credential_type="api_key",
    )


def _authorization_unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "Authorization is temporarily unavailable",
        retryable=True,
        retry_after_seconds=5,
    )


def _authentication_failed() -> ApiError:
    return ApiError(401, "authentication_failed", "Authentication failed")
