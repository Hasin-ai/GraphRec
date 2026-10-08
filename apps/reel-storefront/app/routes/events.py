"""Shopper actions -> GraphRec interaction events, sent one at a time so each has a receipt.

Events go through ``client.storefront.events.create`` (not the buffered tracker):
the next recommendation request must see the event, and the Insight drawer shows
GraphRec's own accepted/duplicate answer.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from ..dependencies import Identity, identity, services
from ..errors import StoreError
from ..graphrec import Services
from ..schemas import Envelope, Receipt, WatchIn
from ..store import now_seconds

logger = logging.getLogger("reel.events")
router = APIRouter(tags=["events"])


async def record(
    svc: Services,
    ident: Identity,
    film_id: str,
    *,
    event_id: Optional[str] = None,
    event_type: str = "rating",
    rating_value: Optional[float] = None,
    occurred_at_sec: Optional[int] = None,
    surface: str = "film",
) -> Receipt:
    if not svc.films.get(film_id):
        raise StoreError(404, "not_found", "That film is not in this store.")

    event_id = event_id or "reel-" + secrets.token_hex(8)
    started = time.perf_counter()

    context = {**ident.context(surface)}
    if event_type == "rating":
        val = rating_value if rating_value is not None else 5
        context["rating"] = val
        context["max_rating"] = 5

    dt_occurred = None
    if occurred_at_sec:
        dt_occurred = datetime.fromtimestamp(occurred_at_sec, timezone.utc)

    # Call GraphRec storefront events API
    receipt = await svc.client.storefront.events.create(
        event_type,
        user_id=ident.user_id,
        product_id=film_id,
        context=context,
        event_id=event_id,
        occurred_at=dt_occurred,
    )
    latency = round((time.perf_counter() - started) * 1000)

    event_row = {
        "shopper": ident.shopper,
        "filmId": film_id,
        "eventId": receipt.event_id,
        "eventType": event_type,
        "origin": "live",
        "time": occurred_at_sec or now_seconds(),
        "duplicate": bool(receipt.duplicate),
        "accepted": bool(receipt.accepted),
    }

    # Record in local live log and durable shared session events
    svc.live.add(event_row)
    if ident.user_id is None:
        svc.storage.record_session_event(ident.session_id, event_row)

    return Receipt(
        event_id=receipt.event_id,
        event_type=event_type,
        film_id=film_id,
        accepted=bool(receipt.accepted),
        duplicate=bool(receipt.duplicate),
        latency_ms=latency,
    )


@router.post("/watch", response_model=Envelope[Receipt])
async def watch(body: WatchIn, ident: Identity = Depends(identity), svc: Services = Depends(services)):
    out = await record(
        svc,
        ident,
        body.film_id,
        event_type=body.event_type,
        rating_value=body.rating,
        occurred_at_sec=body.occurred_at,
    )
    if body.request_id:
        fb_succeeded = False
        fb_result = None
        for attempt in range(2):
            try:
                fb_result = await svc.client.storefront.feedback.conversion(
                    body.request_id,
                    body.film_id,
                    position=body.position,
                    context=ident.context("film"),
                )
                fb_succeeded = True
                break
            except Exception as exc:
                if attempt == 1:
                    logger.warning("Conversion feedback failed after retry for req %s: %s", body.request_id, exc)

        svc.storage.record_feedback("conversion", fb_succeeded)
        if fb_succeeded and fb_result:
            out.feedback = "conversion " + ("duplicate" if fb_result.duplicate else "accepted")
        else:
            out.feedback = "conversion failed"

    return Envelope(data=out)


@router.post("/watch/replay", response_model=Envelope[Receipt])
async def replay(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    """Re-send the shopper's last event with the SAME event_id: GraphRec must answer duplicate (NR-NF-05)."""
    last = next((r for r in reversed(svc.live.for_shopper(ident.shopper)) if not r.get("duplicate")), None)
    if last is None:
        raise StoreError(409, "nothing_to_replay", "Watch a film first; then replay that event.")
    return Envelope(
        data=await record(
            svc,
            ident,
            last["filmId"],
            event_id=last["eventId"],
            event_type=last.get("eventType", "rating"),
        )
    )
