"""The sync and async facades are the same surface, method for method.

`resources/__init__.py` explains why the duplication exists: all the logic lives
in module-level spec builders and decoders, and the two classes differ only in
whether they `await`. Prose alone does not hold that — a method added to one and
forgotten on the other is a silent, permanent divergence that only shows up as an
`AttributeError` in a customer's async service. This file is what holds it.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from graphrec_sdk import AsyncGraphRec, GraphRec
from tests.sdk.conftest import DOMAIN, KEY, TENANT

NAMESPACES = ["catalog", "events", "submissions", "recommendations", "feedback"]

SYNC = GraphRec(api_key=KEY, tenant_id=TENANT, domain=DOMAIN)
ASYNC = AsyncGraphRec(api_key=KEY, tenant_id=TENANT, domain=DOMAIN)


def _methods(obj: object) -> dict[str, Any]:
    return {
        name: getattr(obj, name)
        for name in dir(obj)
        if not name.startswith("_") and callable(getattr(obj, name))
    }


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_both_clients_expose_the_namespace(namespace: str) -> None:
    assert hasattr(SYNC, namespace)
    assert hasattr(ASYNC, namespace)


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_the_two_facades_have_the_same_method_names(namespace: str) -> None:
    assert _methods(getattr(SYNC, namespace)).keys() == _methods(getattr(ASYNC, namespace)).keys()


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_the_two_facades_have_the_same_signatures(namespace: str) -> None:
    for name, blocking in _methods(getattr(SYNC, namespace)).items():
        awaited = getattr(getattr(ASYNC, namespace), name)
        assert inspect.signature(blocking) == inspect.signature(awaited), name


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_only_the_async_facade_is_awaitable(namespace: str) -> None:
    for name, blocking in _methods(getattr(SYNC, namespace)).items():
        assert not inspect.iscoroutinefunction(blocking), f"{namespace}.{name}"
        assert inspect.iscoroutinefunction(getattr(getattr(ASYNC, namespace), name)), name


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_every_method_is_documented(namespace: str) -> None:
    # The docstring is where the scope a call needs, and the status it answers
    # with, are written. An undocumented method is one a caller has to guess at.
    for name, blocking in _methods(getattr(SYNC, namespace)).items():
        assert (blocking.__doc__ or "").strip(), f"{namespace}.{name}"


def test_the_method_table_is_not_empty() -> None:
    # A floor. Without it, a namespace that lost all its methods would pass every
    # comparison above by comparing two empty sets.
    total = sum(len(_methods(getattr(SYNC, name))) for name in NAMESPACES)
    assert total >= 10, total


def test_the_two_clients_expose_the_same_properties() -> None:
    def properties(cls: type) -> set[str]:
        return {name for name, value in vars(cls).items() if isinstance(value, property)}

    # `_Common` carries both, so this is really a check that neither subclass
    # shadowed one of them with something narrower.
    assert properties(GraphRec) | properties(AsyncGraphRec) <= {"hosts", "credential_prefix"}
    assert SYNC.hosts == ASYNC.hosts
    assert SYNC.credential_prefix == ASYNC.credential_prefix


def test_each_client_closes_the_way_its_world_expects() -> None:
    assert not inspect.iscoroutinefunction(GraphRec.close)
    assert inspect.iscoroutinefunction(AsyncGraphRec.aclose)
    for name in ("__enter__", "__exit__"):
        assert hasattr(GraphRec, name), name
    for name in ("__aenter__", "__aexit__"):
        assert hasattr(AsyncGraphRec, name), name


def test_the_barrel_exports_what_it_claims_to() -> None:
    import graphrec_sdk

    missing = [name for name in graphrec_sdk.__all__ if not hasattr(graphrec_sdk, name)]
    assert missing == []
    assert len(graphrec_sdk.__all__) == len(set(graphrec_sdk.__all__))
