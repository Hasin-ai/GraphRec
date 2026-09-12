"""Identifier helpers.

GraphRec deduplicates events and feedback by the tenant-supplied ``event_id``
(max 100 characters). Random IDs are fine for fire-and-forget tracking; use
:func:`deterministic_id` when the same business fact may be sent more than once
(order webhooks, replayed exports) so GraphRec records it exactly once.
"""

from __future__ import annotations

import hashlib
import uuid

MAX_EVENT_ID_LENGTH = 100


def new_id(prefix: str = "") -> str:
    """Random unique identifier, e.g. ``evt_1f0c...``."""

    token = uuid.uuid4().hex
    return f"{prefix}_{token}" if prefix else token


def new_idempotency_key() -> str:
    return str(uuid.uuid4())


def deterministic_id(*parts: object, prefix: str = "") -> str:
    """Stable identifier derived from ``parts``.

    >>> deterministic_id("order", 1042, "line", 2, prefix="evt")
    'evt_…'   # always the same value for the same inputs
    """

    if not parts:
        raise ValueError("deterministic_id() needs at least one part")
    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    token = hashlib.sha256(material).hexdigest()[:40]
    result = f"{prefix}_{token}" if prefix else token
    return result[:MAX_EVENT_ID_LENGTH]
