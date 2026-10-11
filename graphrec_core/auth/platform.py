"""Platform (operator) authentication and authorization (D-04).

Operators sign in with their own account and receive a short-lived bearer token
for the ``graphrec-platform`` audience. Every platform route names the roles that
may call it, and every audit row written during the request is attributed to the
operator through the ``app.audit_actor`` setting (migration 0034 trigger).

``PLATFORM_ADMIN_TOKEN`` is the bootstrap credential:

* development: accepted on every platform route as a full-role operator without an
  identity (kept for local tooling and the test suites);
* production: accepted only to create operators, and only while no active
  operator exists. Once the first operator exists it opens nothing.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.settings import Settings, get_settings

ROLES = ("platform", "plan_management", "monitoring", "audit", "operator_admin")
AUDIENCE = "graphrec-platform"

#: Which roles may call each platform route (method, path template). A route not
#: listed here is refused, so a new route cannot become reachable by accident.
ROUTE_ROLES: dict[tuple[str, str], frozenset[str]] = {
    ("GET", "/v1/platform/me"): frozenset(ROLES),
    ("GET", "/v1/platform/tenants"): frozenset({"platform", "plan_management", "monitoring", "audit"}),
    ("GET", "/v1/platform/tenants/{tenant_id}"): frozenset({"platform", "plan_management", "monitoring", "audit"}),
    ("POST", "/v1/platform/tenants/{tenant_id}/status"): frozenset({"platform"}),
    ("POST", "/v1/platform/tenants/{tenant_id}/recovery"): frozenset({"platform"}),
    ("GET", "/v1/platform/tenants/{tenant_id}/quotas"): frozenset({"platform", "plan_management", "monitoring"}),
    ("POST", "/v1/platform/tenants/{tenant_id}/quotas"): frozenset({"plan_management"}),
    ("POST", "/v1/platform/tenants/{tenant_id}/plan"): frozenset({"plan_management"}),
    ("GET", "/v1/platform/tenants/{tenant_id}/usage"): frozenset({"monitoring", "plan_management"}),
    ("GET", "/v1/platform/usage"): frozenset({"monitoring", "plan_management"}),
    ("GET", "/v1/platform/plans"): frozenset({"plan_management", "platform", "monitoring"}),
    ("PUT", "/v1/platform/plans/{plan_id}"): frozenset({"plan_management"}),
    ("GET", "/v1/platform/plan-requests"): frozenset({"plan_management", "platform", "monitoring"}),
    ("POST", "/v1/platform/plan-requests/{request_id}:approve"): frozenset({"plan_management"}),
    ("POST", "/v1/platform/plan-requests/{request_id}:reject"): frozenset({"plan_management"}),
    ("GET", "/v1/platform/status"): frozenset(ROLES),
    ("GET", "/v1/platform/failures"): frozenset({"monitoring", "audit"}),
    ("GET", "/v1/platform/audit"): frozenset({"audit"}),
    ("GET", "/v1/platform/operators"): frozenset({"operator_admin"}),
    ("POST", "/v1/platform/operators"): frozenset({"operator_admin"}),
    ("PATCH", "/v1/platform/operators/{operator_id}"): frozenset({"operator_admin"}),
}


@dataclass(frozen=True)
class OperatorPrincipal:
    #: ``None`` for the bootstrap token, which has no identity.
    operator_id: UUID | None
    email: str | None
    roles: frozenset[str]
    kind: str  # "operator" | "bootstrap_token"


def _failed() -> ApiError:
    return ApiError(401, "authentication_failed", "Authentication failed")


def _forbidden() -> ApiError:
    return ApiError(403, "insufficient_scope", "Your operator role does not permit this action")


def issue_operator_token(operator_id: UUID, roles: list[str], epoch: int, settings: Settings) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    ttl = settings.operator_token_ttl_seconds
    token = jwt.encode({"sub": str(operator_id), "roles": sorted(roles), "av": epoch, "iat": now,
                        "exp": now + timedelta(seconds=ttl), "jti": str(uuid4()), "iss": "graphrec", "aud": AUDIENCE},
                       settings.jwt_signing_secret, algorithm="HS256")
    return token, ttl


def active_operator_exists(db: Session) -> bool:
    return bool(db.scalar(text("SELECT EXISTS (SELECT 1 FROM platform_operators WHERE status = 'active')")))


def _bootstrap(presented: str, request: Request, db: Session, settings: Settings) -> OperatorPrincipal | None:
    expected = settings.platform_admin_token
    if expected is None or not hmac.compare_digest(presented.encode(), expected.encode()):
        return None
    if not settings.is_production:
        return OperatorPrincipal(None, None, frozenset(ROLES), "bootstrap_token")
    route = getattr(request.scope.get("route"), "path", "")
    if (request.method, route) == ("POST", "/v1/platform/operators") and not active_operator_exists(db):
        return OperatorPrincipal(None, None, frozenset({"operator_admin"}), "bootstrap_token")
    raise _failed()


def _operator(token: str, db: Session, settings: Settings) -> OperatorPrincipal:
    try:
        claims = jwt.decode(token, settings.jwt_signing_secret, algorithms=["HS256"], audience=AUDIENCE,
                            issuer="graphrec", options={"require": ["sub", "roles", "av", "exp"]})
        operator_id = UUID(str(claims["sub"]))
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "token_expired", "Access token expired") from exc
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise _failed() from exc
    try:
        row = db.execute(text("SELECT email::text AS email, roles, status, auth_epoch FROM platform_operators "
                              "WHERE id = :id"), {"id": operator_id}).mappings().one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ApiError(503, "service_unavailable", "Authorization is temporarily unavailable",
                       retryable=True, retry_after_seconds=5) from exc
    if row is None or row["status"] != "active" or row["auth_epoch"] != claims["av"]:
        raise _failed()
    # Roles come from the account now, so a role change takes effect on the next request.
    return OperatorPrincipal(operator_id, row["email"], frozenset(row["roles"]), "operator")


def platform_principal(request: Request, db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings)) -> OperatorPrincipal:
    """Authenticate the operator; does not check roles (see ``platform_administrator``)."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    presented = token.strip()
    if scheme.lower() != "bearer" or not presented:
        raise _failed()
    principal = _bootstrap(presented, request, db, settings) or _operator(presented, db, settings)
    request.state.operator = principal
    return principal


def platform_administrator(request: Request, principal: OperatorPrincipal = Depends(platform_principal),
                           db: Session = Depends(get_db)) -> OperatorPrincipal:
    """Router-level guard: authenticate, check the route's roles, attribute audits."""
    route = getattr(request.scope.get("route"), "path", "")
    allowed = ROUTE_ROLES.get((request.method, route))
    if allowed is None or not principal.roles & allowed:
        raise _forbidden()
    if principal.operator_id is not None:
        if not db.in_transaction():
            db.begin()
        db.execute(text("SELECT set_config('app.audit_actor', :id, true)"), {"id": str(principal.operator_id)})
    return principal
