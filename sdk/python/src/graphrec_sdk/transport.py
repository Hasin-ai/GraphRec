"""One host, one credential, and the retry policy — synchronous and not.

There is a transport per plane and each namespace on the client holds exactly
one, which is what makes "send a data-plane call to the control host"
unrepresentable rather than merely documented.

The two classes below are the only place in this package where the sync and
async paths are written twice, and they are twice because `httpx.Client.send`
and `httpx.AsyncClient.send` cannot be spelled once without making every caller
`await` something that does not need it. The *policy* they share —
`_retry.will_retry`, `_retry.delay_for` — is written once, so a change to when
this SDK retries is a change to one file.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any

import anyio
import httpx

from ._retry import delay_for, will_retry
from .errors import APITimeoutError, GraphRecError, TransportError, error_from

if TYPE_CHECKING:
    from types import TracebackType

    from ._spec import Spec
    from .config import ResolvedConfig


def _headers(config: ResolvedConfig, spec: Spec) -> dict[str, str]:
    headers = {
        # The whole of the credential contract on the wire. Not a signature —
        # `HTTPBearer` on both apps reads this value and nothing else.
        "Authorization": config.credential.authorization,
        "Accept": "application/json",
        "User-Agent": config.user_agent,
    }
    if spec.body is not None:
        headers["Content-Type"] = "application/json"
    if spec.options and spec.options.request_id:
        headers["X-Request-Id"] = spec.options.request_id
    return headers


def _decode(response: httpx.Response) -> Any:
    """The body, or `None` when there is not one to read.

    A non-JSON body is not an exception here. A 502 from a proxy that never
    reached the application is HTML, and turning that into a parse error would
    lose the status — which is the only information the response carried.
    `error_from` handles the shapeless case.
    """
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _transport_error(spec: Spec, origin: str) -> TransportError:
    # DNS, connect, TLS, socket. Both edges pin `protocols tls1.3`, so a runtime
    # that cannot negotiate it lands here with no status to look up.
    return TransportError(
        f"{spec.method} {spec.path} could not reach {origin}. Check network reachability, "
        "and that this runtime can negotiate TLS 1.3 — both GraphRec edges require it."
    )


class _Base:
    def __init__(
        self, origin: str, config: ResolvedConfig, rng: random.Random | None = None
    ) -> None:
        self.origin = origin
        self._config = config
        self._rng = rng or random.Random()

    def _budget(self, spec: Spec) -> float:
        if spec.options and spec.options.timeout is not None:
            return spec.options.timeout
        return self._config.timeout

    def _failure(self, response: httpx.Response) -> GraphRecError:
        return error_from(
            response.status_code,
            _decode(response),
            response.headers.get("X-Request-Id"),
        )

    def _pause(
        self, attempt: int, spec: Spec, error: GraphRecError, deadline: float
    ) -> float | None:
        """How long to wait before the next attempt, or `None` to give up.

        The one place the policy is consulted, so the blocking and awaiting
        loops below cannot disagree about when this SDK retries.
        """
        delay = delay_for(attempt, error, self._rng)
        if not will_retry(
            attempt=attempt,
            idempotent=spec.idempotent,
            max_retries=self._config.max_retries,
            error=error,
            delay=delay,
            remaining=deadline - time.monotonic(),
        ):
            return None
        return min(delay, max(deadline - time.monotonic(), 0.0))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(origin={self.origin!r})"


class Transport(_Base):
    """Blocking. Holds an `httpx.Client` for connection reuse."""

    def __init__(
        self,
        origin: str,
        config: ResolvedConfig,
        client: httpx.Client | None = None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(origin, config, rng)
        self._client = client or httpx.Client()
        self._owns_client = client is None

    def send(self, spec: Spec) -> Any:
        budget = self._budget(spec)
        deadline = time.monotonic() + budget
        headers = _headers(self._config, spec)
        url = f"{self.origin}{spec.path}"
        last: GraphRecError | None = None

        attempt = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise last or APITimeoutError(
                    f"No time left in the {budget}s budget for {spec.path}."
                )

            try:
                response = self._client.request(
                    spec.method,
                    url,
                    headers=headers,
                    json=spec.body,
                    timeout=remaining,
                )
            except httpx.TimeoutException as exc:
                raise APITimeoutError(
                    f"{spec.method} {spec.path} did not complete within {budget}s."
                ) from exc
            except httpx.HTTPError as exc:
                last = _transport_error(spec, self.origin)
                pause = self._pause(attempt, spec, last, deadline)
                if pause is None:
                    raise last from exc
                time.sleep(pause)
                attempt += 1
                continue

            if response.is_success:
                return _decode(response)

            last = self._failure(response)
            pause = self._pause(attempt, spec, last, deadline)
            if pause is None:
                raise last
            time.sleep(pause)
            attempt += 1

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class AsyncTransport(_Base):
    """The same policy, awaited. Holds an `httpx.AsyncClient`."""

    def __init__(
        self,
        origin: str,
        config: ResolvedConfig,
        client: httpx.AsyncClient | None = None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(origin, config, rng)
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def send(self, spec: Spec) -> Any:
        budget = self._budget(spec)
        deadline = time.monotonic() + budget
        headers = _headers(self._config, spec)
        url = f"{self.origin}{spec.path}"
        last: GraphRecError | None = None

        attempt = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise last or APITimeoutError(
                    f"No time left in the {budget}s budget for {spec.path}."
                )

            try:
                response = await self._client.request(
                    spec.method,
                    url,
                    headers=headers,
                    json=spec.body,
                    timeout=remaining,
                )
            except httpx.TimeoutException as exc:
                raise APITimeoutError(
                    f"{spec.method} {spec.path} did not complete within {budget}s."
                ) from exc
            except httpx.HTTPError as exc:
                last = _transport_error(spec, self.origin)
                pause = self._pause(attempt, spec, last, deadline)
                if pause is None:
                    raise last from exc
                await anyio.sleep(pause)
                attempt += 1
                continue

            if response.is_success:
                return _decode(response)

            last = self._failure(response)
            pause = self._pause(attempt, spec, last, deadline)
            if pause is None:
                raise last
            await anyio.sleep(pause)
            attempt += 1

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
