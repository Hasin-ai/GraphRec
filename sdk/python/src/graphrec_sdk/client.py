"""The client, in two flavours, each holding two transports.

Each namespace is constructed with the transport for its plane and there is no
way to hand it the other one. That is the point: the two hosts are not
interchangeable, N3 answers only `/v1/recommendations*` and `/v1/feedback*`
(`deploy/n3/Caddyfile` returns 404 for everything else), and a mistake here
would produce a 404 with nothing in it to explain why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._spec import CallOptions
from .config import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    ResolvedConfig,
    resolve_config,
)
from .resources import (
    AsyncCatalog,
    AsyncEvents,
    AsyncFeedback,
    AsyncRecommendations,
    AsyncSubmissions,
    Catalog,
    Events,
    Feedback,
    Recommendations,
    Submissions,
)
from .transport import AsyncTransport, Transport

if TYPE_CHECKING:
    from types import TracebackType

    import httpx

__all__ = ["AsyncGraphRec", "CallOptions", "GraphRec"]


class _Common:
    _config: ResolvedConfig

    @property
    def hosts(self) -> dict[str, str]:
        """The two origins this client resolved. Useful in a startup log line."""
        return {"control": self._config.control_origin, "data": self._config.data_origin}

    @property
    def credential_prefix(self) -> str:
        """`gr_live_XXXX`. Public, and how a support conversation names a key."""
        return self._config.credential.prefix

    def __repr__(self) -> str:
        # The credential renders itself redacted; this is explicit about it
        # anyway, because the day someone adds a plain field is the day
        # incidental containment stops being enough.
        return (
            f"{type(self).__name__}(control={self._config.control_origin!r}, "
            f"data={self._config.data_origin!r}, credential={self._config.credential})"
        )


class GraphRec(_Common):
    """The blocking client.

    ``timeout`` is a budget for the whole call including retries, in **seconds**.
    ``max_retries`` is extra attempts after the first, and applies only to calls
    that carry an idempotency identifier — which, on this API, is all of them.
    """

    def __init__(
        self,
        *,
        api_key: str,
        tenant_id: str,
        domain: str | None = None,
        console_domain: str | None = None,
        api_domain: str | None = None,
        control_url: str | None = None,
        data_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_agent: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = resolve_config(
            api_key=api_key,
            tenant_id=tenant_id,
            domain=domain,
            console_domain=console_domain,
            api_domain=api_domain,
            control_url=control_url,
            data_url=data_url,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self._control = Transport(self._config.control_origin, self._config, http_client)
        self._data = Transport(self._config.data_origin, self._config, http_client)

        self.catalog = Catalog(self._control)
        self.events = Events(self._control)
        self.submissions = Submissions(self._control)
        self.recommendations = Recommendations(self._data)
        self.feedback = Feedback(self._data)

    def close(self) -> None:
        self._control.close()
        self._data.close()

    def __enter__(self) -> GraphRec:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class AsyncGraphRec(_Common):
    """The awaiting client. Same surface, same arguments, `async def` methods."""

    def __init__(
        self,
        *,
        api_key: str,
        tenant_id: str,
        domain: str | None = None,
        console_domain: str | None = None,
        api_domain: str | None = None,
        control_url: str | None = None,
        data_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_agent: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = resolve_config(
            api_key=api_key,
            tenant_id=tenant_id,
            domain=domain,
            console_domain=console_domain,
            api_domain=api_domain,
            control_url=control_url,
            data_url=data_url,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self._control = AsyncTransport(self._config.control_origin, self._config, http_client)
        self._data = AsyncTransport(self._config.data_origin, self._config, http_client)

        self.catalog = AsyncCatalog(self._control)
        self.events = AsyncEvents(self._control)
        self.submissions = AsyncSubmissions(self._control)
        self.recommendations = AsyncRecommendations(self._data)
        self.feedback = AsyncFeedback(self._data)

    async def aclose(self) -> None:
        await self._control.aclose()
        await self._data.aclose()

    async def __aenter__(self) -> AsyncGraphRec:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
