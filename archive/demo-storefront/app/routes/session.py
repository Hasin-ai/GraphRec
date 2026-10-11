from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from fixtures.personas import PERSONAS

from ..config import Settings
from ..dependencies import Identity, identity, set_identity_cookies, settings
from ..errors import StoreError
from ..schemas import Envelope, PersonaIn, PersonaOut, SessionOut

router = APIRouter(tags=["session"])


def persona_out(key: str) -> PersonaOut:
    p = PERSONAS[key]
    return PersonaOut(key=p.key, name=p.name, blurb=p.blurb, color=p.color, user_id=p.user_id)


def session_out(ident: Identity) -> SessionOut:
    return SessionOut(
        persona=persona_out(ident.persona.key),
        session_id=ident.session_id,
        personas=[persona_out(k) for k in PERSONAS],
    )


@router.get("/session", response_model=Envelope[SessionOut])
async def get_session(response: Response, ident: Identity = Depends(identity), cfg: Settings = Depends(settings)) -> Envelope[SessionOut]:
    set_identity_cookies(response, ident, cfg)
    return Envelope(data=session_out(ident), meta={"freshSession": ident.fresh_session})


@router.post("/session/persona", response_model=Envelope[SessionOut])
async def set_persona(body: PersonaIn, response: Response, ident: Identity = Depends(identity), cfg: Settings = Depends(settings)) -> Envelope[SessionOut]:
    key = body.persona.strip().lower()
    if key not in PERSONAS:
        raise StoreError(422, "unknown_persona", f"'{body.persona}' is not a demo shopper. Choose one of: {', '.join(PERSONAS)}.")
    switched = Identity(persona=PERSONAS[key], session_id=ident.session_id, fresh_session=ident.fresh_session)
    set_identity_cookies(response, switched, cfg)
    return Envelope(data=session_out(switched), meta={"previous": ident.persona.key})
