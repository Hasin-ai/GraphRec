"""The single credentialed GraphRec client plus local stores, created in the lifespan."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from graphrec_sdk import AsyncGraphRec

from .config import Settings
from .store import Films, LastLists, LiveLog, Shoppers


@dataclass
class Services:
    client: Any
    films: Films
    shoppers: Shoppers
    live: LiveLog
    settings: Settings
    model_card: dict
    last_lists: LastLists = field(default_factory=LastLists)
    #: request_id -> impression feedback event id (links clicks to impressions).
    impressions: dict = field(default_factory=dict)

    async def close(self) -> None:
        await self.client.close()


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


def build_local(settings: Settings, client: Any) -> Services:
    return Services(
        client=client,
        films=Films(settings.data_dir / "films.json"),
        shoppers=Shoppers(settings.data_dir / "personas.json"),
        live=LiveLog(settings.state_dir),
        settings=settings,
        model_card=json.loads((settings.data_dir / "model_card.json").read_text(encoding="utf-8")),
    )
