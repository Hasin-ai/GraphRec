"""Server-side configuration for the Reel storefront. Nothing here reaches the browser."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = APP_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PACKAGE_DIR / ".env", extra="ignore")

    graphrec_base_url: str = "http://localhost:8010"
    #: Storefront key (events, recommendations, feedback, catalog read). Written by scripts/bootstrap_reel.py.
    graphrec_api_key: str = Field(min_length=1)

    reel_port: int = 5290
    reel_cookie_secure: bool = False
    #: Model version activated by bootstrap_reel.py, shown in the Status tab (the key cannot read versions).
    reel_model_version_id: str = ""
    reel_model_version_tag: str = ""
    #: How bootstrap_reel.py made the version: "checkpoint" (the offline MovieLens checkpoint described by
    #: data/model_card.json) or "trained" (GraphRec trained it on this store's events; the card does not apply).
    reel_model_source: str = "checkpoint"
    reel_tenant_name: str = "Reel"

    graphrec_timeout_seconds: float = 5.0
    graphrec_max_retries: int = 1
    top_n: int = 10

    data_dir: Path = PACKAGE_DIR / "data"
    state_dir: Path = PACKAGE_DIR / "state"
    frontend_dist: Path = PACKAGE_DIR / "frontend" / "dist"

    @field_validator("graphrec_api_key")
    @classmethod
    def _real_key(cls, value: str) -> str:
        if not value.startswith("gr_live_"):
            raise ValueError("GRAPHREC_API_KEY must be a GraphRec API key (gr_live_...). Run scripts/bootstrap_reel.py.")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
