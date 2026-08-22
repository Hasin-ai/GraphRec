"""Public key discovery.

Served unauthenticated and cached, because a verifier that cannot fetch the key
set cannot verify anything — including the token it would need to fetch it with.

Only public material appears here. The private scalar (`d`) is never part of the
response, and `alg` is published so a verifier pins the algorithm from the key
set rather than from the token it is about to check.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from apps.control_api.deps import get_token_service
from graphrec.auth.tokens import TokenService

router = APIRouter(tags=["discovery"])


@router.get("/.well-known/jwks.json", summary="Public keys for token verification")
async def jwks(
    response: Response, tokens: Annotated[TokenService, Depends(get_token_service)]
) -> dict[str, list[dict[str, str]]]:
    # Cacheable, but not indefinitely: a rotated key has to become reachable
    # within a bounded window or every verifier fails at once.
    response.headers["Cache-Control"] = "public, max-age=300"
    return tokens.public_jwks()
