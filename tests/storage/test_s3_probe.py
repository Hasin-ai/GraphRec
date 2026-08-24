"""The S3 adapter's readiness probe.

`S3ArtifactStore` is the adapter the deployment actually runs — the default for
`artifact_store` is S3, and the Compose stack points it at MinIO — so its probe
is the one `/readyz` calls in production. It is tested here against an injected
client rather than a live endpoint, because what needs proving is the two
outcomes and the error narrowing, not that boto3 can reach a socket. The live
path is exercised by `tests/api/test_health.py`, which runs against the MinIO in
`docker-compose.yml`.
"""

from __future__ import annotations

from typing import Any

import pytest

from graphrec.storage.s3 import S3ArtifactStore
from graphrec.storage.store import StorageError


class _Client:
    """A stand-in for boto3's client, recording what it was asked."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_bucket", kwargs))
        if self._raises is not None:
            raise self._raises
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_object", kwargs))
        if self._raises is not None:
            raise self._raises
        return {}


def _store(client: _Client) -> S3ArtifactStore:
    return S3ArtifactStore(
        endpoint="http://storage.internal:9000",
        access_key="key",
        secret_key="secret",
        bucket="graphrec",
        client=client,
    )


def test_a_reachable_bucket_probes_clean() -> None:
    client = _Client()

    _store(client).probe()

    assert client.calls == [("head_bucket", {"Bucket": "graphrec"})]


def test_the_bucket_is_probed_not_a_key() -> None:
    """`head_object` on a well-known key would conflate two different failures.

    An empty bucket has no such key, so a missing-key 404 and an unreachable
    endpoint would both have to be interpreted, and the interpretation is the
    part that gets it wrong. `head_bucket` succeeds on an empty bucket and
    fails on a missing one, which is the question readiness is asking.
    """
    client = _Client()

    _store(client).probe()

    assert [name for name, _ in client.calls] == ["head_bucket"]


def test_an_unreachable_endpoint_becomes_a_storage_error() -> None:
    """Narrowed at the boundary, like every other call in this adapter."""
    client = _Client(raises=OSError("connect timeout"))

    with pytest.raises(StorageError) as caught:
        _store(client).probe()

    assert caught.value.__cause__ is not None


def test_the_message_does_not_carry_the_endpoint() -> None:
    """`/readyz` is unauthenticated, and this message is the closest a
    connection detail gets to a response body (NR-NF-06).

    The handler in `apps/control_api/routers/health.py` replaces it with
    "unreachable" regardless, but a message that never held the host in the
    first place cannot be leaked by a future handler that forgets to.
    """
    client = _Client(raises=OSError("could not connect to storage.internal:9000"))

    with pytest.raises(StorageError) as caught:
        _store(client).probe()

    assert "storage.internal" not in str(caught.value)
    assert "graphrec" in str(caught.value)
