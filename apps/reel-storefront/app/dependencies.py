"""Identity comes from this request's cookies only; there is no global "active user"."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Request, Response

from .config import Settings, get_settings
from .graphrec import Services
from .store import Persona, shopper_key

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


def identity(request: Request) -> Identity:
    svc: Services = request.app.state.services
    session_id = getattr(request.state, "session_id", None) or request.cookies.get(SESSION_COOKIE) or ""
    return Identity(svc.shoppers.get(request.cookies.get(PERSONA_COOKIE)), session_id)


def valid_session(value: str) -> bool:
    return value.startswith("sess_") and 12 <= len(value) <= 64


def new_session_id() -> str:
    return "sess_" + secrets.token_urlsafe(12)


def set_cookies(response: Response, ident: Identity, cfg: Settings) -> None:
    common = {"httponly": True, "samesite": "lax", "secure": cfg.reel_cookie_secure, "max_age": MAX_AGE, "path": "/"}
    response.set_cookie(PERSONA_COOKIE, ident.persona.key, **common)
    response.set_cookie(SESSION_COOKIE, ident.session_id, **common)
