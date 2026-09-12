from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._base_client import AsyncAPIClient, SyncAPIClient


class SyncResource:
    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client


class AsyncResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client
