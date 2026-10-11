"""Server-side configuration for the Reel storefront. Nothing here reaches the browser."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

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

    #: Public base URL of the RustFS bucket holding the film covers, as the *browser* reaches it,
    #: e.g. http://localhost:9000/reel-covers. Empty = no covers (tiles keep the coloured placeholder).
    #: The objects are listed in data/covers.json (film id -> object key), written by scripts/upload_covers.py.
    reel_covers_base_url: str = ""

    graphrec_timeout_seconds: float = 5.0
    graphrec_max_retries: int = 1
    top_n: int = 10

    data_dir: Path = PACKAGE_DIR / "data"
    state_dir: Path = PACKAGE_DIR / "state"
    frontend_dist: Path = PACKAGE_DIR / "frontend" / "dist"

    redis_url: Optional[str] = None
    reel_secret_key: str = "reel-dev-secret-key-please-change-in-production-min32"
    reel_env: str = "development"
    reel_log_format: str = "json"
    reel_metrics_token: Optional[str] = None
    reel_rate_limit_per_minute: int = 120
    reel_body_limit_bytes: int = 65536
    reel_allowed_origins: list[str] = [
        "http://localhost:5290",
        "http://127.0.0.1:5290",
        "http://localhost:5291",
        "http://127.0.0.1:5291",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
    ]

    @field_validator("graphrec_api_key")
    @classmethod
    def _real_key(cls, value: str) -> str:
        if not value.startswith("gr_live_"):
            raise ValueError("GRAPHREC_API_KEY must be a GraphRec API key (gr_live_...). Run scripts/bootstrap_reel.py.")
        return value

    def check_production_safety(self) -> None:
        if self.reel_env == "production":
            if not self.reel_cookie_secure:
                raise ValueError("REEL_COOKIE_SECURE must be True when REEL_ENV=production.")
            if self.reel_secret_key == "reel-dev-secret-key-please-change-in-production-min32":
                raise ValueError("REEL_SECRET_KEY must be configured with a secure key in production.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
