"""Identity comes from this request's cookies only; there is no global "active user"."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeSerializer

from .config import Settings, get_settings
from .graphrec import Services
from .store import Persona, shopper_key

logger = logging.getLogger(__name__)

PERSONA_COOKIE = "reel_persona"
SESSION_COOKIE = "reel_session"
MAX_AGE = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class Identity:
    persona: Persona
    session_id: str

    @property
    def user_id(self):
        return self.persona.user_id

    @property
    def shopper(self) -> str:
        return shopper_key(self.persona, self.session_id)

    def context(self, surface: str) -> dict:
        return {"surface": surface, "session_id": self.session_id, "demo_persona": self.persona.key, "source": "reel-storefront"}


def services(request: Request) -> Services:
    return request.app.state.services


def settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


def _serializer(secret_key: str) -> URLSafeSerializer:
    return URLSafeSerializer(secret_key, salt="reel-session-v1")


def sign_session(session_id: str, persona_key: str, secret_key: str) -> str:
    return _serializer(secret_key).dumps({"sid": session_id, "p": persona_key})


def unsign_session(token: str, secret_key: str) -> Optional[Tuple[str, str]]:
    try:
        data = _serializer(secret_key).loads(token)
        if isinstance(data, dict) and "sid" in data:
            return str(data["sid"]), str(data.get("p", "anon"))
    except (BadSignature, Exception):
        return None
    return None


def identity(request: Request) -> Identity:
    svc: Services = request.app.state.services
    cfg: Settings = settings(request)
    raw_token = request.cookies.get(SESSION_COOKIE) or ""

    session_id: str
    persona_key: str

    if raw_token:
        unsigned = unsign_session(raw_token, cfg.reel_secret_key)
        if unsigned:
            session_id, persona_key = unsigned
        elif valid_session(raw_token):
            # Backwards compatibility with existing un-signed sess_ cookies
            session_id = raw_token
            persona_key = request.cookies.get(PERSONA_COOKIE) or "anon"
        else:
            session_id = new_session_id()
            persona_key = "anon"
    else:
        session_id = getattr(request.state, "session_id", None) or new_session_id()
        persona_key = request.cookies.get(PERSONA_COOKIE) or "anon"

    # Allow query/state overrides if previously set in middleware
    if hasattr(request.state, "session_id") and request.state.session_id:
        session_id = request.state.session_id

    persona = svc.shoppers.get(persona_key, session_id=session_id)
    return Identity(persona, session_id)


def valid_session(value: str) -> bool:
    return value.startswith("sess_") and 12 <= len(value) <= 64


def new_session_id() -> str:
    return "sess_" + secrets.token_urlsafe(12)


def set_cookies(response: Response, ident: Identity, cfg: Settings) -> None:
    common = {"httponly": True, "samesite": "lax", "secure": cfg.reel_cookie_secure, "max_age": MAX_AGE, "path": "/"}
    signed_token = sign_session(ident.session_id, ident.persona.key, cfg.reel_secret_key)
    response.set_cookie(PERSONA_COOKIE, ident.persona.key, **common)
    response.set_cookie(SESSION_COOKIE, signed_token, **common)
