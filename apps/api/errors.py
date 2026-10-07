from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import logging
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool

from graphrec_core.errors import ApiError
from graphrec_core.auth.audit import record_public_login_denial
from graphrec_core.registration.audit import record_public_registration_denial


def correlation_id_for(request: Request) -> UUID:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, UUID) else uuid4()


def error_response(
    *,
    correlation_id: UUID,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
    details: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": str(correlation_id),
        "retryable": retryable,
    }
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds
    if details:
        error["details"] = details
    headers = {**(extra_headers or {}), "X-Correlation-ID": str(correlation_id)}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    principal = getattr(request.state, 'authenticated_principal', None)
    if principal is not None and exc.status_code in {403, 404, 409, 422, 429, 503}:
        route = getattr(request.scope.get('route'), 'path', 'unknown')
        if _denial_audit_admitted(principal, exc.code, route):
            await run_in_threadpool(_record_tenant_denial, principal, correlation_id_for(request), exc.code, route)
    return error_response(
        correlation_id=correlation_id_for(request),
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        retry_after_seconds=exc.retry_after_seconds,
        details=exc.details,
        extra_headers=getattr(exc, "headers", None),
    )


#: A-18: at most this many identical denial audits (same credential, reason and
#: route) per minute, so a client hammering a 429 cannot turn each rejected
#: request into a database write. The first ones are always recorded.
DENIAL_AUDITS_PER_MINUTE = 5


def _denial_audit_admitted(principal, reason: str, route: str) -> bool:
    from graphrec_core.usage.admission import get_admission
    subject = f"{principal.tenant_id}:{principal.actor_reference}:{reason}:{route}"
    return get_admission().check_window("denial_audit", subject, DENIAL_AUDITS_PER_MINUTE, 60) is None


def _record_tenant_denial(principal, correlation_id, reason, route):
    from graphrec_core.database.models import AuditLog
    from graphrec_core.database.session import SessionLocal
    from graphrec_core.database.tenancy import set_local_tenant
    try:
        with SessionLocal() as db, db.begin():
            set_local_tenant(db, principal.tenant_id)
            db.add(AuditLog(id=uuid4(), tenant_id=principal.tenant_id, actor_type=principal.actor_type,
                actor_reference=principal.actor_reference, action_type='request_denied', resource_type='api_route',
                outcome='denied', correlation_reference=correlation_id,
                redacted_details={'reason': reason, 'route': route}, occurred_at=datetime.now(timezone.utc)))
    except Exception:
        logging.getLogger(__name__).warning('Could not persist denial audit for correlation %s', correlation_id)


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    malformed_json = any(error.get("type") == "json_invalid" for error in exc.errors())
    if request.url.path == "/v1/tenants":
        record_public_registration_denial(
            event_type="registration_validation_denied",
            correlation_id=correlation_id_for(request),
            source=request.client.host if request.client else "unknown",
            detail={
                "reason": "malformed_json" if malformed_json else "validation_failed",
                "fields": [
                    ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                    for error in exc.errors()
                ],
            },
        )
    elif request.url.path == "/v1/auth/login":
        record_public_login_denial(
            event_type="login_validation_denied",
            correlation_id=correlation_id_for(request),
            source=request.client.host if request.client else "unknown",
            detail={
                "reason": "malformed_json" if malformed_json else "validation_failed",
                "fields": [
                    ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                    for error in exc.errors()
                ],
            },
        )
    if malformed_json:
        return error_response(
            correlation_id=correlation_id_for(request),
            status_code=400,
            code="malformed_request",
            message="The JSON request body is malformed",
        )
    safe_fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            "message": error.get("msg", "Invalid value"),
        }
        for error in exc.errors()
    ]
    return error_response(
        correlation_id=correlation_id_for(request),
        status_code=422,
        code="validation_failed",
        message="One or more request fields are invalid",
        details={"fields": safe_fields},
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(
            correlation_id=correlation_id_for(request),
            status_code=404,
            code="resource_not_found",
            message="The requested resource was not found",
        )
    if exc.status_code == 405:
        return error_response(
            correlation_id=correlation_id_for(request),
            status_code=405,
            code="method_not_allowed",
            message="This method is not supported for the requested resource",
            extra_headers=dict(exc.headers or {}),
        )
    return error_response(
        correlation_id=correlation_id_for(request),
        status_code=400,
        code="malformed_request",
        message="The request could not be processed",
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A-03 / NR-NF-06: an unexpected failure still returns the error envelope with a
    traceable correlation id, and never the exception text (it may hold data)."""
    correlation_id = correlation_id_for(request)
    logging.getLogger("graphrec.api").error(
        "Unhandled error on %s %s (correlation %s)", request.method, request.url.path, correlation_id,
        exc_info=exc,
    )
    return error_response(
        correlation_id=correlation_id,
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred. Quote the correlation id when reporting it.",
        retryable=True,
    )
