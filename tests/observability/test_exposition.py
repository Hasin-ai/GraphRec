"""The metrics listener: which port it is on, and what it does when it cannot bind.

The property under test is the one that keeps §9.1's "two public ports" true —
metrics are on a listener of their own and never on the application's — plus the
decision that a failure to expose metrics must not take a process down.
"""

from __future__ import annotations

import socket
import urllib.request

import pytest

from graphrec.observability.exposition import (
    start_metrics_server,
    stop_metrics_server_for_test,
)
from graphrec.observability.metrics import reset_metrics_for_test


@pytest.fixture(autouse=True)
def _clean():
    stop_metrics_server_for_test()
    reset_metrics_for_test()
    yield
    stop_metrics_server_for_test()
    reset_metrics_for_test()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_metrics_are_served_on_their_own_port(settings) -> None:
    """Not a route on the API. A scrape of this port returns the exposition."""
    port = _free_port()
    configured = settings.model_copy(
        update={"metrics_enabled": True, "metrics_host": "127.0.0.1", "metrics_port": port}
    )

    assert start_metrics_server(configured, app="test_app", version="9.9.9") == port

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
        body = response.read().decode()
    assert 'graphrec_build_info{app="test_app",version="9.9.9"} 1.0' in body


def test_disabling_it_still_records_what_is_running(settings) -> None:
    """`metrics_enabled=0` turns off the listener, not the instrumentation.

    The distinction matters for the test suite, which runs with the listener off
    and would otherwise be asserting against code paths that never execute in
    production.
    """
    configured = settings.model_copy(update={"metrics_enabled": False})

    assert start_metrics_server(configured, app="test_app") is None

    from graphrec.observability.metrics import REGISTRY

    published = {
        sample.labels.get("app")
        for metric in REGISTRY.collect()
        for sample in metric.samples
        if sample.name == "graphrec_build_info"
    }
    assert published == {"test_app"}


def test_a_port_already_taken_is_logged_not_raised(settings) -> None:
    """A worker that will not start because its metrics port is busy is a worse
    outage than a worker nobody can graph.

    And the missing series is not silent: Prometheus reports the target as down,
    which is itself the alert.
    """
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = int(taken.getsockname()[1])
        configured = settings.model_copy(
            update={"metrics_enabled": True, "metrics_host": "127.0.0.1", "metrics_port": port}
        )

        assert start_metrics_server(configured, app="test_app") is None


def test_starting_twice_does_not_take_a_second_port(settings) -> None:
    """A process has one metrics listener by definition.

    The control API calls this from `lifespan`, and a test suite that creates
    twenty apps would otherwise leave twenty threads and exhaust the port on the
    second one.
    """
    port = _free_port()
    configured = settings.model_copy(
        update={"metrics_enabled": True, "metrics_host": "127.0.0.1", "metrics_port": port}
    )

    first = start_metrics_server(configured, app="test_app")
    second = start_metrics_server(configured, app="test_app")

    assert first == second == port
