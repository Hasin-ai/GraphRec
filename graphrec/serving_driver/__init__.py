"""Orchestration adapters — ADR 0028.

The port is `driver`; the adapters are `compose`. `build_serving_driver` is the
selector, and it refuses `k3s` by name rather than silently falling back, for
the reason `graphrec.ml.index.build_candidate_index` refuses `qdrant`: a
deferred adapter that quietly becomes the shipped one is a deferral nobody finds
out about until the demonstration it was deferred for.
"""

from __future__ import annotations

from graphrec.common.config import ServingDriverKind
from graphrec.serving_driver.compose import ComposeDriver, InProcessDriver, project_name
from graphrec.serving_driver.driver import (
    DesiredState,
    DriverError,
    DriverInfo,
    Observation,
    ReplicaObservation,
    ServingDriver,
)


def build_serving_driver(kind: ServingDriverKind, *, compose_file: str) -> ServingDriver:
    if kind is ServingDriverKind.COMPOSE:
        return ComposeDriver(compose_file=compose_file)
    msg = (
        f"serving_driver={kind.value} selects an adapter that is not built. "
        "See ADR 0028: the port exists, the k3s implementation is deferred. "
        f"Set serving_driver={ServingDriverKind.COMPOSE.value}."
    )
    raise NotImplementedError(msg)


__all__ = [
    "ComposeDriver",
    "DesiredState",
    "DriverError",
    "DriverInfo",
    "InProcessDriver",
    "Observation",
    "ReplicaObservation",
    "ServingDriver",
    "build_serving_driver",
    "project_name",
]
