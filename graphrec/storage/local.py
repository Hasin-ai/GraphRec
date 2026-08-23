"""A filesystem artifact store.

Not a test double. `docker-compose.yml` runs one API, one job worker and one
training worker on one host, and a shared volume is a correct object store for
that shape — the S3 adapter exists for the deployment where they are not on one
host, and choosing between them is a setting.

The one property worth stating: **a put is atomic**. Writing straight to the
destination would leave a half-written checkpoint behind a process that died
mid-write, and the next resume would load it and fail a digest check it could
not distinguish from tampering. So the write goes to a sibling temporary file
and `os.replace` renames it, which POSIX makes atomic within a filesystem. The
same reasoning, and very nearly the same code, as
`graphrec.ml.train.checkpoint.save_checkpoint`.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

from graphrec.storage.store import StorageError, digest_bytes, digest_file, verify


class LocalArtifactStore:
    """Objects as files under `root`. `root` is created on first use."""

    def __init__(self, root: pathlib.Path | str) -> None:
        self._root = pathlib.Path(root)

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def _path(self, key: str) -> pathlib.Path:
        # A key with `..` in it would escape the root, and the only way one gets
        # here is a stored `uri` somebody edited. Refused rather than normalised:
        # normalising would silently read a different object than the row names.
        if key.startswith("/") or ".." in pathlib.PurePosixPath(key).parts:
            raise StorageError(f"{key!r} is not a storable key")
        return self._root / key

    def put_bytes(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, data)
        return digest_bytes(data)

    def get_bytes(self, key: str, *, expected_digest: str | None = None) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"{key} is not in the store")
        data = path.read_bytes()
        verify(digest_bytes(data), expected_digest, key=key)
        return data

    def put_file(self, key: str, path: pathlib.Path) -> str:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".partial")
        os.close(handle)
        temporary_path = pathlib.Path(temporary)
        try:
            shutil.copyfile(path, temporary_path)
            os.replace(temporary_path, destination)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError(f"could not store {key}") from exc
        return digest_file(destination)

    def get_file(self, key: str, path: pathlib.Path, *, expected_digest: str | None = None) -> None:
        source = self._path(key)
        if not source.is_file():
            raise StorageError(f"{key} is not in the store")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        # Verified *after* the copy, on the copy. Verifying the source would
        # attest to a file the caller is not about to open.
        verify(digest_file(path), expected_digest, key=key)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def uri(self, key: str) -> str:
        return self._path(key).resolve().as_uri()

    def _atomic_write(self, path: pathlib.Path, data: bytes) -> None:
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".partial")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.replace(temporary, path)
        except OSError as exc:
            pathlib.Path(temporary).unlink(missing_ok=True)
            raise StorageError(f"could not write {path.name}") from exc


__all__ = ["LocalArtifactStore"]
