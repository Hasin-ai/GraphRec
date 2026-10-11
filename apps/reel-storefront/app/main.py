"""Reel storefront: FastAPI app factory, lifespan, security middlewares, and static SPA serving."""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .config import Settings, get_settings
from .dependencies import (
    MAX_AGE,
    SESSION_COOKIE,
    new_session_id,
    sign_session,
    unsign_session,
    valid_session,
)
from .errors import error_response, install_error_handlers
from .graphrec import Services, build_services
from .observability import METRICS, configure_logging, correlation_id_var
from .routes import events, films, insight, proof, recommendations, session

logger = logging.getLogger("reel")
API_PREFIX = "/api/reel"


def create_app(settings: Optional[Settings] = None, svc: Optional[Services] = None) -> FastAPI:
    cfg = settings or get_settings()
    cfg.check_production_safety()
    configure_logging(cfg.reel_log_format)
    built = svc or build_services(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if built.storage.is_redis and built.storage._redis is not None:
            METRICS.bind_redis(built.storage._redis)
        app.state.services = built
        app.state.settings = cfg
        try:
            yield
        finally:
            if svc is None:
                await built.close()

    app = FastAPI(
        title="Reel storefront",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/reel/docs" if cfg.reel_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/reel/openapi.json",
    )
    # Ensure state is accessible even before lifespan starts (e.g. testing)
    app.state.services = built
    app.state.settings = cfg
    install_error_handlers(app)

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or f"reel-{secrets.token_hex(8)}"
        request.state.correlation_id = cid
        token = correlation_id_var.set(cid)
        start_time = time.monotonic()
        try:
            response: Response = await call_next(request)
        finally:
            duration = time.monotonic() - start_time
        response.headers["X-Correlation-ID"] = cid
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            route_path = route.path
            if request.url.path.startswith(API_PREFIX) and not route_path.startswith(API_PREFIX):
                route_path = f"{API_PREFIX}{route_path}"
        else:
            route_path = request.url.path
        METRICS.observe_http(request.method, route_path, response.status_code, duration)
        logger.info(
            "%s %s %d (%.2fms)",
            request.method,
            route_path,
            response.status_code,
            duration * 1000,
            extra={
                "method": request.method,
                "route": route_path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        correlation_id_var.reset(token)
        return response

    from urllib.parse import urlsplit
    _c = urlsplit(cfg.reel_covers_base_url) if cfg.reel_covers_base_url else None
    covers_origin = f" {_c.scheme}://{_c.netloc}" if _c and _c.scheme == "http" else ""

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (  # img-src also allows the RustFS cover bucket (http in dev)
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            f"img-src 'self' data: https:{covers_origin}; "
            "connect-src 'self' http: https:; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if cfg.reel_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.middleware("http")
    async def request_guard_middleware(request: Request, call_next):
        # 1. Body size limit
        content_length = request.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            if int(content_length) > cfg.reel_body_limit_bytes:
                return error_response(413, "payload_too_large", f"Request body exceeds {cfg.reel_body_limit_bytes} bytes limit.")

        # 2. Origin check for CSRF on state-changing requests
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("Origin")
            if origin and cfg.reel_allowed_origins:
                clean_origin = origin.rstrip("/")
                allowed_clean = [o.rstrip("/") for o in cfg.reel_allowed_origins]
                if clean_origin not in allowed_clean:
                    return error_response(403, "forbidden", f"Origin '{origin}' is not permitted.")

        # 3. Rate limiting for API calls
        if request.url.path.startswith(API_PREFIX):
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = built.storage.check_rate_limit(f"ip:{client_ip}", limit=cfg.reel_rate_limit_per_minute)
            if not allowed:
                METRICS.observe_rate_limit_hit()
                resp = error_response(429, "rate_limited", f"Rate limit exceeded. Try again in {retry_after} seconds.")
                resp.headers["Retry-After"] = str(retry_after)
                return resp

        return await call_next(request)

    @app.middleware("http")
    async def ensure_session(request: Request, call_next):
        """Every shopper gets a signed session on their first request."""
        raw_cookie = request.cookies.get(SESSION_COOKIE) or ""
        unsigned = unsign_session(raw_cookie, cfg.reel_secret_key)
        fresh_sid = None
        if unsigned:
            request.state.session_id = unsigned[0]
        elif valid_session(raw_cookie):
            request.state.session_id = raw_cookie
        else:
            fresh_sid = new_session_id()
            request.state.session_id = fresh_sid

        response: Response = await call_next(request)
        cookie_headers = response.headers.getlist("set-cookie")
        has_session_cookie = any(SESSION_COOKIE in h for h in cookie_headers)
        if fresh_sid and not has_session_cookie:
            signed_token = sign_session(fresh_sid, "anon", cfg.reel_secret_key)
            response.set_cookie(
                SESSION_COOKIE,
                signed_token,
                httponly=True,
                samesite="lax",
                max_age=MAX_AGE,
                path="/",
                secure=cfg.reel_cookie_secure,
            )
        return response

    # Film covers, same-origin: /reel-covers/<imdb>.jpg is streamed from the RustFS bucket.
    if cfg.reel_covers_base_url.startswith("/"):
        import re as _re
        import httpx
        from fastapi.responses import StreamingResponse

        covers_path = cfg.reel_covers_base_url.rstrip("/")
        covers_http = httpx.AsyncClient(timeout=10.0)
        cover_name = _re.compile(r"^[0-9]{7,8}\.jpg$")

        @app.get(covers_path + "/{name}", include_in_schema=False)
        async def cover(name: str):
            if not cover_name.match(name):
                return error_response(404, "not_found", "Unknown cover.")
            try:
                upstream = await covers_http.send(
                    covers_http.build_request("GET", f"{cfg.reel_covers_origin.rstrip('/')}/{name}"), stream=True)
            except httpx.HTTPError:
                return error_response(502, "covers_unavailable", "Cover storage is unreachable.")
            if upstream.status_code != 200:
                await upstream.aclose()
                return error_response(404, "not_found", "Unknown cover.")
            return StreamingResponse(
                upstream.aiter_bytes(), media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=604800"},
                background=BackgroundTask(upstream.aclose))

    # Operational Health Endpoints
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        checks = {
            "graphrec": "unknown",
            "redis": "ok" if built.storage.ping() else "down",
            "catalogue": "ok" if len(built.films.items) > 0 else "empty",
            "model": "ok" if bool(cfg.reel_model_version_id or cfg.reel_model_source) else "unconfigured",
        }
        try:
            gr_health = await built.client.health()
            checks["graphrec"] = "ok" if (isinstance(gr_health, dict) and gr_health.get("status") in ("ok", "healthy")) or gr_health == "ok" else "degraded"
        except Exception as exc:
            checks["graphrec"] = f"unreachable: {exc}"

        all_ready = (
            checks["graphrec"] == "ok"
            and checks["catalogue"] == "ok"
            and checks["model"] == "ok"
        )
        status_code = 200 if all_ready else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ready" if all_ready else "not_ready", "checks": checks},
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request):
        if cfg.reel_metrics_token:
            auth_header = request.headers.get("Authorization") or ""
            expected = f"Bearer {cfg.reel_metrics_token}"
            if auth_header != expected:
                return error_response(401, "unauthorized", "Invalid or missing metrics token.")
        elif cfg.reel_env == "production":
            return error_response(403, "forbidden", "Metrics endpoint requires REEL_METRICS_TOKEN in production.")

        return Response(
            content=METRICS.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    api = APIRouter(prefix=API_PREFIX)
    for module in (session, films, events, recommendations, insight, proof):
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
            try:
                resolved_candidate = candidate.resolve()
                resolved_dist = dist.resolve()
                if path and candidate.is_file() and resolved_candidate.is_relative_to(resolved_dist):
                    resp = FileResponse(resolved_candidate)
                    if "/assets/" in str(candidate):
                        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                    return resp
            except Exception:
                pass
            resp = FileResponse(dist / "index.html")
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
    else:
        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return JSONResponse({"message": "Reel API is running. Build frontend or run dev."})

    return app


app = create_app()
