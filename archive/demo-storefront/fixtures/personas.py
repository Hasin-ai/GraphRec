"""The four demo shoppers. Persona selection is a presenter control, not authentication."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    blurb: str
    color: str
    #: GraphRec ``user_id``; ``None`` for the cold-start control (session recommendations).
    user_id: Optional[str]


def _persona_overrides() -> Dict[str, Tuple[str, str]]:
    """``DEMO_PERSONA_USERS`` maps personas onto real tenant shoppers.

    Format: ``maya=1234:Curly hair regular,noah=87:...`` (blurb optional). Read
    from the environment, falling back to ``.env`` next to the package, so the
    server and the scripts agree without pydantic-settings exporting variables.
    """

    raw = os.environ.get("DEMO_PERSONA_USERS")
    if raw is None:
        env_file = Path(__file__).resolve().parents[1] / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("DEMO_PERSONA_USERS="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    overrides: Dict[str, Tuple[str, str]] = {}
    for entry in (raw or "").split(","):
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        user_id, _, blurb = value.partition(":")
        if key.strip() and user_id.strip():
            overrides[key.strip().lower()] = (user_id.strip(), blurb.strip())
    return overrides


def _build_personas() -> Dict[str, Persona]:
    defaults = (
        Persona("maya", "Maya", "Barrier-first skincare, fragrance-free", "#174A3A", "demo-maya"),
        Persona("noah", "Noah", "Curl care and scalp health", "#4B6C8F", "demo-noah"),
        Persona("lina", "Lina", "Fragrance-forward, buys gifts", "#E58B72", "demo-lina"),
        Persona("guest", "New visitor", "No history — cold start", "#82857D", None),
    )
    overrides = _persona_overrides()
    personas: Dict[str, Persona] = {}
    for persona in defaults:
        if persona.key in overrides and persona.user_id is not None:
            user_id, blurb = overrides[persona.key]
            persona = Persona(persona.key, persona.name, blurb or persona.blurb, persona.color, user_id)
        personas[persona.key] = persona
    return personas


PERSONAS: Dict[str, Persona] = _build_personas()

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
