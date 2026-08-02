from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://graphrec_app:graphrec_app_local_only@localhost:5432/graphrec"
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
    max_tenant_name_length: int = Field(default=200, ge=1)
    max_idempotency_key_length: int = Field(default=255, ge=16)
    max_password_length: int = Field(default=1_024, ge=64)

    # Qdrant vector store
    qdrant_url: str = Field(default="http://localhost:6334")
    qdrant_collection_prefix: str = Field(default="graphrec")
    qdrant_embedding_dim: int = Field(default=128, ge=16, le=4096)
    qdrant_top_k: int = Field(default=100, ge=1, le=1000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
