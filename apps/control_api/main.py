"""The control-plane API.

A modular monolith: routers here, domain logic in `graphrec.domain`. Everything
lives under `/v1`, with platform-realm endpoints under `/v1/platform/*` (D6), so
that two same-named resources in different realms — tenant audit and platform
audit — can never be confused for one another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.control_api.errors import install_error_handlers
from apps.control_api.middleware import BodyLimitMiddleware, RequestContextMiddleware
from apps.control_api.routers import health
from graphrec.common.config import Settings, get_settings
from graphrec.common.logging import configure_logging, get_logger

logger = get_logger(__name__)

API_PREFIX = "/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    logger.info(
        "api_starting",
        extra={
            "environment": settings.environment.value,
            "serving_driver": settings.serving_driver.value,
            "candidate_index": settings.candidate_index.value,
            "email_delivery": settings.email_delivery_available,
        },
    )
    if not settings.email_delivery_available:
        # Invitations and account recovery both need out-of-band token delivery.
        # Without SMTP the admin CLI is the only route, which is an operational
        # constraint worth stating at startup rather than discovering later.
        logger.warning(
            "email_delivery_unconfigured",
            extra={"impact": "invitation and recovery tokens must be surfaced by the admin CLI"},
        )
    yield
    logger.info("api_stopping")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="GraphRec",
        version="0.1.0",
        description=(
            "Multi-tenant recommendation platform. Tenant scope is resolved from the "
            "verified credential and never from a path, query or body parameter."
        ),
        lifespan=lifespan,
        # Trailing slashes are rejected rather than redirected: a 307 to a
        # different path silently drops the Authorization header on some clients.
        redirect_slashes=False,
        openapi_url="/openapi.json",
        docs_url="/docs",
    )

    # Outermost first: the request id must be bound before anything can fail,
    # so that even a body-limit rejection carries a reference.
    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=settings.max_request_body_bytes,
        bulk_limit=settings.max_bulk_body_bytes,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "Retry-After"],
    )

    install_error_handlers(app)

    # Operational endpoints sit outside /v1: they are infrastructure, not API.
    app.include_router(health.router)

    v1 = APIRouter(prefix=API_PREFIX)
    # Phase 2 mounts identity, tenancy and platform routers here.
    app.include_router(v1)

    return app


app = create_app()
