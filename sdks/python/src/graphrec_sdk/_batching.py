"""Byte-budget chunking for bulk endpoints.

GraphRec rejects request bodies above ``MAX_REQUEST_BODY_BYTES`` (16 KiB by
default) with ``413 payload_too_large``. Bulk helpers split their input so that
every request fits, measuring each item with the exact encoder used to send it.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from ._serialization import encode_json
from .errors import InputValidationError


def chunk_items(
    items: Sequence[Any],
    *,
    envelope_key: str,
    max_bytes: int,
    max_items: int,
    describe: str = "item",
) -> List[List[Any]]:
    """Split JSON-ready ``items`` so each ``{envelope_key: [...]}`` body fits ``max_bytes``."""

    overhead = len(encode_json({envelope_key: []}))
    chunks: List[List[Any]] = []
    current: List[Any] = []
    current_size = overhead

    for item in items:
        size = len(encode_json(item))
        if overhead + size > max_bytes:
            label = (
                (item.get("external_id") or item.get("event_id"))
                if isinstance(item, dict)
                else None
            )
            raise InputValidationError(
                f"{describe} {label!r} encodes to {size} bytes, which cannot fit in a "
                f"{max_bytes}-byte request. Shrink it (e.g. its metadata/context) or raise "
                "max_body_bytes to match the server's MAX_REQUEST_BODY_BYTES."
            )
        added = size + (1 if current else 0)
        if current and (current_size + added > max_bytes or len(current) >= max_items):
            chunks.append(current)
            current = []
            current_size = overhead
            added = size
        current.append(item)
        current_size += added

    if current:
        chunks.append(current)
    return chunks
