from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = APP_DIR.parent


class Settings(BaseSettings):
    """Server-side configuration. Nothing here is ever sent to the browser."""

    model_config = SettingsConfigDict(env_file=PACKAGE_DIR / ".env", extra="ignore")

    graphrec_base_url: str = "http://localhost:8010"
    graphrec_api_key: str = Field(min_length=1)
    graphrec_seed_api_key: str = ""

    demo_port: int = 5190
    demo_disable_missing: bool = False
    demo_cookie_secure: bool = False

    #: Only ``True`` after ``scripts/verify_personalization.py`` passed for ``model_proof_version_id``.
    model_proof_verified: bool = False
    model_proof_version_id: str = ""

    #: Page-path bounds: keep the storefront responsive even when GraphRec is slow.
    graphrec_timeout_seconds: float = 2.0
    graphrec_max_retries: int = 1
    catalog_cache_seconds: float = 30.0

    frontend_dist: Path = PACKAGE_DIR / "frontend" / "dist"

    @field_validator("graphrec_api_key")
    @classmethod
    def _real_key(cls, value: str) -> str:
        if not value.startswith("gr_live_") or "replace_me" in value:
            raise ValueError(
                "GRAPHREC_API_KEY must be a real GraphRec API key (gr_live_...). "
                "Create one in the operator console or with scripts/bootstrap_tenant.py."
            )
        return value

    @property
    def seed_api_key(self) -> str:
        return self.graphrec_seed_api_key or self.graphrec_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
