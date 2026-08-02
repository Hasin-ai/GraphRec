from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.errors import api_error_handler, http_error_handler, validation_error_handler
from apps.api.middleware import ContractMiddleware
from apps.api.routes.auth import router as auth_router
from apps.api.routes.api_keys import router as api_keys_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.deployment import router as deployment_router
from apps.api.routes.events import router as events_router
from apps.api.routes.model_versions import router as model_versions_router
from apps.api.routes.platform import router as platform_router
from apps.api.routes.products import router as products_router
from apps.api.routes.recommendations import router as recommendations_router
from apps.api.routes.subscriptions import router as subscriptions_router
from apps.api.routes.tenants import router as tenants_router
from apps.api.routes.usage import router as usage_router
from graphrec_core.database.session import engine
from graphrec_core.errors import ApiError
from graphrec_core.settings import get_settings

app = FastAPI(
    title="GraphRec API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(ContractMiddleware, settings=get_settings())
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.include_router(tenants_router)
app.include_router(auth_router)
app.include_router(api_keys_router)
app.include_router(subscriptions_router)
app.include_router(usage_router)
app.include_router(products_router)
app.include_router(events_router)
app.include_router(datasets_router)
app.include_router(model_versions_router)
app.include_router(deployment_router)
app.include_router(recommendations_router)
app.include_router(platform_router)


@app.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
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
