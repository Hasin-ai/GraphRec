from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Dict, Optional, Tuple, Union, cast
from uuid import UUID

from .._base_client import FileTuple
from ..errors import InputValidationError
from ..models.datasets import DatasetSnapshot, DatasetSnapshotList, DatasetUploadResult
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncDatasets", "Datasets", "FileInput"]

#: A path, raw bytes, a binary file object, or ``(filename, bytes)``.
FileInput = Union[str, "os.PathLike[str]", bytes, IO[bytes], Tuple[str, bytes]]

_CONTENT_TYPES = {".json": "application/json", ".csv": "text/csv", ".jsonl": "application/json"}


def _read_file(
    file: FileInput, filename: Optional[str], content_type: Optional[str]
) -> Dict[str, FileTuple]:
    name: Optional[str]
    if isinstance(file, tuple):
        name, data = file
    elif isinstance(file, bytes):
        name, data = filename or "dataset.json", file
    elif isinstance(file, (str, os.PathLike)):
        path = Path(file)
        name, data = path.name, path.read_bytes()
    elif hasattr(file, "read"):
        data = file.read()
        raw_name = getattr(file, "name", None)
        name = os.path.basename(raw_name) if isinstance(raw_name, str) else None
    else:
        raise InputValidationError(
            "file must be a path, bytes, a binary file object or (name, bytes)"
        )
    if not isinstance(data, bytes):
        raise InputValidationError("Dataset files must be read in binary mode")
    final_name = filename or name or "dataset.json"
    suffix = Path(final_name).suffix.lower()
    final_type = (
        content_type
        or _CONTENT_TYPES.get(suffix)
        or mimetypes.guess_type(final_name)[0]
        or "application/octet-stream"
    )
    return {"file": (final_name, data, final_type)}


def _snapshot_body(cutoff_at: Optional[datetime], description: Optional[str]) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if cutoff_at is not None:
        body["cutoff_at"] = cutoff_at
    if description is not None:
        body["description"] = description
    return body


class Datasets(SyncResource):
    """Training data preparation. Scopes: ``training:write`` / ``training:read``."""

    def upload(
        self,
        file: FileInput,
        *,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> DatasetUploadResult:
        """Import a JSON or CSV export of products and/or events, then snapshot it.

        ``POST /v1/datasets/upload`` (multipart, up to the server's
        ``MAX_UPLOAD_BODY_BYTES``). JSON may be ``{"products": [...], "events": [...]}``
        or a list of records; CSV needs a header row. Records with ``event_id``
        are events, records with ``external_id`` are products, and ``context`` /
        ``metadata`` CSV cells may contain JSON. One invalid record rejects the
        whole file with :class:`~graphrec_sdk.RequestValidationError`.
        """

        return cast(
            DatasetUploadResult,
            self._client.request(
                "datasets.upload",
                files=_read_file(file, filename, content_type),
                cast_to=DatasetUploadResult,
            ),
        )

    def create_snapshot(
        self, *, cutoff_at: Optional[datetime] = None, description: Optional[str] = None
    ) -> DatasetSnapshot:
        """Freeze the tenant's current data (up to ``cutoff_at``) for training.

        ``POST /v1/datasets/snapshots``.
        """

        return cast(
            DatasetSnapshot,
            self._client.request(
                "datasets.create_snapshot",
                json=_snapshot_body(cutoff_at, description),
                cast_to=DatasetSnapshot,
            ),
        )

    def list_snapshots(self) -> DatasetSnapshotList:
        """``GET /v1/datasets/snapshots``, newest first."""

        return cast(
            DatasetSnapshotList,
            self._client.request("datasets.list_snapshots", cast_to=DatasetSnapshotList),
        )

    def get_snapshot(self, snapshot_id: Union[str, UUID]) -> DatasetSnapshot:
        """``GET /v1/datasets/snapshots/{snapshot_id}``."""

        return cast(
            DatasetSnapshot,
            self._client.request(
                "datasets.get_snapshot",
                path_params={"snapshot_id": snapshot_id},
                cast_to=DatasetSnapshot,
            ),
        )


class AsyncDatasets(AsyncResource):
    async def upload(
        self,
        file: FileInput,
        *,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> DatasetUploadResult:
        """Async variant of :meth:`Datasets.upload` (the file is read synchronously)."""

        return cast(
            DatasetUploadResult,
            await self._client.request(
                "datasets.upload",
                files=_read_file(file, filename, content_type),
                cast_to=DatasetUploadResult,
            ),
        )

    async def create_snapshot(
        self, *, cutoff_at: Optional[datetime] = None, description: Optional[str] = None
    ) -> DatasetSnapshot:
        """Async variant of :meth:`Datasets.create_snapshot`."""

        return cast(
            DatasetSnapshot,
            await self._client.request(
                "datasets.create_snapshot",
                json=_snapshot_body(cutoff_at, description),
                cast_to=DatasetSnapshot,
            ),
        )

    async def list_snapshots(self) -> DatasetSnapshotList:
        """Async variant of :meth:`Datasets.list_snapshots`."""

        return cast(
            DatasetSnapshotList,
            await self._client.request("datasets.list_snapshots", cast_to=DatasetSnapshotList),
        )

    async def get_snapshot(self, snapshot_id: Union[str, UUID]) -> DatasetSnapshot:
        """Async variant of :meth:`Datasets.get_snapshot`."""

        return cast(
            DatasetSnapshot,
            await self._client.request(
                "datasets.get_snapshot",
                path_params={"snapshot_id": snapshot_id},
                cast_to=DatasetSnapshot,
            ),
        )
