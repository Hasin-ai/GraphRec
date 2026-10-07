from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ..config import Settings
from ..dependencies import Identity, identity, services, set_cookies, settings
from ..errors import StoreError
from ..graphrec import Services
from ..schemas import Envelope, PersonaIn, PersonaOut, Receipt, SessionOut
from ..store import Persona, shopper_key
from .events import record

router = APIRouter(tags=["session"])


def persona_out(p: Persona) -> PersonaOut:
    return PersonaOut(key=p.key, name=p.name, blurb=p.blurb, color=p.color, user_id=p.user_id, history_length=len(p.history))


def session_out(svc: Services, ident: Identity) -> SessionOut:
    return SessionOut(persona=persona_out(ident.persona), session_id=ident.session_id,
                      personas=[persona_out(p) for p in svc.shoppers.personas.values()])


@router.get("/session", response_model=Envelope[SessionOut])
async def get_session(response: Response, ident: Identity = Depends(identity), svc: Services = Depends(services), cfg: Settings = Depends(settings)):
    set_cookies(response, ident, cfg)
    return Envelope(data=session_out(svc, ident))


@router.post("/session/persona", response_model=Envelope[SessionOut])
async def set_persona(body: PersonaIn, response: Response, ident: Identity = Depends(identity),
                      svc: Services = Depends(services), cfg: Settings = Depends(settings)):
    key = body.persona.strip().lower()
    if key not in svc.shoppers.personas:
        raise StoreError(422, "unknown_persona", f"'{body.persona}' is not a demo shopper.")
    switched = Identity(svc.shoppers.personas[key], ident.session_id)
    carried: list[Receipt] = []
    if body.carry_session and ident.persona.user_id is None and switched.user_id:
        # Act 2: the films watched anonymously in this session are recorded for the signed-in shopper.
        # Deterministic ids: carrying twice is a duplicate, not a second interaction.
        for row in svc.live.for_shopper(shopper_key(ident.persona, ident.session_id)):
            if not row.get("duplicate"):
                carried.append(await record(svc, switched, row["filmId"], event_id=f"reel-carry-{switched.user_id}-{row['eventId']}"[:100], surface="sign_in"))
    set_cookies(response, switched, cfg)
    return Envelope(data=session_out(svc, switched), meta={"carried": [c.model_dump(by_alias=True) for c in carried]})
