"""D-04: operator sign-in (public; no platform credential required)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.routes.operators import OperatorLogin, OperatorSession, _security_event
from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.passwords import verify_password
from graphrec_core.auth.platform import issue_operator_token
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import SharedRateLimiter
from graphrec_core.settings import Settings, get_settings

router = APIRouter(prefix="/v1/platform/auth", tags=["platform"])
settings = get_settings()
operator_login_limiter = SharedRateLimiter(
    name="operator_login", limit=settings.login_rate_limit, window_seconds=settings.login_rate_window_seconds)


@router.post("/login", response_model=OperatorSession)
def operator_login(payload: OperatorLogin, request: Request, db: Session = Depends(get_db),
                   app_settings: Settings = Depends(get_settings)) -> OperatorSession:
    source = request.client.host if request.client else "unknown"
    email_key = protected_auth_hash(str(payload.email))
    retry = max(filter(None, [operator_login_limiter.check(f"source:{source}"),
                              operator_login_limiter.check(f"account:{email_key}")]), default=None)
    if retry is not None:
        raise ApiError(429, "rate_limit_exceeded", "Authentication request limit exceeded",
                       retryable=True, retry_after_seconds=retry)
    row = db.execute(text("SELECT id, email::text AS email, display_name, password_hash, roles, status, auth_epoch "
                          "FROM platform_operators WHERE email = :email"), {"email": str(payload.email)}).mappings().one_or_none()
    # verify_password runs a dummy hash when the account is unknown (constant work).
    if not verify_password(row["password_hash"] if row else None, payload.password) or row["status"] != "active":
        _security_event(db, "operator_login_failed", "warning",
                        {"correlation_id": str(request.state.correlation_id), "email_hash": email_key})
        db.commit()
        raise ApiError(401, "authentication_failed", "Authentication failed")
    db.execute(text("UPDATE platform_operators SET last_login_at = now() WHERE id = :id"), {"id": row["id"]})
    _security_event(db, "operator_login_succeeded", "info",
                    {"correlation_id": str(request.state.correlation_id), "operator_id": str(row["id"])})
    db.commit()
    token, ttl = issue_operator_token(row["id"], list(row["roles"]), row["auth_epoch"], app_settings)
    return OperatorSession(access_token=token, expires_in=ttl, operator_id=row["id"], email=row["email"],
                           display_name=row["display_name"], roles=sorted(row["roles"]))
