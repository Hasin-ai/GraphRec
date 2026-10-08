"""The Insight drawer's Sequence and Status tabs, backed by GraphRec events."""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends
from graphrec_sdk import APIError

from ..dependencies import Identity, identity, services
from ..graphrec import Services
from ..schemas import Envelope, Film, SequenceItem, SequenceOut, StatusOut
from ..store import WINDOW, history_for

logger = logging.getLogger("reel.insight")
router = APIRouter(prefix="/insight", tags=["insight"])


async def get_shopper_history(svc: Services, ident: Identity) -> List[dict]:
    """Single source of truth: query GraphRec for identified users, shared storage for session."""
    if ident.user_id:
        try:
            records = await svc.client.storefront.events.list(user_id=ident.user_id, limit=500)
            if records:
                rows = []
                for item in reversed(records):
                    pid = getattr(item, "external_product_id", None) or getattr(item, "product_id", None)
                    if not pid:
                        continue
                    ctx = getattr(item, "context", {}) or {}
                    eid = getattr(item, "event_id", "")
                    origin = "training" if ctx.get("source") == "movielens-training-history" or str(eid).startswith("ml-") else "live"
                    dt = getattr(item, "occurred_at", None) or getattr(item, "created_at", None)
                    ts = int(dt.timestamp()) if hasattr(dt, "timestamp") else 0
                    rows.append({
                        "filmId": str(pid),
                        "time": ts,
                        "origin": origin,
                        "eventType": getattr(item, "event_type", "rating"),
                        "eventId": str(eid),
                    })
                return rows
        except Exception as exc:
            logger.warning("Failed to query GraphRec events for user %s: %s; falling back to local store", ident.user_id, exc)

    # Anonymous session or fallback:
    if ident.user_id is None:
        session_events = svc.storage.get_session_events(ident.session_id)
        if session_events:
            return [r for r in session_events if not r.get("duplicate")]

    live_rows = svc.live.for_shopper(ident.shopper)
    return history_for(ident.persona, live_rows)


@router.get("/sequence", response_model=Envelope[SequenceOut])
async def sequence(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    rows = await get_shopper_history(svc, ident)
    cut = max(0, len(rows) - WINDOW)
    live_in_window = sum(1 for r in rows[cut:] if r.get("origin") == "live")
    items = []
    # The window, plus the films most recently pushed out of it by live events.
    for n, r in enumerate(rows[max(0, cut - live_in_window):]):
        absolute = max(0, cut - live_in_window) + n
        film = svc.films.get(r["filmId"])
        if not film:
            continue
        items.append(SequenceItem(
            film=Film(**film),
            time=r.get("time", 0),
            origin=r.get("origin", "live"),
            event_type=r.get("eventType", "rating"),
            event_id=r.get("eventId"),
            in_window=absolute >= cut,
            evicted=absolute < cut,
        ))
    return Envelope(data=SequenceOut(
        shopper=ident.persona.name,
        total=len(rows),
        window=WINDOW,
        items=items,
        live_count=sum(1 for r in rows if r.get("origin") == "live"),
        session_only=ident.user_id is None,
    ))


@router.get("/history", response_model=Envelope[List[Film]])
async def history(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    """Every film in the shopper's history, most recent first, each film once (for "Recently watched" and ✓ marks)."""
    rows = await get_shopper_history(svc, ident)
    seen: set = set()
    out: List[Film] = []
    for r in reversed(rows):
        fid = r.get("filmId")
        film = svc.films.get(fid)
        if film and fid not in seen:
            seen.add(fid)
            out.append(Film(**film))
    return Envelope(data=out)


@router.get("/status", response_model=Envelope[StatusOut])
async def status(ident: Identity = Depends(identity), svc: Services = Depends(services)):
    cfg = svc.settings
    state = "ok"
    try:
        health = await svc.client.health()
        state = str(health.get("status", "ok")) if isinstance(health, dict) else "ok"
    except APIError:
        state = "unreachable"

    readiness = {
        "graphrec": state,
        "redis": "ok" if svc.storage.ping() else "down",
        "catalogue": "ok" if len(svc.films.items) > 0 else "empty",
        "model": "ok" if bool(cfg.reel_model_version_id or cfg.reel_model_source) else "unconfigured",
    }
    feedback_health = svc.storage.get_feedback_health()

    return Envelope(data=StatusOut(
        tenant=cfg.reel_tenant_name,
        graphrec=state,
        model_version_id=cfg.reel_model_version_id or None,
        model_version_tag=cfg.reel_model_version_tag or None,
        model_card=svc.model_card if cfg.reel_model_source == "checkpoint" else None,
        model_source=cfg.reel_model_source,
        live_events=len(svc.live.for_shopper(ident.shopper)),
        feedback_health=feedback_health,
        readiness=readiness,
    ))
