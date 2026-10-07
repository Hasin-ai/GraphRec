"""The Insight drawer's Sequence and Status tabs."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from graphrec_sdk import APIError

from ..dependencies import Identity, identity, services
from ..graphrec import Services
from ..schemas import Envelope, Film, SequenceItem, SequenceOut, StatusOut
from ..store import WINDOW, history_for

router = APIRouter(prefix="/insight", tags=["insight"])


@router.get("/sequence", response_model=Envelope[SequenceOut])
async def sequence(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    live_rows = svc.live.for_shopper(ident.shopper)
    rows = history_for(ident.persona, live_rows)
    cut = max(0, len(rows) - WINDOW)
    live_in_window = sum(1 for r in rows[cut:] if r["origin"] == "live")
    items = []
    # The window, plus the films most recently pushed out of it by live events.
    for n, r in enumerate(rows[max(0, cut - live_in_window):]):
        absolute = max(0, cut - live_in_window) + n
        film = svc.films.get(r["filmId"])
        if not film:
            continue
        items.append(SequenceItem(film=Film(**film), time=r["time"], origin=r["origin"], event_type=r["eventType"],
                                  event_id=r.get("eventId"), in_window=absolute >= cut, evicted=absolute < cut))
    return Envelope(data=SequenceOut(shopper=ident.persona.name, total=len(rows), window=WINDOW, items=items,
                                     live_count=sum(1 for r in rows if r["origin"] == "live"),
                                     session_only=ident.user_id is None))


@router.get("/history", response_model=Envelope[List[Film]])
async def history(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    """Every film in the shopper's history, most recent first, each film once (for "Recently watched" and ✓ marks)."""
    seen: set = set()
    out: List[Film] = []
    for r in reversed(history_for(ident.persona, svc.live.for_shopper(ident.shopper))):
        film = svc.films.get(r["filmId"])
        if film and r["filmId"] not in seen:
            seen.add(r["filmId"])
            out.append(Film(**film))
    return Envelope(data=out)


@router.get("/status", response_model=Envelope[StatusOut])
async def status(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    cfg = svc.settings
    try:
        health = await svc.client.health()
        state = str(health.get("status", "ok")) if isinstance(health, dict) else "ok"
    except APIError:
        state = "unreachable"
    return Envelope(data=StatusOut(
        tenant=cfg.reel_tenant_name, graphrec=state,
        model_version_id=cfg.reel_model_version_id or None, model_version_tag=cfg.reel_model_version_tag or None,
        model_card=svc.model_card, live_events=len(svc.live.for_shopper(ident.shopper))))
