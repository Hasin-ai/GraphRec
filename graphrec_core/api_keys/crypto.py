from __future__ import annotations

import hashlib
import hmac
import secrets

SECRET_PREFIX = "gr_live_"


def generate_api_key() -> tuple[str, str]:
    encoded_secret = secrets.token_urlsafe(32)
    full_secret = f"{SECRET_PREFIX}{encoded_secret}"
    return full_secret, f"{SECRET_PREFIX}{encoded_secret[:8]}"


def api_key_digest(secret: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def has_valid_secret_shape(secret: str) -> bool:
    if not secret.startswith(SECRET_PREFIX) or len(secret) != len(SECRET_PREFIX) + 43:
        return False
    encoded = secret[len(SECRET_PREFIX) :]
    return all(character.isalnum() or character in "-_" for character in encoded)
