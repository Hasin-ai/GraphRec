from __future__ import annotations

import hmac

from fastapi import Depends, Request

from graphrec_core.errors import ApiError
from graphrec_core.settings import Settings, get_settings


def platform_administrator(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.platform_admin_token
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    presented = token.strip()
    if (
        expected is None
        or scheme.lower() != "bearer"
        or not presented
        or not hmac.compare_digest(presented.encode(), expected.encode())
    ):
        raise ApiError(401, "authentication_failed", "Authentication failed")
