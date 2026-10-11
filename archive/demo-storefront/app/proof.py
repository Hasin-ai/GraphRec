"""Honest provenance: compute ``proofStatus`` and cross-persona similarity.

The raw ``strategy`` GraphRec returns never drives a user-facing claim. A result is
``model_verified`` only when the operator has recorded a passed verification for
the *exact* model version that produced it.
"""

from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from .schemas import PairSimilarity, ProofStatus, Provenance


def proof_status(
    *,
    fallback_used: bool,
    model_version_id: Optional[str],
    verified: bool,
    verified_version_id: str,
) -> ProofStatus:
    if fallback_used:
        return "catalog_fallback"
    if verified and model_version_id and verified_version_id and model_version_id == verified_version_id:
        return "model_verified"
    return "serving_preview"


def provenance(
    recs: object,
    *,
    verified: bool,
    verified_version_id: str,
    excluded_count: int,
    omitted_product_count: int,
    impression_event_id: Optional[str] = None,
) -> Provenance:
    """Build the provenance block from an SDK ``Recommendations`` result."""

    model_version_id = getattr(recs, "model_version_id", None)
    model_version_id = str(model_version_id) if model_version_id else None
    fallback_used = bool(getattr(recs, "fallback_used", False))
    return Provenance(
        request_id=str(getattr(recs, "request_id")),
        model_version_id=model_version_id,
        raw_strategy=str(getattr(recs, "strategy", "")),
        fallback_used=fallback_used,
        fallback_tier=str(getattr(recs, "fallback_tier", "")),
        proof_status=proof_status(
            fallback_used=fallback_used,
            model_version_id=model_version_id,
            verified=verified,
            verified_version_id=verified_version_id,
        ),
        excluded_count=excluded_count,
        omitted_product_count=omitted_product_count,
        impression_event_id=impression_event_id,
    )


def pairwise_similarity(rankings: Dict[str, Sequence[str]], names: Dict[str, str]) -> List[PairSimilarity]:
    pairs: List[PairSimilarity] = []
    for a, b in combinations(rankings.keys(), 2):
        sa, sb = set(rankings[a]), set(rankings[b])
        union = len(sa | sb)
        pairs.append(
            PairSimilarity(a=names[a], b=names[b], overlap=len(sa & sb), jaccard=round(len(sa & sb) / union, 2) if union else 0.0)
        )
    return pairs


def distinct_orderings(rankings: Dict[str, Sequence[str]]) -> int:
    return len({tuple(r) for r in rankings.values()})


def shared_across_all(rankings: Dict[str, Sequence[str]]) -> set:
    sets = [set(r) for r in rankings.values() if r]
    return set.intersection(*sets) if sets else set()


def gate(
    *,
    known_rankings: Dict[str, Sequence[str]],
    any_model_version: bool,
    all_repeatable: Optional[bool],
    any_fallback_for_known: bool,
    verified_status_everywhere: bool,
) -> Tuple[bool, str]:
    """The model-proof gate, mirroring ``scripts/verify_personalization.py``.

    Returns ``(passed, reason)``. The reason is written for a presenter to read aloud.
    """

    if not known_rankings:
        return False, "No shopper with history was compared."
    if not any_model_version:
        return False, "No model version was returned, so there is nothing to verify."
    if any_fallback_for_known:
        return False, "At least one shopper with history received the catalog fallback."
    if all_repeatable is False:
        return False, "Repeating the same request changed the ordering, so results are not stable."
    if distinct_orderings(known_rankings) < len(known_rankings):
        return False, (
            "Shoppers with different histories received the same ranking. The serving path is live "
            "but the query is not yet user-specific."
        )
    if not verified_status_everywhere:
        return False, (
            "Rankings differ per shopper, but this model version has not been recorded as verified "
            "(MODEL_PROOF_VERIFIED / MODEL_PROOF_VERSION_ID). Run scripts/verify_personalization.py."
        )
    return True, "Rankings differ per shopper, repeat exactly, and carry a verified model version."
