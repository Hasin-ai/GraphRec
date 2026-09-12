"""HTTP core shared by :class:`~graphrec_sdk.GraphRec` and :class:`~graphrec_sdk.AsyncGraphRec`.

Responsibilities: URL and header construction, credential injection, JSON
encoding, retries with backoff, error mapping and response validation.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
import uuid
from functools import lru_cache
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union, cast

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from ._auth import Auth
from ._constants import (
    DEFAULT_MAX_BATCH_ITEMS,
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_TIMEOUT,
    HEADER_CORRELATION_ID,
    HEADER_IDEMPOTENCY_KEY,
)
from ._retry import RetryPolicy
from ._routes import ROUTES, Route
from ._serialization import encode_json
from ._version import __version__
from .errors import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    ConfigurationError,
    TokenExpiredError,
    error_from_response,
)
from .models.auth import AuthTokenPair

__all__ = ["AsyncAPIClient", "FileTuple", "SyncAPIClient", "TimeoutTypes"]

TimeoutTypes = Union[float, httpx.Timeout, None]
FileTuple = Tuple[str, bytes, str]

log = logging.getLogger("graphrec_sdk")


class _Omit:
    def __repr__(self) -> str:
        return "OMIT"


OMIT: Any = _Omit()


@lru_cache(maxsize=256)
def _adapter(tp: Any) -> TypeAdapter[Any]:
    return TypeAdapter(tp)


def _user_agent() -> str:
    return (
        f"graphrec-sdk-python/{__version__} "
        f"Python/{platform.python_version()} httpx/{httpx.__version__}"
    )


class _BaseClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth: Optional[Auth],
        timeout: TimeoutTypes,
        retry: RetryPolicy,
        max_body_bytes: int,
        max_batch_items: int,
        default_headers: Optional[Mapping[str, str]],
    ) -> None:
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise ConfigurationError(f"base_url must be an absolute http(s) URL, got {base_url!r}")
        if max_body_bytes < 1024:
            raise ConfigurationError("max_body_bytes must be at least 1024")
        if max_batch_items < 1:
            raise ConfigurationError("max_batch_items must be at least 1")
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout: Union[httpx.Timeout, float, None] = (
            DEFAULT_TIMEOUT if timeout is None else timeout
        )
        self.retry = retry
        self.max_body_bytes = max_body_bytes
        self.max_batch_items = max_batch_items
        self._default_headers: Dict[str, str] = dict(default_headers or {})

    # -- request construction -------------------------------------------------

    def _check_auth(self, route: Route) -> None:
        if route.auth in {"none", "optional"}:
            return
        if self.auth is None:
            raise ConfigurationError(
                f"{route.method} {route.path} requires credentials. Pass api_key=..., "
                "access_token=..., or email=/password= when creating the client."
            )
        if route.auth == "bearer" and self.auth.credential_type != "bearer":
            hint = (
                "Pass access_token=<PLATFORM_ADMIN_TOKEN>."
                if route.path.startswith("/v1/platform")
                else "API keys cannot manage API keys; use email=/password= or access_token=."
            )
            raise ConfigurationError(
                f"{route.method} {route.path} requires a bearer credential. {hint}"
            )

    def _url(self, route: Route, path_params: Optional[Mapping[str, object]]) -> str:
        return self.base_url + route.build_path(path_params)

    def _base_headers(
        self,
        route: Route,
        *,
        correlation_id: str,
        idempotency_key: Optional[str],
        extra_headers: Optional[Mapping[str, str]],
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": _user_agent(),
            HEADER_CORRELATION_ID: correlation_id,
        }
        # GraphRec's contract middleware requires this header on POST/PUT/PATCH;
        # older servers demand it even when the action endpoint has no body.
        if route.method in {"POST", "PUT", "PATCH"} and route.body != "multipart":
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers[HEADER_IDEMPOTENCY_KEY] = idempotency_key
        headers.update(self._default_headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @staticmethod
    def _encode_body(route: Route, json: Any) -> Optional[bytes]:
        if json is OMIT:
            return None
        if route.body != "json":  # pragma: no cover - programming error
            raise ValueError(f"{route.key} does not accept a JSON body")
        return encode_json(json)

    def _parse(self, response: httpx.Response, cast_to: Any, correlation_id: str) -> Any:
        if cast_to is None:
            return None
        try:
            data = response.json()
        except ValueError as exc:
            raise APIResponseValidationError(
                "GraphRec returned a non-JSON success response",
                response=response,
                body=response.text,
                correlation_id=correlation_id,
            ) from exc
        if cast_to is Any:
            return data
        try:
            if isinstance(cast_to, type) and issubclass(cast_to, BaseModel):
                return cast_to.model_validate(data)
            return _adapter(cast_to).validate_python(data)
        except ValidationError as exc:
            raise APIResponseValidationError(
                f"GraphRec response did not match the expected schema: {exc}",
                response=response,
                body=data,
                correlation_id=correlation_id,
            ) from exc

    @staticmethod
    def _log_response(
        route: Route, response: httpx.Response, started: float, correlation_id: str, attempt: int
    ) -> None:
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "GraphRec %s %s -> %s in %.0f ms (correlation_id=%s, attempt=%d)",
                route.method,
                response.request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                correlation_id,
                attempt + 1,
            )


class SyncAPIClient(_BaseClient):
    def __init__(
        self,
        *,
        base_url: str,
        auth: Optional[Auth],
        timeout: TimeoutTypes,
        retry: RetryPolicy,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            auth=auth,
            timeout=timeout,
            retry=retry,
            max_body_bytes=max_body_bytes,
            max_batch_items=max_batch_items,
            default_headers=default_headers,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self._sleep: Callable[[float], None] = time.sleep

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _login_for_auth(self, email: str, password: str) -> AuthTokenPair:
        return cast(
            AuthTokenPair,
            self.request(
                "auth.login", json={"email": email, "password": password}, cast_to=AuthTokenPair
            ),
        )

    def request(
        self,
        route_key: str,
        *,
        cast_to: Any,
        path_params: Optional[Mapping[str, object]] = None,
        json: Any = OMIT,
        files: Optional[Mapping[str, FileTuple]] = None,
        idempotency_key: Optional[str] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        timeout: TimeoutTypes = None,
    ) -> Any:
        route = ROUTES[route_key]
        self._check_auth(route)
        url = self._url(route, path_params)
        body = self._encode_body(route, json)
        correlation_id = str(uuid.uuid4())
        attempt = 0
        refreshed = False

        while True:
            headers = self._base_headers(
                route,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                extra_headers=extra_headers,
            )
            if route.auth != "none" and self.auth is not None:
                headers.update(self.auth.headers(self._login_for_auth))
            request = self._http.build_request(
                route.method,
                url,
                headers=headers,
                content=body,
                files=dict(files) if files else None,
                timeout=self.timeout if timeout is None else timeout,
            )
            started = time.perf_counter()
            try:
                response = self._http.send(request)
            except httpx.TransportError as exc:
                delay = self.retry.delay_for_exception(exc, route, attempt)
                if delay is None:
                    error_cls = (
                        APITimeoutError
                        if isinstance(exc, httpx.TimeoutException)
                        else APIConnectionError
                    )
                    raise error_cls(request=request, correlation_id=correlation_id) from exc
                log.info("Retrying %s %s after %s in %.2fs", route.method, route.path, exc, delay)
                self._sleep(delay)
                attempt += 1
                continue

            self._log_response(route, response, started, correlation_id, attempt)
            if response.is_success:
                return self._parse(response, cast_to, correlation_id)

            error = error_from_response(response)
            if (
                isinstance(error, TokenExpiredError)
                and self.auth is not None
                and self.auth.can_refresh
                and not refreshed
            ):
                self.auth.invalidate()
                refreshed = True
                continue
            delay = self.retry.delay_for_status(error, route, attempt)
            if delay is None:
                raise error
            log.info(
                "Retrying %s %s after HTTP %s (%s) in %.2fs",
                route.method,
                route.path,
                error.status_code,
                error.code,
                delay,
            )
            self._sleep(delay)
            attempt += 1


class AsyncAPIClient(_BaseClient):
    def __init__(
        self,
        *,
        base_url: str,
        auth: Optional[Auth],
        timeout: TimeoutTypes,
        retry: RetryPolicy,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            auth=auth,
            timeout=timeout,
            retry=retry,
            max_body_bytes=max_body_bytes,
            max_batch_items=max_batch_items,
            default_headers=default_headers,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self._sleep: Callable[[float], Any] = asyncio.sleep

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _login_for_auth(self, email: str, password: str) -> AuthTokenPair:
        result = await self.request(
            "auth.login", json={"email": email, "password": password}, cast_to=AuthTokenPair
        )
        return cast(AuthTokenPair, result)

    async def request(
        self,
        route_key: str,
        *,
        cast_to: Any,
        path_params: Optional[Mapping[str, object]] = None,
        json: Any = OMIT,
        files: Optional[Mapping[str, FileTuple]] = None,
        idempotency_key: Optional[str] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        timeout: TimeoutTypes = None,
    ) -> Any:
        route = ROUTES[route_key]
        self._check_auth(route)
        url = self._url(route, path_params)
        body = self._encode_body(route, json)
        correlation_id = str(uuid.uuid4())
        attempt = 0
        refreshed = False

        while True:
            headers = self._base_headers(
                route,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                extra_headers=extra_headers,
            )
            if route.auth != "none" and self.auth is not None:
                headers.update(await self.auth.async_headers(self._login_for_auth))
            request = self._http.build_request(
                route.method,
                url,
                headers=headers,
                content=body,
                files=dict(files) if files else None,
                timeout=self.timeout if timeout is None else timeout,
            )
            started = time.perf_counter()
            try:
                response = await self._http.send(request)
            except httpx.TransportError as exc:
                delay = self.retry.delay_for_exception(exc, route, attempt)
                if delay is None:
                    error_cls = (
                        APITimeoutError
                        if isinstance(exc, httpx.TimeoutException)
                        else APIConnectionError
                    )
                    raise error_cls(request=request, correlation_id=correlation_id) from exc
                log.info("Retrying %s %s after %s in %.2fs", route.method, route.path, exc, delay)
                await self._sleep(delay)
                attempt += 1
                continue

            self._log_response(route, response, started, correlation_id, attempt)
            if response.is_success:
                return self._parse(response, cast_to, correlation_id)

            error: APIStatusError = error_from_response(response)
            if (
                isinstance(error, TokenExpiredError)
                and self.auth is not None
                and self.auth.can_refresh
                and not refreshed
            ):
                self.auth.invalidate()
                refreshed = True
                continue
            delay = self.retry.delay_for_status(error, route, attempt)
            if delay is None:
                raise error
            log.info(
                "Retrying %s %s after HTTP %s (%s) in %.2fs",
                route.method,
                route.path,
                error.status_code,
                error.code,
                delay,
            )
            await self._sleep(delay)
            attempt += 1
