"""Where `/metrics` is served, and why it is not on the API's port.

**Metrics are exposed on a separate listener, never on the application port.**
That is a deliberate decision (ADR 0040) and it buys two things at once:

* §9.1 allows the estate exactly two public ports — 443 on N1 and 443 on N3.
  Anything on the application listener is one Caddy misconfiguration away from
  being public, and a metrics endpoint is a description of the platform's
  internals: route names, tenant identifiers, queue depths. Putting it on its
  own port means the public reverse proxy has no route to it to begin with,
  rather than a rule saying not to.
* The workers are not HTTP servers. A `/metrics` route on FastAPI would leave
  the job worker, the training worker and the reconciler unscrapeable, which is
  where four of §24's six alerts get their data. One mechanism covers all five
  processes.

The server is `prometheus_client`'s own: a daemon thread running a WSGI handler
that does nothing but serialise the registry. It is deliberately not the
application's event loop — a scrape must still answer when the loop is the thing
that is wedged, which is the scrape that matters most.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import start_http_server

from graphrec.common.logging import get_logger
from graphrec.observability.metrics import REGISTRY, record_build_info

if TYPE_CHECKING:
    from graphrec.common.config import Settings

logger = get_logger(__name__)

#: The running server, so a second call is a no-op rather than a port conflict.
#: A module-level singleton because there is exactly one metrics listener per
#: process by definition, and threading a handle through five different app
#: entrypoints would buy nothing.
_started: tuple[str, int] | None = None


def start_metrics_server(settings: Settings, *, app: str, version: str = "0.1.0") -> int | None:
    """Start the exposition listener. Returns the port, or `None` if disabled.

    Failure to bind is logged and swallowed. That is the right trade for this
    endpoint specifically: a job worker that will not start because its metrics
    port was already taken is a worse outage than a job worker nobody can graph,
    and the missing series is itself visible — Prometheus reports the target as
    down, which is the alert.
    """
    global _started

    record_build_info(app, version)

    if not settings.metrics_enabled:
        logger.info("metrics_disabled", extra={"app": app})
        return None

    if _started is not None:
        host, port = _started
        logger.debug("metrics_already_serving", extra={"app": app, "port": port})
        return port

    host = settings.metrics_host
    port = settings.metrics_port
    try:
        start_http_server(port, addr=host, registry=REGISTRY)
    except OSError:
        logger.exception("metrics_server_failed", extra={"app": app, "port": port})
        return None

    _started = (host, port)
    logger.info("metrics_serving", extra={"app": app, "port": port})
    return port


def stop_metrics_server_for_test() -> None:
    """Forget the singleton so another test can start one. Tests only."""
    global _started
    _started = None
