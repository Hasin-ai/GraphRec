"""Browser actions -> GraphRec events through the buffered tracker.

The browser chooses only the action shape; user id, session id and persona come
from the request's own cookies.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ..dependencies import Identity, identity, services
from ..errors import StoreError
from ..graphrec import Services
from ..schemas import Envelope, EventIn, EventOut

router = APIRouter(tags=["events"])

PRODUCT_ACTIONS = {"view", "add_to_cart", "remove_from_cart", "add_to_wishlist"}


async def track_browser_action(svc: Services, ident: Identity, body: EventIn) -> EventOut:
    ctx = ident.context(body.surface)
    common = {"session_id": ident.session_id, "context": ctx}
    tracker = svc.tracker
    if body.action in PRODUCT_ACTIONS:
        if not body.product_id:
            raise StoreError(422, "validation_failed", f"{body.action} needs a productId.")
        if body.action == "view":
            event = await tracker.view(ident.user_id, body.product_id, **common)
        elif body.action == "add_to_cart":
            event = await tracker.add_to_cart(ident.user_id, body.product_id, quantity=body.quantity, price=body.price, **common)
        elif body.action == "remove_from_cart":
            event = await tracker.remove_from_cart(ident.user_id, body.product_id, quantity=body.quantity, **common)
        else:
            event = await tracker.add_to_wishlist(ident.user_id, body.product_id, **common)
    else:  # search
        if not body.query or not body.query.strip():
            raise StoreError(422, "validation_failed", "search needs a query.")
        event = await tracker.search(ident.user_id, body.query.strip(), **common)
    return EventOut(event_id=str(event.event_id), event_type=str(event.event_type))


@router.post("/events", response_model=Envelope[EventOut], status_code=status.HTTP_202_ACCEPTED)
async def post_event(body: EventIn, ident: Identity = Depends(identity), svc: Services = Depends(services)) -> Envelope[EventOut]:
    out = await track_browser_action(svc, ident, body)
    return Envelope(data=out, meta={"pending": svc.tracker.pending})
