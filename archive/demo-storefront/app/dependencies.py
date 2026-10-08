"""Per-request identity from cookies, and access to the app-state GraphRec services.

Identity is resolved from *this request's* cookies only. Two browser windows with
different persona cookies are two different shoppers; there is no process-global
"active user".
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Request, Response

from fixtures.personas import DEFAULT_PERSONA, PERSONAS, Persona

from .config import Settings, get_settings
from .graphrec import Services

PERSONA_COOKIE = "facet_demo_user"
SESSION_COOKIE = "facet_demo_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class Identity:
    persona: Persona
    session_id: str
    #: True when the session cookie was missing and a fresh id was generated for this request.
    fresh_session: bool

    @property
    def user_id(self) -> Optional[str]:
        return self.persona.user_id

    def context(self, surface: str) -> dict:
        return {
            "surface": surface,
            "demo_persona": self.persona.key,
            "source": "demo-storefront",
        }


def new_session_id() -> str:
    return "sess_" + secrets.token_urlsafe(12)


def resolve_persona(raw: Optional[str]) -> Persona:
    key = (raw or "").strip().lower()
    return PERSONAS.get(key) or PERSONAS[DEFAULT_PERSONA]


def identity(request: Request) -> Identity:
    persona = resolve_persona(request.cookies.get(PERSONA_COOKIE))
    session_id = request.cookies.get(SESSION_COOKIE) or ""
    fresh = not (session_id.startswith("sess_") and 12 <= len(session_id) <= 64)
    if fresh:
        session_id = new_session_id()
    return Identity(persona=persona, session_id=session_id, fresh_session=fresh)


def set_identity_cookies(response: Response, ident: Identity, settings: Settings) -> None:
    common = {"httponly": True, "samesite": "lax", "secure": settings.demo_cookie_secure, "max_age": COOKIE_MAX_AGE, "path": "/"}
    response.set_cookie(PERSONA_COOKIE, ident.persona.key, **common)
    response.set_cookie(SESSION_COOKIE, ident.session_id, **common)


def services(request: Request) -> Services:
    return request.app.state.services


def settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()
