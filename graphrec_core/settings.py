from __future__ import annotations

from functools import lru_cache

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ``development`` keeps local defaults and development-only features
    # (placeholder training, manual model registration). ``production`` refuses
    # to start with default, placeholder or short secrets (A-10).
    graphrec_env: Literal["development", "production"] = "development"

    database_url: str = "postgresql+psycopg://graphrec_app:graphrec_app_local_only@localhost:5432/graphrec"
    # Connection pool sized for uvicorn's 40-thread sync pool per process.
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=20, ge=0, le=400)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    # Applied to every connection; the worker's long snapshot reads stay well below it.
    db_statement_timeout_ms: int = Field(default=30_000, ge=100, le=3_600_000)
    audit_hash_secret: str = Field(default="local-development-only", min_length=16)
    jwt_signing_secret: str = Field(default="local-jwt-development-secret-change-me", min_length=32)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3_600)
    refresh_token_ttl_seconds: int = Field(default=604_800, ge=3_600)
    login_rate_limit: int = Field(default=8, ge=1)
    login_rate_window_seconds: int = Field(default=60, ge=1)
    subscription_rate_limit: int = Field(default=30, ge=1)
    subscription_rate_window_seconds: int = Field(default=60, ge=1)
    usage_rate_limit: int = Field(default=30, ge=1)
    usage_rate_window_seconds: int = Field(default=60, ge=1)
    api_key_hmac_pepper: str = Field(
        default="local-api-key-hmac-pepper-change-me", min_length=32
    )
    api_key_hash_version: int = Field(default=1, ge=1)
    api_key_rate_limit: int = Field(default=10, ge=1)
    api_key_rate_window_seconds: int = Field(default=60, ge=1)
    max_active_api_keys_per_tenant: int = Field(default=25, ge=1)
    max_api_key_name_length: int = Field(default=100, ge=1, le=100)
    max_api_key_scopes: int = Field(default=12, ge=1, le=12)
    max_api_key_rotation_reason_length: int = Field(default=500, ge=1, le=500)
    max_api_key_grace_seconds: int = Field(default=86_400, ge=0, le=86_400)
    registration_rate_limit: int = Field(default=5, ge=1)
    registration_rate_window_seconds: int = Field(default=60, ge=1)
    max_request_body_bytes: int = Field(default=16_384, ge=1_024)
    max_upload_body_bytes: int = Field(default=10_485_760, ge=1_024)
    # Batch endpoints accept up to 1,000 items; 16 KiB fits only ~100 events.
    max_bulk_body_bytes: int = Field(default=1_048_576, ge=1_024)
    max_tenant_name_length: int = Field(default=200, ge=1)
    max_idempotency_key_length: int = Field(default=255, ge=16)
    max_password_length: int = Field(default=1_024, ge=64)
    account_setup_token_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)
    training_cooldown_seconds: int = Field(default=60, ge=0, le=86_400)
    # XR-F-02/03 scheduler: shortest allowed schedule and how often policies are evaluated.
    retraining_min_interval_minutes: int = Field(default=60, ge=1, le=43_200)
    scheduler_tick_seconds: int = Field(default=15, ge=1, le=3_600)
    # XR-F-08 capacity policy: logical serving replicas, each worth
    # ceil(plan concurrency / plan maximum replicas) recommendation slots;
    # scale up immediately, scale down only after the stabilization window.
    capacity_target_rpm_per_replica: int = Field(default=120, ge=1, le=1_000_000)
    capacity_scale_down_stabilization_seconds: int = Field(default=120, ge=0, le=86_400)
    # D16 admission control: shared Redis for recommendation rate limits and
    # concurrency slots. Redis errors fail open to a per-process fallback.
    redis_url: str | None = "redis://localhost:6379/0"
    redis_timeout_ms: int = Field(default=30, ge=5, le=1_000)
    slot_wait_ms: int = Field(default=100, ge=0, le=5_000)
    slot_lease_seconds: int = Field(default=30, ge=1, le=600)
    # A-01: proxies whose X-Forwarded-For is trusted for the client address used by
    # per-source limits. Comma-separated IPs/CIDRs, or "*" when the API is reachable
    # only through the bundled nginx (never publish the API port with "*").
    forwarded_allow_ips: str = "127.0.0.1"
    # Shared secret for /v1/platform routes; unset disables platform administration.
    platform_admin_token: str | None = None

    # Qdrant vector store
    qdrant_url: str = Field(default="http://localhost:6334")
    qdrant_collection_prefix: str = Field(default="graphrec")
    qdrant_embedding_dim: int = Field(default=128, ge=16, le=4096)
    qdrant_top_k: int = Field(default=100, ge=1, le=1000)

    # DGSR model artifacts. A training job with ``configuration.pretrained_artifact``
    # imports ``<model_artifact_root>/<name>/`` (best.pt, config.json, id_maps.json,
    # interactions.npz) instead of training; unset disables imports.
    model_artifact_root: str | None = None
    generated_model_root: str = "/app/generated_artifacts"

    @field_validator("platform_admin_token", mode="before")
    @classmethod
    def _blank_token_disables_platform(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if len(value) < 32:
                raise ValueError("PLATFORM_ADMIN_TOKEN must be at least 32 characters")
        return value

    @field_validator("jwt_signing_secret", "platform_admin_token")
    @classmethod
    def _reject_example_placeholders(cls, value: object) -> object:
        # Values copied verbatim from .env.example are public; refuse to start with them.
        if isinstance(value, str) and "replace-with" in value.lower():
            raise ValueError(
                "secret still uses the .env.example placeholder; generate a random value"
            )
        return value


    @property
    def is_production(self) -> bool:
        return self.graphrec_env == "production"

    @model_validator(mode="after")
    def _production_requires_strong_secrets(self) -> "Settings":
        if not self.is_production:
            return self
        problems: list[str] = []
        defaults = {name: field.default for name, field in type(self).model_fields.items()}
        for name in ("jwt_signing_secret", "audit_hash_secret", "api_key_hmac_pepper"):
            value = getattr(self, name)
            if value == defaults[name] or _looks_like_placeholder(value) or len(value) < 32:
                problems.append(f"{name.upper()} must be a unique random value of at least 32 characters")
        if self.platform_admin_token is not None and _looks_like_placeholder(self.platform_admin_token):
            problems.append("PLATFORM_ADMIN_TOKEN must not be a placeholder")
        if self.database_url == defaults["database_url"] or "local_only" in self.database_url:
            problems.append("DATABASE_URL must not use the development default or local-only passwords")
        if not self.redis_url:
            problems.append("REDIS_URL is required in production (shared rate limits and admission control)")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


_PLACEHOLDER_MARKERS = ("replace-with", "change-me", "changeme", "local-development", "local-only", "example")


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


@lru_cache
def get_settings() -> Settings:
    return Settings()
