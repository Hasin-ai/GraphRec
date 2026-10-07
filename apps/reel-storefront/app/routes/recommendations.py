"""Recommendation shelves, the before/after diff and click feedback.

* ``home`` - identified shopper: ``recommendations.get(user_id)``; GraphRec reads the
  stored history (seeded training events + live events). Anonymous: ``for_session``
  with this session's watched films as ``recent_product_ids``; with none, GraphRec
  answers with its popular fallback.
* ``more_like`` - ``for_session`` seeded with one film and no user: the session
  path of the same model (mean user vector), labelled as such.

The diff compares with the previous list this storefront showed on the same shelf.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import List, Optional, Union

from fastapi import APIRouter, Depends
from graphrec_sdk import APIError

from ..dependencies import Identity, identity, services
from ..errors import StoreError, translate_api_error
from ..graphrec import Services
from ..schemas import (ClickIn, Diff, Envelope, FeedbackOut, Film, Ranked, RecommendationIn, RecommendationsOut,
                       Trace, TraceRequest, Unavailable)
from ..store import WINDOW, display_title, history_for

router = APIRouter(tags=["recommendations"])


def genre_shift(films, before: List[str], after: List[str]) -> str:
    def shares(ids):
        c = Counter(g for i in ids for g in (films.get(i) or {}).get("genres", []))
        return {g: n / len(ids) for g, n in c.items()} if ids else {}
    b, a = shares(before), shares(after)
    if not b or not a:
        return ""
    # Name the genre that grew most; if none grew by 10 points, the one that moved most.
    genres = sorted(set(a) | set(b))
    genre = max(genres, key=lambda g: a.get(g, 0) - b.get(g, 0))
    if a.get(genre, 0) - b.get(genre, 0) < 0.1:
        genre = max(genres, key=lambda g: abs(a.get(g, 0) - b.get(g, 0)))
        if abs(a.get(genre, 0) - b.get(genre, 0)) < 0.1:
            return ""
    return f"{genre} {round(b.get(genre, 0) * 100)}% → {round(a.get(genre, 0) * 100)}%"


def build_diff(svc: Services, previous: Optional[List[str]], current: List[str]) -> Diff:
    if previous is None:
        return Diff(has_previous=False, entered=[], left=[], changed=0, summary="First list for this shelf.")
    if previous == current:
        return Diff(has_previous=True, entered=[], left=[], changed=0, summary="No change since the last update.")
    entered = [i for i in current if i not in previous]
    left = [Film(**svc.films.get(i)) for i in previous if i not in current and svc.films.get(i)]
    shift = genre_shift(svc.films, previous, current)
    summary = f"{len(entered)} of {len(current)} new" + (f"; {shift}" if shift else "") if entered else "Same films as before."
    if not entered and previous != current:
        summary = "Same films, new order."
    return Diff(has_previous=True, entered=entered, left=left, changed=len(entered), summary=summary)


@router.post("/recommendations", response_model=Envelope[Union[RecommendationsOut, Unavailable]])
async def recommend(body: RecommendationIn, ident: Identity = Depends(identity), svc: Services = Depends(services)):
    top_n = svc.settings.top_n
    ctx = ident.context("home" if body.shelf == "home" else "film")
    recent: List[str] = []
    exclude: List[str] = []
    user_id = ident.user_id
    if body.shelf == "more_like":
        if not body.film_id or not svc.films.get(body.film_id):
            raise StoreError(422, "validation_failed", "more_like needs a filmId from this store.")
        recent, exclude, user_id = [body.film_id], [body.film_id], None
    elif user_id is None:
        live = history_for(ident.persona, svc.live.for_shopper(ident.shopper))
        recent = [r["filmId"] for r in live][-WINDOW:]
    started = time.perf_counter()
    try:
        if user_id is not None:
            recs = await svc.client.storefront.recommendations.get(user_id=user_id, top_n=top_n, context=ctx)
            endpoint = "POST /v1/recommendations"
        else:
            recs = await svc.client.storefront.recommendations.for_session(
                ident.session_id, recent_product_ids=recent or None, top_n=top_n, context=ctx, exclude_product_ids=exclude or None)
            endpoint = "POST /v1/recommendations/session"
    except APIError as error:
        t = translate_api_error(error)
        return Envelope(data=Unavailable(reason=t.message, correlation_id=t.correlation_id), meta={"code": t.code})
    latency = round((time.perf_counter() - started) * 1000)

    ids = [i.external_product_id for i in recs.items]
    shelf_key = body.shelf if body.shelf == "home" else f"more_like:{body.film_id}"
    previous = svc.last_lists.swap(ident.shopper, shelf_key, ids)
    old_pos = {fid: n for n, fid in enumerate(previous or [], start=1)}
    items: List[Ranked] = []
    omitted = 0
    for item in recs.items:
        film = svc.films.get(item.external_product_id)
        if not film:
            omitted += 1
            continue
        before = old_pos.get(item.external_product_id)
        change = "same" if previous is None else ("new" if before is None else "up" if before > item.position else "down" if before < item.position else "same")
        items.append(Ranked(**film, position=item.position, change=change, previous_position=before))

    impression = None
    if recs.items:
        try:
            receipt = await svc.client.storefront.feedback.impression(recs, context=ctx)
            impression = receipt.event_id
            svc.impressions[recs.request_id] = impression
        except APIError:
            pass  # telemetry is best-effort

    if body.shelf == "more_like":
        title = f"More like {display_title(svc.films.get(body.film_id)['title'])}"
    elif recs.fallback_used:
        title = "Popular right now"
    else:
        title = "Recommended for you"
    trace = Trace(
        request=TraceRequest(endpoint=endpoint, user_id=user_id, top_n=top_n, recent_product_ids=recent, exclude_count=len(exclude)),
        request_id=recs.request_id,
        model_version_id=str(recs.model_version_id) if recs.model_version_id else None,
        strategy=recs.strategy, fallback_used=recs.fallback_used, fallback_tier=recs.fallback_tier,
        applied_rules=list(recs.applied_rules or []), latency_ms=latency,
    )
    return Envelope(data=RecommendationsOut(shelf=body.shelf, title=title, items=items, trace=trace,
                                            diff=build_diff(svc, previous, ids), omitted=omitted, impression=impression))


@router.post("/feedback/click", response_model=Envelope[FeedbackOut])
async def click(body: ClickIn, ident: Identity = Depends(identity), svc: Services = Depends(services)):
    fb = await svc.client.storefront.feedback.click(
        body.request_id, body.film_id, position=body.position,
        impression_event_id=svc.impressions.get(body.request_id), context=ident.context("shelf"))
    return Envelope(data=FeedbackOut(event_id=fb.event_id, accepted=fb.accepted, duplicate=fb.duplicate))
