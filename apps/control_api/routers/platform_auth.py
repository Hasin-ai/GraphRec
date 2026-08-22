"""Operator sign-in and identity, under `/v1/platform/*` (D6).

Separated from the tenant routes by prefix so that "audit" in the platform realm
and "audit" in the tenant realm can never be confused for one another, and so
that a mis-mounted router is visible in the route table rather than at runtime.

Every route here runs on the platform connection, as `graphrec_platform` — a role
holding no grant at all on products, events, customers or models.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.control_api.deps import CurrentPlatform, get_token_service
from apps.control_api.routers.auth import _client_address
from apps.control_api.schemas import (
    PlatformMeResponse,
    PlatformSignInRequest,
    SessionResponse,
)
from graphrec.auth.tokens import TokenService
from graphrec.domain.identity import IdentityService

router = APIRouter(prefix="/platform", tags=["platform-auth"])


def _service(tokens: Annotated[TokenService, Depends(get_token_service)]) -> IdentityService:
    return IdentityService(tokens)


Service = Annotated[IdentityService, Depends(_service)]


@router.post("/auth/sign-in", response_model=SessionResponse, summary="Operator sign-in")
async def platform_sign_in(
    body: PlatformSignInRequest, request: Request, service: Service
) -> SessionResponse:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.platform_sessionmaker
    async with sessionmaker() as session, session.begin():
        user = await service.authenticate_platform_user(
            session, email=body.email, password=body.password
        )
        issued = await service.issue_platform_session(
            session,
            user=user,
            user_agent=request.headers.get("user-agent"),
            client_address=_client_address(request),
        )
    return SessionResponse(
        access_token=issued.access_token,
        expires_at=issued.access_expires_at,
        refresh_token=issued.refresh_token,
        refresh_expires_at=issued.refresh_expires_at,
    )


@router.get("/me", response_model=PlatformMeResponse, summary="The signed-in operator")
async def platform_me(principal: CurrentPlatform) -> PlatformMeResponse:
    """Reports the *effective* permissions — the token's, intersected with the
    database's. A permission revoked after the token was issued does not appear.
    """
    return PlatformMeResponse(
        platform_user_id=principal.user.platform_user_id,
        email=principal.user.email,
        display_name=principal.user.display_name,
        permissions=sorted(principal.permissions),
    )
