"""The S3-compatible adapter.

MinIO or RustFS in this deployment (BUILD_PROMPT §Object storage); the API is
the same and so is this code. `use_path_style` is on by default because a
self-hosted endpoint has no wildcard DNS to make virtual-host addressing work,
and discovering that at the first upload is a bad afternoon.

boto3 is imported lazily, inside the constructor. The training worker needs it;
the control API, the test suite and every unit test that touches
`graphrec.storage` do not, and a module-level import would make a ~50 ms botocore
load part of importing anything that mentions storage.

Errors are narrowed to `StorageError` at the boundary. A `ClientError` carrying
a bucket name and a request id is exactly the kind of thing NR-NF-06 does not
want propagating toward a response body, and callers upstream need one exception
type to decide whether an attempt was worth spending.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graphrec.storage.store import StorageError, digest_bytes, digest_file, verify

if TYPE_CHECKING:
    import pathlib


class S3ArtifactStore:
    """One bucket, addressed by key."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        use_path_style: bool = True,
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint = endpoint.rstrip("/")
        if client is not None:
            self._client = client
            return
        import boto3  # see the module docstring
        from botocore.config import Config

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(s3={"addressing_style": "path" if use_path_style else "virtual"}),
        )

    def put_bytes(self, key: str, data: bytes) -> str:
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except Exception as exc:
            raise StorageError(f"could not store {key}") from exc
        return digest_bytes(data)

    def get_bytes(self, key: str, *, expected_digest: str | None = None) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            data: bytes = response["Body"].read()
        except Exception as exc:
            raise StorageError(f"could not read {key}") from exc
        verify(digest_bytes(data), expected_digest, key=key)
        return data

    def put_file(self, key: str, path: pathlib.Path) -> str:
        # Hashed before the upload rather than after. There is no
        # read-back-and-verify step here — that would double the transfer on
        # every checkpoint — so the digest attests to what was sent, and the
        # matching check happens on the way out at `get_file`.
        checksum = digest_file(path)
        try:
            self._client.upload_file(str(path), self._bucket, key)
        except Exception as exc:
            raise StorageError(f"could not store {key}") from exc
        return checksum

    def get_file(self, key: str, path: pathlib.Path, *, expected_digest: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self._bucket, key, str(path))
        except Exception as exc:
            raise StorageError(f"could not read {key}") from exc
        verify(digest_file(path), expected_digest, key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            # Deliberately broad. `head_object` reports a missing key as a
            # `ClientError` with a 404 in it and a missing bucket as a different
            # `ClientError`, and both mean the same thing to a caller asking
            # whether it can read the object.
            return False
        return True

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"could not delete {key}") from exc

    def uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"


__all__ = ["S3ArtifactStore"]
