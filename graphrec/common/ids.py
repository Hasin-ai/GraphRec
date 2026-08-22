"""Identifier generation.

Resource identifiers are UUIDv7: time-ordered, so they index well as primary
keys, while remaining opaque to a client. Never expose a sequence — a guessable
identifier invites the cross-tenant probing that gate 4 exists to defeat.

Request references are short and human-quotable, because a tenant reads one out
of an error banner (`err-3f81-7a20c`, dc.html L1189).
"""

from __future__ import annotations

import os
import secrets
import time
import uuid

_ALPHABET = "0123456789abcdef"


def uuid7() -> uuid.UUID:
    """A UUIDv7: 48-bit millisecond timestamp, then 74 random bits.

    Python's stdlib has no uuid7 before 3.14, so it is constructed here rather
    than taking a dependency for one function.
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand = int.from_bytes(os.urandom(10), "big")

    value = ms << 80
    value |= 7 << 76  # version
    value |= ((rand >> 64) & 0xFFF) << 64  # rand_a
    value |= 0b10 << 62  # variant
    value |= rand & 0x3FFFFFFFFFFFFFFF  # rand_b
    return uuid.UUID(int=value)


def new_request_reference() -> str:
    """`err-3f81-7a20c` — the shape the console already renders."""
    return "err-{}-{}".format(
        "".join(secrets.choice(_ALPHABET) for _ in range(4)),
        "".join(secrets.choice(_ALPHABET) for _ in range(5)),
    )


def new_request_id() -> str:
    """The `X-Request-Id` value when a client supplies none."""
    return uuid7().hex


def new_token(byte_length: int = 32) -> str:
    """A URL-safe secret: invitation tokens, recovery proofs, credential secrets."""
    return secrets.token_urlsafe(byte_length)
