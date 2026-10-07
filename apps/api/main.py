from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from apps.api.errors import (
    api_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from apps.api.body_limit import BodyLimitMiddleware
from apps.api.middleware import ContractMiddleware
from apps.api.routes.account import router as account_router
from apps.api.routes.audit import router as audit_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.api_keys import router as api_keys_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.deployment import router as deployment_router
from apps.api.routes.events import router as events_router
from apps.api.routes.meta import router as meta_router
from apps.api.routes.model_versions import router as model_versions_router
from apps.api.routes.operator_auth import router as operator_auth_router
from apps.api.routes.operators import router as operators_router
from apps.api.routes.platform import router as platform_router
from apps.api.routes.products import router as products_router
from apps.api.routes.recommendations import router as recommendations_router
from apps.api.routes.retraining import router as retraining_router
from apps.api.routes.recommendation_policy import router as recommendation_policy_router
from apps.api.routes.subscriptions import router as subscriptions_router
from apps.api.routes.tenant_users import router as tenant_users_router
from apps.api.routes.tenants import router as tenants_router
from apps.api.routes.usage import router as usage_router
from graphrec_core.database.session import engine
from graphrec_core.errors import ApiError
from graphrec_core.settings import get_settings
from graphrec_core.usage.admission import get_admission
from graphrec_core.version import __version__

app = FastAPI(
    title="GraphRec API",
    version=__version__,
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(ContractMiddleware, settings=get_settings())
app.add_middleware(BodyLimitMiddleware, settings=get_settings())
# Outermost: resolve the real client address from a trusted proxy before any
# per-source limit or audit reads request.client (A-01).
app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts=[h.strip() for h in get_settings().forwarded_allow_ips.split(",") if h.strip()],
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.include_router(meta_router)
app.include_router(tenants_router)
app.include_router(account_router)
app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(api_keys_router)
app.include_router(tenant_users_router)
app.include_router(subscriptions_router)
app.include_router(usage_router)
app.include_router(products_router)
app.include_router(events_router)
app.include_router(datasets_router)
app.include_router(model_versions_router)
app.include_router(deployment_router)
app.include_router(recommendations_router)
app.include_router(retraining_router)
app.include_router(recommendation_policy_router)
app.include_router(platform_router)
app.include_router(operator_auth_router)
app.include_router(operators_router)


@app.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    """Liveness plus database reachability (kept for existing probes and the SDK)."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ApiError(
            503,
            "service_unavailable",
            "Database health check failed",
            retryable=True,
            retry_after_seconds=5,
        ) from exc
    return {"status": "ok"}


def _timed(check):  # noqa: ANN001
    started = time.perf_counter()
    try:
        detail = check()
        status = "ok"
    except Exception as exc:  # noqa: BLE001 - any failure makes the dependency unavailable
        detail, status = type(exc).__name__, "unavailable"
    return {"status": status, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            **({"detail": detail} if detail else {})}


@app.get("/readyz", include_in_schema=False)
def ready() -> JSONResponse:
    """A-27: readiness with one entry per dependency, measured now.

    PostgreSQL is required (503 without it). Redis and Qdrant degrade service
    without stopping it (limits fall back per process; DGSR scores in process),
    so they are reported as ``degraded`` rather than failing readiness.
    """
    def database():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def redis():
        state = get_admission().status()
        if state["status"] == "degraded":
            raise ConnectionError("redis")
        return None if state["status"] == "ok" else state["status"]

    def vector_store():
        from graphrec_core.vector_store.client import get_qdrant_client
        get_qdrant_client().get_collections()

    checks = {"database": _timed(database), "redis": _timed(redis), "vector_store": _timed(vector_store)}
    if checks["database"]["status"] != "ok":
        status, code = "not_ready", 503
    elif any(c["status"] != "ok" for c in checks.values()):
        status, code = "degraded", 200
    else:
        status, code = "ready", 200
    return JSONResponse({"status": status, "version": __version__, "checks": checks}, status_code=code)
