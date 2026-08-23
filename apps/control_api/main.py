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
from redis.asyncio import ConnectionPool, Redis

from apps.control_api.routers import (
    api_keys,
    audit,
    auth,
    health,
    ingestion,
    platform,
    platform_auth,
    products,
    registry,
    serving,
    tenants,
    training,
    usage,
    users,
    well_known,
)
from graphrec.auth.tokens import TokenService
from graphrec.common.config import Settings, get_settings
from graphrec.common.logging import configure_logging, get_logger
from graphrec.db.engine import create_app_engine, create_platform_engine, create_sessionmaker
from graphrec.domain.metering.counters import RedisUsageCounters, ResilientUsageCounters
from graphrec.http import (
    BodyLimitMiddleware,
    RequestContextMiddleware,
    install_error_handlers,
)
from graphrec.storage.factory import create_artifact_store

logger = get_logger(__name__)

API_PREFIX = "/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
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

    # Both engines are disposed, not just the tenant one. A leaked platform pool
    # keeps connections open as a role that can read every tenant's plan and
    # quota rows.
    await app.state.engine.dispose()
    await app.state.platform_engine.dispose()
    await app.state.redis.aclose()
    # And the pool under it. `aclose` returns the client's own connection and
    # leaves every other one in the pool open, so a process that started and
    # stopped an app — a test, a reload, a CLI — leaves sockets for the garbage
    # collector to notice later as an unraisable `ResourceWarning`.
    await app.state.redis_pool.disconnect()
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

    app.state.settings = settings

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

    # Two engines, two roles, and nothing in between. Tenant traffic runs as
    # `graphrec_app`; `/v1/platform/*` runs as `graphrec_platform`, which holds no
    # grant whatsoever on products, events, customers or models. A platform
    # handler that tried to read tenant business data would fail on a missing
    # privilege rather than return it.
    app.state.engine = create_app_engine(settings)
    app.state.platform_engine = create_platform_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.platform_sessionmaker = create_sessionmaker(app.state.platform_engine)

    # The metering cache. Wrapped so that Redis being unreachable costs a
    # ledger query rather than a failed request — a measurement is never allowed
    # to depend on a cache being up (`domain/metering/counters.py`).
    # The pool is kept as well as the client: closing a client does not
    # disconnect a pool it was handed, and shutdown has to reach the pool.
    app.state.redis_pool = ConnectionPool.from_url(str(settings.redis_url))
    app.state.redis = Redis(connection_pool=app.state.redis_pool)
    app.state.usage_counters = ResilientUsageCounters(RedisUsageCounters(app.state.redis))

    # The artifact store, for the one control-plane operation that needs the
    # bytes: a roll back validates that its target's artifact is still there
    # before it changes desired state (ER-F-07). `:archive` uses it too, to
    # delete what it retires. A control API configured without one still reads
    # the registry; it just says so rather than pretending the check passed.
    app.state.artifact_store = create_artifact_store(settings)

    app.state.tokens = TokenService(
        private_key_path=settings.jwt_private_key_path,
        public_key_path=settings.jwt_public_key_path,
        key_id=settings.jwt_key_id,
        issuer=settings.jwt_issuer,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
    )

    # Operational endpoints sit outside /v1: they are infrastructure, not API.
    app.include_router(health.router)
    app.include_router(well_known.router)

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(auth.router)
    v1.include_router(tenants.router)
    v1.include_router(users.router)
    v1.include_router(api_keys.router)
    v1.include_router(products.router)
    v1.include_router(ingestion.router)
    v1.include_router(usage.router)
    v1.include_router(audit.router)
    v1.include_router(training.router)
    v1.include_router(registry.router)
    v1.include_router(serving.router)
    # Snapshots hang off `/v1/datasets`, not `/v1/training-jobs`. A snapshot
    # outlives the run that produced it and is referenced by a model version, so
    # addressing it through the job would be addressing it through one of its
    # relations (BACKEND_PLAN L1131).
    v1.include_router(training.datasets)
    v1.include_router(platform_auth.router)
    v1.include_router(platform.router)
    app.include_router(v1)

    return app


app = create_app()
