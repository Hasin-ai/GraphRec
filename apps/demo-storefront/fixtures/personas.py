"""The four demo shoppers. Persona selection is a presenter control, not authentication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    blurb: str
    color: str
    #: GraphRec ``user_id``; ``None`` for the cold-start control (session recommendations).
    user_id: Optional[str]


PERSONAS: Dict[str, Persona] = {
    p.key: p
    for p in (
        Persona("maya", "Maya", "Barrier-first skincare, fragrance-free", "#174A3A", "demo-maya"),
        Persona("noah", "Noah", "Curl care and scalp health", "#4B6C8F", "demo-noah"),
        Persona("lina", "Lina", "Fragrance-forward, buys gifts", "#E58B72", "demo-lina"),
        Persona("guest", "New visitor", "No history — cold start", "#82857D", None),
    )
}

DEFAULT_PERSONA = "guest"
KNOWN_PERSONAS: Tuple[str, ...] = tuple(k for k, p in PERSONAS.items() if p.user_id)

#: Seeded browsing history per persona, oldest first: (event_type, product external_id, extra).
#: Purchases carry an order id so the event ids are deterministic order lines.
SEED_HISTORY: Dict[str, Tuple[Tuple[str, str, dict], ...]] = {
    "maya": (
        ("view", "skin-cleanser-01", {}),
        ("view", "skin-serum-01", {}),
        ("click", "skin-serum-01", {}),
        ("add_to_cart", "skin-cleanser-01", {"quantity": 1}),
        ("view", "skin-cream-01", {}),
        ("add_to_cart", "skin-cream-01", {"quantity": 1}),
        ("purchase", "skin-cleanser-01", {"order_id": "SEED-MAYA-1", "line": 1}),
        ("purchase", "skin-cream-01", {"order_id": "SEED-MAYA-1", "line": 2}),
        ("view", "skin-mask-01", {}),
        ("view", "skin-mist-01", {}),
        ("add_to_wishlist", "skin-mist-01", {}),
        ("view", "makeup-tint-01", {}),
        ("view", "skin-spf-01", {}),
        ("purchase", "skin-spf-01", {"order_id": "SEED-MAYA-2", "line": 1}),
    ),
    "noah": (
        ("view", "hair-shampoo-01", {}),
        ("view", "hair-conditioner-01", {}),
        ("add_to_cart", "hair-shampoo-01", {"quantity": 1}),
        ("add_to_cart", "hair-conditioner-01", {"quantity": 1}),
        ("purchase", "hair-shampoo-01", {"order_id": "SEED-NOAH-1", "line": 1}),
        ("purchase", "hair-conditioner-01", {"order_id": "SEED-NOAH-1", "line": 2}),
        ("view", "hair-curl-01", {}),
        ("click", "hair-curl-01", {}),
        ("view", "hair-tonic-01", {}),
        ("add_to_cart", "hair-tonic-01", {"quantity": 1}),
        ("view", "hair-oil-01", {}),
        ("view", "skin-cleanser-01", {}),
        ("purchase", "hair-tonic-01", {"order_id": "SEED-NOAH-2", "line": 1}),
    ),
    "lina": (
        ("view", "frag-edp-01", {}),
        ("click", "frag-edp-01", {}),
        ("view", "frag-solid-01", {}),
        ("add_to_cart", "frag-edp-01", {"quantity": 1}),
        ("purchase", "frag-edp-01", {"order_id": "SEED-LINA-1", "line": 1}),
        ("view", "makeup-blush-01", {}),
        ("view", "makeup-balm-01", {}),
        ("add_to_cart", "makeup-balm-01", {"quantity": 2}),
        ("view", "frag-handwash-01", {}),
        ("view", "frag-candle-01", {}),
        ("add_to_cart", "frag-candle-01", {"quantity": 1}),
        ("purchase", "makeup-balm-01", {"order_id": "SEED-LINA-2", "line": 1}),
        ("purchase", "frag-candle-01", {"order_id": "SEED-LINA-2", "line": 2}),
        ("view", "makeup-palette-01", {}),
    ),
}
