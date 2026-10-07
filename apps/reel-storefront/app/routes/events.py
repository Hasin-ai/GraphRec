"""Shopper actions -> GraphRec interaction events, sent one at a time so each has a receipt.

Events go through ``client.storefront.events.create`` (not the buffered tracker):
the next recommendation request must see the event, and the Insight drawer shows
GraphRec's own accepted/duplicate answer.
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends

from ..dependencies import Identity, identity, services
from ..errors import StoreError
from ..graphrec import Services
from ..schemas import Envelope, Receipt, WatchIn
from ..store import now_seconds

router = APIRouter(tags=["events"])

#: "Watched it" is sent as a rating. The checkpoint ignores the value (one edge type); it is kept for the record.
WATCH_EVENT = "rating"


async def record(svc: Services, ident: Identity, film_id: str, *, event_id: Optional[str] = None, surface: str = "film") -> Receipt:
    if not svc.films.get(film_id):
        raise StoreError(404, "not_found", "That film is not in this store.")
    event_id = event_id or "reel-" + secrets.token_hex(8)
    started = time.perf_counter()
    receipt = await svc.client.storefront.events.create(
        WATCH_EVENT,
        user_id=ident.user_id,
        product_id=film_id,
        context={**ident.context(surface), "rating": 5, "max_rating": 5},
        event_id=event_id,
    )
    latency = round((time.perf_counter() - started) * 1000)
    svc.live.add({
        "shopper": ident.shopper, "filmId": film_id, "eventId": receipt.event_id, "eventType": WATCH_EVENT,
        "time": now_seconds(), "duplicate": bool(receipt.duplicate), "accepted": bool(receipt.accepted),
    })
    return Receipt(event_id=receipt.event_id, event_type=WATCH_EVENT, film_id=film_id, accepted=bool(receipt.accepted),
                   duplicate=bool(receipt.duplicate), latency_ms=latency)


@router.post("/watch", response_model=Envelope[Receipt])
async def watch(body: WatchIn, ident: Identity = Depends(identity), svc: Services = Depends(services)):
    out = await record(svc, ident, body.film_id)
    if body.request_id:
        try:
            fb = await svc.client.storefront.feedback.conversion(
                body.request_id, body.film_id, position=body.position, context=ident.context("film"))
            out.feedback = "conversion " + ("duplicate" if fb.duplicate else "accepted")
        except Exception:  # feedback is telemetry; never fail the watch
            out.feedback = "conversion failed"
    return Envelope(data=out)


@router.post("/watch/replay", response_model=Envelope[Receipt])
async def replay(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    """Re-send the shopper's last event with the SAME event_id: GraphRec must answer duplicate (NR-NF-05)."""

    last = next((r for r in reversed(svc.live.for_shopper(ident.shopper)) if not r.get("duplicate")), None)
    if last is None:
        raise StoreError(409, "nothing_to_replay", "Watch a film first; then replay that event.")
    return Envelope(data=await record(svc, ident, last["filmId"], event_id=last["eventId"]))
