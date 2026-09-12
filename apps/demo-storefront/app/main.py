"""Facet storefront service: FastAPI app factory, lifespan and static SPA serving."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from graphrec_sdk import APIError

from .config import PACKAGE_DIR, Settings, get_settings
from .dependencies import services
from .errors import error_response, install_error_handlers
from .graphrec import Services, build_services
from .routes import events, products, recommendations, session
from .schemas import Envelope, HealthOut

MAX_BODY_BYTES = 32 * 1024
API_PREFIX = "/api/demo"


def create_app(settings: Optional[Settings] = None, svc: Optional[Services] = None) -> FastAPI:
    """Build the app. Tests pass ``svc`` with fakes; production builds the real client in the lifespan."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        built = svc or build_services(cfg)
        if svc is None:
            built.tracker.start()
        app.state.services = built
        app.state.settings = cfg
        try:
            yield
        finally:
            if svc is None:
                await built.close()

    app = FastAPI(title="Facet storefront", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    install_error_handlers(app)

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return error_response(413, "payload_too_large", f"Request bodies are limited to {MAX_BODY_BYTES} bytes.")
        return await call_next(request)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(session.router)
    api.include_router(products.router)
    api.include_router(events.router)
    api.include_router(recommendations.router)

    @api.get("/health", response_model=Envelope[HealthOut])
    async def health(request: Request, svc_: Services = Depends(services)) -> Envelope[HealthOut]:
        cfg: Settings = request.app.state.settings
        graphrec_status = "ok"
        correlation_id = None
        count = None
        try:
            result = await svc_.client.health()
            graphrec_status = str(result.get("status", "ok")) if isinstance(result, dict) else "ok"
            count = len(await svc_.catalog.listed())
        except APIError as error:
            graphrec_status = "unreachable"
            correlation_id = error.correlation_id
        return Envelope(
            data=HealthOut(
                graphrec=graphrec_status,
                graphrec_base_url=cfg.graphrec_base_url,
                proof_configured=cfg.model_proof_verified,
                proof_version_id=cfg.model_proof_version_id or None,
                catalog_products=count,
                correlation_id=correlation_id,
            )
        )

    @api.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def unknown_api(path: str):
        return error_response(404, "not_found", f"Unknown API route /api/demo/{path}.")

    app.include_router(api)

    dist = settings.frontend_dist if settings else PACKAGE_DIR / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = dist / path
            if path and ".." not in path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return JSONResponse({"message": "Facet API is running. Build the frontend (cd frontend && npm run build) or use the Vite dev server."})

    return app


app = create_app()
