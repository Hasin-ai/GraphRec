"""A-10: production mode refuses default, placeholder or short secrets."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphrec_core.settings import Settings

STRONG = {
    "graphrec_env": "production",
    "jwt_signing_secret": "J" * 48,
    "audit_hash_secret": "A" * 48,
    "api_key_hmac_pepper": "P" * 48,
    "database_url": "postgresql+psycopg://graphrec_app:Zx9-strong-password@db:5432/graphrec",
    "redis_url": "redis://redis:6379/0",
    "platform_admin_token": None,
}


def build(**overrides):
    return Settings(_env_file=None, **{**STRONG, **overrides})


def test_production_accepts_strong_unique_secrets():
    assert build().is_production


@pytest.mark.parametrize("name", ["jwt_signing_secret", "audit_hash_secret", "api_key_hmac_pepper"])
def test_production_rejects_default_secrets(name):
    defaults = Settings.model_fields[name].default
    with pytest.raises(ValidationError, match=name.upper()):
        build(**{name: defaults})


@pytest.mark.parametrize("value", ["replace-with-a-long-random-local-secret-xxxxxxx", "x" * 20])
def test_production_rejects_placeholder_or_short_audit_secret(value):
    with pytest.raises(ValidationError, match="AUDIT_HASH_SECRET"):
        build(audit_hash_secret=value)


def test_production_rejects_development_database_password_and_missing_redis():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        build(database_url="postgresql+psycopg://graphrec_app:graphrec_app_local_only@db/graphrec")
    with pytest.raises(ValidationError, match="REDIS_URL"):
        build(redis_url=None)


def test_development_keeps_local_defaults():
    settings = Settings(_env_file=None)
    assert settings.graphrec_env == "development" and not settings.is_production
