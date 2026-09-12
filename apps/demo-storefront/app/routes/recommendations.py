"""Recommendations, feedback, simulated purchase and the compare lab."""

from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple, Union

from fastapi import APIRouter, Depends, Query
from graphrec_sdk import APIError
from graphrec_sdk.ecommerce import EventBuilder

from fixtures.personas import KNOWN_PERSONAS, PERSONAS, Persona

from ..dependencies import Identity, identity, services
from ..errors import StoreError, translate_api_error
from ..graphrec import Services, log, product_ids
from ..proof import distinct_orderings, gate, pairwise_similarity, provenance, shared_across_all
from ..schemas import (
    ClickIn,
    CompareColumn,
    CompareItem,
    CompareOut,
    CompareSummary,
    Envelope,
    FeedbackOut,
    PurchaseIn,
    PurchaseLineOut,
    PurchaseOut,
    RecommendationIn,
    RecommendationsOut,
    RecommendationsUnavailable,
)
from .session import persona_out

router = APIRouter(tags=["recommendations"])

COMPARE_TOP_N_DEFAULT = 5
COMPARE_SESSION_ID = "sess_compare_lab"


def _clean_ids(ids: Sequence[str]) -> List[str]:
    seen: Dict[str, None] = {}
    for raw in ids:
        value = str(raw).strip()
        if value and value not in seen:
            seen[value] = None
    return list(seen)[:200]


async def _fetch(svc: Services, persona: Persona, session_id: str, *, top_n: int, exclude: List[str], recent: List[str], context: dict):
    """One raw Top-N request for a persona: user-based for known shoppers, session-based otherwise."""

    if persona.user_id:
        return await svc.client.recommendations.get(user_id=persona.user_id, top_n=top_n, context=context, exclude_product_ids=exclude)
    return await svc.client.recommendations.for_session(
        session_id, recent_product_ids=recent or None, top_n=top_n, context=context, exclude_product_ids=exclude
    )


@router.post("/recommendations", response_model=Envelope[Union[RecommendationsOut, RecommendationsUnavailable]])
async def recommend(body: RecommendationIn, ident: Identity = Depends(identity), svc: Services = Depends(services)):
    exclude = _clean_ids(body.exclude_product_ids)
    recent = _clean_ids(body.recent_product_ids)
    context = ident.context(body.surface)
    try:
        recs = await _fetch(svc, ident.persona, ident.session_id, top_n=body.top_n, exclude=exclude, recent=recent, context=context)
    except APIError as error:
        # A shelf that fails must never take the page down with it.
        t = translate_api_error(error)
        log.warning("recommendations unavailable (%s): %s", t.code, error)
        return Envelope(data=RecommendationsUnavailable(reason=t.message, correlation_id=t.correlation_id), meta={"code": t.code})

    impression_id: Optional[str] = None
    if recs.items:
        try:
            receipt = await svc.client.feedback.impression(recs, context=context)
            impression_id = receipt.event_id
            svc.impressions.put(recs.request_id, impression_id)
        except APIError as error:  # telemetry is best-effort
            log.warning("impression feedback failed: %s", error)

    items, omitted = await svc.catalog.hydrate([(i.external_product_id, i.position) for i in recs.items])
    prov = provenance(
        recs,
        verified=svc.settings.model_proof_verified,
        verified_version_id=svc.settings.model_proof_version_id,
        excluded_count=len(exclude),
        omitted_product_count=omitted,
        impression_event_id=impression_id,
    )
    return Envelope(data=RecommendationsOut(items=items, provenance=prov), meta={"persona": ident.persona.key})


@router.post("/feedback/click", response_model=Envelope[FeedbackOut])
async def click(body: ClickIn, ident: Identity = Depends(identity), svc: Services = Depends(services)) -> Envelope[FeedbackOut]:
    receipt = await svc.client.feedback.click(
        body.request_id,
        body.product_id,
        position=body.position,
        impression_event_id=svc.impressions.get(body.request_id),
        context=ident.context(body.surface),
    )
    return Envelope(data=FeedbackOut(event_id=receipt.event_id, accepted=receipt.accepted, duplicate=receipt.duplicate))


def order_id_for(persona_key: str, client_order_key: str) -> str:
    digest = hashlib.sha256(f"facet:{persona_key}:{client_order_key}".encode()).hexdigest()
    return "ORD-" + digest[:8].upper()


@router.post("/purchase", response_model=Envelope[PurchaseOut])
async def purchase(body: PurchaseIn, ident: Identity = Depends(identity), svc: Services = Depends(services)) -> Envelope[PurchaseOut]:
    # Validate lines against the catalog first so nothing is sent for an unknown SKU.
    products = {p.external_id: p for p in await svc.catalog.all()}
    order_id = order_id_for(ident.persona.key, body.client_order_key)
    builder = EventBuilder(default_context={"source": "demo-storefront", "app": "facet"})
    context = ident.context(body.surface)
    events = []
    lines: List[PurchaseLineOut] = []
    total = Decimal("0")
    for index, line in enumerate(body.lines, start=1):
        product = products.get(line.product_id)
        if product is None or not product.available:
            raise StoreError(422, "unknown_product", f"{line.product_id} is not available in this store.")
        event = builder.purchase(
            ident.user_id,
            product.external_id,
            order_id=order_id,
            line=index,
            quantity=line.quantity,
            price=product.price,
            currency="USD",
            session_id=ident.session_id,
            context=context,
        )
        events.append(event)
        line_total = Decimal(product.price) * line.quantity
        total += line_total
        lines.append(
            PurchaseLineOut(
                product_id=product.external_id,
                title=product.title,
                quantity=line.quantity,
                unit_price=product.price,
                line_total=f"{line_total:.2f}",
                event_id=str(event.event_id),
            )
        )
    # Sent directly (not through the buffer) so the confirmation page can report the receipt.
    result = await svc.client.events.create_batch(events)
    return Envelope(
        data=PurchaseOut(
            order_id=order_id,
            lines=lines,
            total=f"{total:.2f}",
            accepted_count=result.accepted_count,
            duplicate_count=result.duplicate_count,
            rejected_count=result.rejected_count,
        ),
        meta={"requestCount": len(result.batches)},
    )


async def _compare_persona(svc: Services, persona: Persona, *, top_n: int, exclude: List[str]) -> Tuple[Optional[object], Optional[object], Optional[str]]:
    """Two identical requests so repeatability can be checked. Returns (first, second, error)."""

    context = {"surface": "compare", "demo_persona": persona.key, "source": "demo-storefront"}
    try:
        first = await _fetch(svc, persona, COMPARE_SESSION_ID, top_n=top_n, exclude=exclude, recent=[], context=context)
        second = await _fetch(svc, persona, COMPARE_SESSION_ID, top_n=top_n, exclude=exclude, recent=[], context=context)
        return first, second, None
    except APIError as error:
        return None, None, translate_api_error(error).message


@router.get("/compare", response_model=Envelope[CompareOut])
async def compare(
    top_n: int = Query(default=COMPARE_TOP_N_DEFAULT, alias="topN", ge=1, le=20),
    exclude: List[str] = Query(default=[]),
    svc: Services = Depends(services),
) -> Envelope[CompareOut]:
    excluded = _clean_ids(exclude)
    results = await asyncio.gather(*(_compare_persona(svc, PERSONAS[k], top_n=top_n, exclude=excluded) for k in PERSONAS))
    products = {p.external_id: p for p in await svc.catalog.all()}

    rankings: Dict[str, List[str]] = {}
    columns: List[CompareColumn] = []
    repeatable_flags: List[bool] = []
    for key, (first, second, error) in zip(PERSONAS, results):
        persona = persona_out(key)
        if first is None:
            columns.append(CompareColumn(persona=persona, items=[], provenance=None, repeatable=None, error=error))
            continue
        ids = product_ids(first.items)
        rankings[key] = ids
        repeatable = ids == product_ids(second.items) if second is not None else None
        if repeatable is not None:
            repeatable_flags.append(repeatable)
        columns.append(
            CompareColumn(
                persona=persona,
                items=[],  # filled below once shared products are known
                provenance=provenance(
                    first,
                    verified=svc.settings.model_proof_verified,
                    verified_version_id=svc.settings.model_proof_version_id,
                    excluded_count=len(excluded),
                    omitted_product_count=sum(1 for i in ids if i not in products),
                ),
                repeatable=repeatable,
            )
        )

    shared = shared_across_all(rankings) if len(rankings) == len(PERSONAS) else set()
    for column in columns:
        ids = rankings.get(column.persona.key, [])
        column.items = [
            CompareItem(
                position=index,
                external_id=pid,
                title=products[pid].title if pid in products else pid,
                category=products[pid].category if pid in products else "unknown",
                price=products[pid].price if pid in products else "0.00",
                accent=products[pid].accent if pid in products else None,
                shared=pid in shared,
            )
            for index, pid in enumerate(ids, start=1)
        ]

    names = {k: PERSONAS[k].name for k in rankings}
    known = {k: v for k, v in rankings.items() if k in KNOWN_PERSONAS}
    known_columns = [c for c in columns if c.persona.key in KNOWN_PERSONAS and c.provenance]
    any_model_version = any(c.provenance and c.provenance.model_version_id for c in columns)
    all_repeatable: Optional[bool] = all(repeatable_flags) if repeatable_flags else None
    passed, reason = gate(
        known_rankings=known,
        any_model_version=any_model_version,
        all_repeatable=all_repeatable,
        any_fallback_for_known=any(c.provenance.fallback_used for c in known_columns if c.provenance),
        verified_status_everywhere=bool(known_columns) and all(c.provenance.proof_status == "model_verified" for c in known_columns if c.provenance),
    )
    summary = CompareSummary(
        top_n=top_n,
        excluded_product_ids=excluded,
        unique_products=len({pid for ids in rankings.values() for pid in ids}),
        slots=top_n * len(PERSONAS),
        distinct_orderings=distinct_orderings(rankings),
        known_personas_identical=len(known) > 1 and distinct_orderings(known) == 1,
        all_repeatable=all_repeatable,
        any_model_version=any_model_version,
        gate_passed=passed,
        gate_reason=reason,
    )
    return Envelope(data=CompareOut(columns=columns, pairs=pairwise_similarity(rankings, names), summary=summary))
