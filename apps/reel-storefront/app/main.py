"""Reel storefront: FastAPI app factory, lifespan and static SPA serving."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .dependencies import SESSION_COOKIE, MAX_AGE, new_session_id, valid_session
from .errors import error_response, install_error_handlers
from .graphrec import Services, build_services
from .routes import events, films, insight, recommendations, session

API_PREFIX = "/api/reel"


def create_app(settings: Optional[Settings] = None, svc: Optional[Services] = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        built = svc or build_services(cfg)
        app.state.services = built
        app.state.settings = cfg
        try:
            yield
        finally:
            if svc is None:
                await built.close()

    app = FastAPI(title="Reel storefront", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    install_error_handlers(app)

    @app.middleware("http")
    async def ensure_session(request: Request, call_next):
        """Every shopper gets a session id on their first request, so the next one sees the same session."""
        current = request.cookies.get(SESSION_COOKIE) or ""
        fresh = None if valid_session(current) else new_session_id()
        if fresh:
            request.state.session_id = fresh
        response = await call_next(request)
        if fresh and SESSION_COOKIE not in response.headers.get("set-cookie", ""):
            cfg = getattr(request.app.state, "settings", None)
            response.set_cookie(SESSION_COOKIE, fresh, httponly=True, samesite="lax", max_age=MAX_AGE, path="/",
                                secure=bool(cfg and cfg.reel_cookie_secure))
        return response
    api = APIRouter(prefix=API_PREFIX)
    for module in (session, films, events, recommendations, insight):
        api.include_router(module.router)

    @api.api_route("/{path:path}", methods=["GET", "POST"], include_in_schema=False)
    async def unknown(path: str):
        return error_response(404, "not_found", f"Unknown API route {API_PREFIX}/{path}.")

    app.include_router(api)

    dist = (settings.frontend_dist if settings else None) or Settings.model_fields["frontend_dist"].default
    if dist.is_dir() and (dist / "index.html").is_file():
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
            return JSONResponse({"message": "Reel API is running. Build the frontend (cd frontend && npm run build) or use npm run dev."})

    return app


app = create_app()
