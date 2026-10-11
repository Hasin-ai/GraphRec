"""The single credentialed GraphRec client plus local and shared stores, created in the lifespan."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from graphrec_sdk import AsyncGraphRec

from .config import Settings
from .storage import SharedState
from .store import Films, LiveLog, Shoppers


class StorageLastLists:
    """Delegates to SharedState (Redis or memory) for cross-worker diffing."""

    def __init__(self, storage: SharedState) -> None:
        self._storage = storage

    def swap(self, shopper: str, shelf: str, ids: List[str]) -> Optional[List[str]]:
        return self._storage.swap_last_list(shopper, shelf, ids)


class StorageImpressions(dict):
    """Delegates to SharedState for cross-worker impression attribution."""

    def __init__(self, storage: SharedState) -> None:
        super().__init__()
        self._storage = storage

    def __getitem__(self, key: str) -> Optional[str]:
        return self._storage.get_impression(key)

    def __setitem__(self, key: str, value: str) -> None:
        self._storage.set_impression(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        val = self._storage.get_impression(key)
        return val if val is not None else default


@dataclass
class Services:
    client: Any
    films: Films
    shoppers: Shoppers
    live: LiveLog
    settings: Settings
    model_card: dict
    storage: SharedState
    last_lists: StorageLastLists = field(init=False)
    impressions: StorageImpressions = field(init=False)

    def __post_init__(self) -> None:
        self.last_lists = StorageLastLists(self.storage)
        self.impressions = StorageImpressions(self.storage)

    async def close(self) -> None:
        if hasattr(self.client, "close"):
            await self.client.close()
        self.storage.close()


def build_services(settings: Settings) -> Services:
    client = AsyncGraphRec(
        base_url=settings.graphrec_base_url,
        api_key=settings.graphrec_api_key,
        timeout=httpx.Timeout(settings.graphrec_timeout_seconds, connect=2.0),
        max_retries=settings.graphrec_max_retries,
        default_headers={"X-Demo-App": "reel-storefront"},
        use_env=False,
    )
    return build_local(settings, client)


def load_covers(settings: Settings) -> Dict[str, str]:
    """Film id -> public cover URL in the RustFS bucket (empty when covers are not configured)."""

    base = settings.reel_covers_base_url.rstrip("/")
    manifest = settings.data_dir / "covers.json"
    if not base or not manifest.is_file():
        return {}
    keys: Dict[str, str] = json.loads(manifest.read_text(encoding="utf-8"))
    return {film_id: f"{base}/{key}" for film_id, key in keys.items()}


def build_local(settings: Settings, client: Any) -> Services:
    storage = SharedState(redis_url=settings.redis_url)
    return Services(
        client=client,
        films=Films(settings.data_dir / "films.json", covers=load_covers(settings)),
        shoppers=Shoppers(settings.data_dir / "personas.json"),
        live=LiveLog(settings.state_dir),
        settings=settings,
        model_card=json.loads((settings.data_dir / "model_card.json").read_text(encoding="utf-8")),
        storage=storage,
    )
