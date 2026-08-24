"""Tenant registration, sign-in, refresh and sign-out.

These are the only routes that run without a verified credential, so they are the
only ones that use `get_session` rather than a tenant-bound one. Each binds a
context of its own before touching a tenant-owned row — from a value it minted
(registration), or from a verified claim (refresh).
"""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.control_api.deps import (
    CurrentTenant,
    get_session,
    get_settings_dep,
    get_token_service,
)
from apps.control_api.schemas import (
    AcceptInvitationRequest,
    ConfirmRecoveryRequest,
    MeResponse,
    RecoveryRequestedResponse,
    RefreshRequest,
    RegisterTenantRequest,
    RequestRecoveryRequest,
    SessionResponse,
    SignInRequest,
    TenantResponse,
    UserResponse,
)
from graphrec.auth.tokens import TokenService
from graphrec.common.config import Settings
from graphrec.common.delivery import deliver_recovery
from graphrec.common.enums import AuditAction
from graphrec.common.errors import AuthError, ConflictError, GraphRecError
from graphrec.domain.audit import Actor, AuditTrail, record
from graphrec.domain.identity import IdentityService

router = APIRouter(tags=["auth"])


def _service(
    tokens: Annotated[TokenService, Depends(get_token_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> IdentityService:
    return IdentityService(
        tokens,
        invitation_ttl_seconds=settings.invitation_ttl_seconds,
        recovery_ttl_seconds=settings.recovery_ttl_seconds,
    )


Service = Annotated[IdentityService, Depends(_service)]
Session = Annotated[AsyncSession, Depends(get_session)]


def _client_address(request: Request) -> str | None:
    """The peer address, for session forensics. Never a forwarded header.

    `X-Forwarded-For` is caller-controlled unless a trusted proxy overwrites it,
    and this service does not yet know whether one is in front of it. Recording a
    spoofable value would make the session log actively misleading.

    The value is parsed before it is returned, because the column is `inet` and
    the peer is not always an address — ASGI transports over a unix socket or an
    in-process test client report a name. An unparseable peer is recorded as
    absent rather than crashing a sign-in that is otherwise valid.
    """
    if request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a tenant and its first administrator",
)
async def register_tenant(
    body: RegisterTenantRequest, session: Session, service: Service
) -> TenantResponse:
    async with session.begin():
        try:
            tenant, _ = await service.register_tenant(
                session,
                tenant_name=body.tenant_name,
                tenant_code=body.tenant_code,
                email=body.email,
                password=body.password,
                plan_id=None,
            )
        except IntegrityError as exc:
            # The unique index is the real arbiter — two simultaneous
            # registrations of one name both pass the pre-check and one loses
            # here. Reported with the prototype's wording either way.
            raise ConflictError(
                "tenant_name_already_registered",
                copy_args={"business_name": body.tenant_name},
            ).with_field("tenant_name", "Business name already registered.") from exc

        return TenantResponse(
            tenant_id=tenant.tenant_id,
            tenant_code=tenant.tenant_code,
            tenant_name=tenant.tenant_name,
            status=tenant.status,
            created_at=tenant.created_at,
            status_reason=tenant.status_reason,
        )


@router.post("/auth/sign-in", response_model=SessionResponse, summary="Sign in to a tenant")
async def sign_in(
    body: SignInRequest, request: Request, session: Session, service: Service
) -> SessionResponse:
    """Audited both ways, and the two ways are written differently.

    A successful sign-in joins this transaction: `authenticate_tenant_user` has
    already bound `app.tenant_id`, so the row lands scoped to the tenant whose
    audit page will show it.

    A refused sign-in cannot. The refusal raises, the transaction rolls back,
    and a row written here would go with it — so `AuditTrail.refused` writes on
    a second connection. Which tenant it names depends on how far the attempt
    got: a real tenant code gives a row that tenant can see on their own audit
    page, and an unrecognised one gives a row with no tenant at all, visible
    only to the platform realm. Neither case tells the caller which it was.
    """
    trail = AuditTrail(
        session=session,
        sessionmaker=request.app.state.sessionmaker,
        actor=Actor.unauthenticated(),
    )
    try:
        return await _sign_in(body, request, session, service, trail)
    except GraphRecError as exc:
        await trail.refused(
            AuditAction.ACCESS,
            resource_type="session",
            error=exc,
            details={"operation": "sign_in"},
        )
        raise


async def _sign_in(
    body: SignInRequest,
    request: Request,
    session: AsyncSession,
    service: IdentityService,
    trail: AuditTrail,
) -> SessionResponse:
    async with session.begin():
        # A direct `SELECT` here returns nothing: no context is bound yet, so RLS
        # filters every row. That is the correct default and is not worked
        # around — `resolve_tenant_code` is a SECURITY DEFINER function
        # (migration 0003) that returns one identifier for an exact code and no
        # other column. See that migration for why the alternatives are worse.
        tenant_id = await session.scalar(
            select(func.tenant_lookup.resolve_tenant_code(body.tenant_code))
        )
        if tenant_id is None:
            # Still pay the cost of a hash so a bad tenant code and a bad
            # password take the same time.
            from graphrec.auth.passwords import verify_password

            verify_password(None, body.password)
            raise AuthError("invalid_credentials")

        # Known from here on, so a refusal past this point names the tenant it
        # was aimed at rather than nobody.
        trail.tenant_id = tenant_id

        tenant, user = await service.authenticate_tenant_user(
            session, tenant_id=tenant_id, email=body.email, password=body.password
        )
        trail.actor = Actor.user(user.tenant_user_id)
        await record(
            session,
            actor=trail.actor,
            action=AuditAction.ACCESS,
            resource_type="session",
            resource_ref=user.tenant_user_id,
            tenant_id=tenant_id,
            details={"operation": "sign_in"},
        )
        issued = await service.issue_tenant_session(
            session,
            tenant=tenant,
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


@router.post("/auth/refresh", response_model=SessionResponse, summary="Exchange a refresh token")
async def refresh(
    body: RefreshRequest, request: Request, session: Session, service: Service
) -> SessionResponse:
    async with session.begin():
        issued = await service.rotate_tenant_session(
            session,
            refresh_token=body.refresh_token,
            user_agent=request.headers.get("user-agent"),
            client_address=_client_address(request),
        )
    return SessionResponse(
        access_token=issued.access_token,
        expires_at=issued.access_expires_at,
        refresh_token=issued.refresh_token,
        refresh_expires_at=issued.refresh_expires_at,
    )


@router.post(
    "/auth/sign-out",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
async def sign_out(body: RefreshRequest, session: Session, service: Service) -> Response:
    """Idempotent, and answers 204 whether or not the token existed.

    Reporting "no such session" would let anyone test whether a token they found
    is still live.
    """
    async with session.begin():
        await service.revoke_tenant_session(session, refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: The one sentence step 1 returns, whatever happened. Held as a constant so a
#: test can assert that the two code paths return the identical string rather
#: than two strings that merely look alike (dc.html L1588).
RECOVERY_REQUESTED = "If that identifier matches an account, recovery instructions have been sent."


@router.post(
    "/auth/recovery",
    response_model=RecoveryRequestedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a recovery proof",
)
async def request_recovery(
    body: RequestRecoveryRequest, session: Session, service: Service
) -> RecoveryRequestedResponse:
    """Accepted, always. What follows from it is not the caller's business.

    202 rather than 200 because that is what actually happened: a request was
    accepted for out-of-band handling, and whether anything was sent is
    something the caller is not told. A 200 would imply a completed action and
    invite the reading that a 404 exists for the other case.

    Three things are the same on both paths and each is deliberate:

    * the status code,
    * the response body — `RECOVERY_REQUESTED` and nothing derived from the
      lookup,
    * and the absence of an audit row. A refusal recorded here would be an
      `outcome: cancelled` row that appeared only for identifiers that do not
      exist, which is an enumeration oracle for anyone who can read the tenant's
      own audit page.

    The timing is *not* equalised, and this is the honest limitation: an unknown
    tenant code returns before any row is read. Recovery is rate-limited at the
    edge rather than padded here, because padding an endpoint that writes rows
    to a fixed duration is a promise this code cannot keep under load.
    """
    async with session.begin():
        tenant_id = await session.scalar(
            select(func.tenant_lookup.resolve_tenant_code(body.tenant_code))
        )
        issued = (
            None
            if tenant_id is None
            else await service.request_recovery(session, tenant_id=tenant_id, email=body.email)
        )
    if issued is not None:
        # After the commit, not inside it. A proof handed to a transport and
        # then rolled back is a proof that works for the person holding it and
        # matches no digest in the database.
        deliver_recovery(email=issued.user.email, token=issued.token, expires_at=issued.expires_at)
    return RecoveryRequestedResponse(detail=RECOVERY_REQUESTED)


@router.post(
    "/auth/recovery:confirm",
    response_model=UserResponse,
    summary="Consume a recovery proof and set new authentication material",
)
async def confirm_recovery(
    body: ConfirmRecoveryRequest, session: Session, service: Service
) -> UserResponse:
    """Step 2. Unauthenticated by necessity, exactly like accepting an invitation.

    No session is issued. The prototype's button reads "Set and return to sign
    in" (dc.html L1039), and signing in afterwards is what proves the password
    just set is the password the user meant. It also means the account is not
    handed a live session by a request that carried no proof of identity beyond
    a token from an email.
    """
    async with session.begin():
        user = await service.confirm_recovery(
            session,
            token=body.token,
            password=body.password,
            password_confirmation=body.password_confirmation,
        )
        return UserResponse(
            tenant_user_id=user.tenant_user_id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            last_authenticated_at=user.last_authenticated_at,
        )


@router.post(
    "/invitations:accept",
    response_model=UserResponse,
    summary="Activate an invited account",
)
async def accept_invitation(
    body: AcceptInvitationRequest, session: Session, service: Service
) -> UserResponse:
    """Unauthenticated by necessity: the invitee has no account until this runs.

    The invitation token is the credential, and it is the only thing the caller
    supplies that identifies anything. There is no `tenant_code` and no `email`
    field — both are read from the invitation row, so a caller cannot assert
    which tenant or which account they are activating.

    Returns the activated user and nothing else. No session is issued: the
    prototype's form submits with "Set and return to sign in" (dc.html L1045),
    and signing in afterwards proves the password that was just set is the
    password the invitee meant.
    """
    async with session.begin():
        user = await service.accept_invitation(
            session,
            token=body.token,
            password=body.password,
            password_confirmation=body.password_confirmation,
        )
        return UserResponse(
            tenant_user_id=user.tenant_user_id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            last_authenticated_at=user.last_authenticated_at,
        )


@router.get("/me", response_model=MeResponse, summary="The signed-in user")
async def me(principal: CurrentTenant) -> MeResponse:
    return MeResponse(
        tenant_user_id=principal.user.tenant_user_id,
        tenant_id=principal.tenant_id,
        email=principal.user.email,
        display_name=principal.user.display_name,
        role=principal.user.role,
        status=principal.user.status,
    )


__all__ = ["router"]
