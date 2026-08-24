"""API credential management.

Session-authenticated only. A credential cannot reach these routes, and that is
the scope-delegation refusal made structural rather than conditional: there is
no code path here that inspects a credential's scopes and decides, because no
credential arrives in the first place. `refuse_scope_delegation` in `deps.py`
guards the case that appears the day a provisioning route is added.

Both tenant roles may manage credentials (BACKEND_PLAN §12.3, and dc.html L1258
lists "Credential management" as true for both), which is the one capability the
two roles share. That is deliberate in the product: a developer who cannot
issue a credential cannot integrate anything.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from apps.control_api.deps import (
    ApiKeyRateLimit,
    CurrentTenant,
    TenantAudit,
    get_settings_dep,
)
from apps.control_api.schemas import (
    CreateCredentialRequest,
    CredentialListResponse,
    CredentialResponse,
    IssuedCredentialResponse,
    RotateCredentialRequest,
    ScopeDescriptor,
    ScopeListResponse,
)
from graphrec.common.config import Settings
from graphrec.common.enums import (
    SCOPE_LABELS,
    SCOPE_SHORT_LABELS,
    AuditAction,
    CredentialScope,
    CredentialState,
)
from graphrec.db.models import ApiKey
from graphrec.domain.credentials import CredentialService

router = APIRouter(tags=["credentials"])


def _service(settings: Annotated[Settings, Depends(get_settings_dep)]) -> CredentialService:
    return CredentialService(
        pepper=settings.api_key_hmac_pepper.get_secret_value(),
        hash_version=settings.api_key_hash_version,
        max_active_per_tenant=settings.max_active_api_keys_per_tenant,
        max_scopes=settings.max_api_key_scopes,
        max_name_length=settings.max_api_key_name_length,
        max_grace_seconds=settings.max_api_key_grace_seconds,
    )


Service = Annotated[CredentialService, Depends(_service)]


def _view(api_key: ApiKey, *, now: dt.datetime) -> CredentialResponse:
    """Render one credential, with its gate-5 preconditions resolved here.

    `can_rotate`, `can_revoke` and `blocked_reason` are computed on the server
    so the console disables a control and shows *the server's* reason, rather
    than deciding for itself and drifting. The prototype's own table does this
    client-side at L1118-1119; a real client must not, for the same reason it
    must not derive `state` — it does not own the clock or the rules.
    """
    state = api_key.state(now=now)
    revoked = state is CredentialState.REVOKED

    # dc.html L1118: rotate is disabled for a revoked credential and carries
    # this reason. L1119: revoke is disabled too, and carries *no* reason —
    # reproduced exactly, because a revoked credential being un-revokable is
    # self-evident from the row and the prototype declines to restate it.
    blocked_reason = "Revoked credentials cannot be rotated." if revoked else None

    return CredentialResponse(
        key_id=api_key.key_id,
        name=api_key.name,
        visible_prefix=api_key.visible_prefix,
        scopes=[CredentialScope(value) for value in api_key.scopes],
        state=state,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
        can_rotate=not revoked,
        can_revoke=not revoked,
        blocked_reason=blocked_reason,
        grace_expires_at=(api_key.previous_expires_at if api_key.grace_is_open(now=now) else None),
    )


@router.get("/scopes", response_model=ScopeListResponse, summary="The scope catalogue")
async def list_scopes() -> ScopeListResponse:
    """Serves the create and rotate dialogs' checkbox list (dc.html L1134).

    Needs no credential of its own: the vocabulary is public, identical for
    every tenant, and already visible in the published API contract. Gating it
    would imply the names are sensitive, which would be theatre.
    """
    return ScopeListResponse(
        scopes=[
            ScopeDescriptor(
                scope=scope,
                label=SCOPE_LABELS[scope],
                short_label=SCOPE_SHORT_LABELS[scope],
            )
            for scope in CredentialScope
        ]
    )


@router.get("/api-keys", response_model=CredentialListResponse, summary="List credentials")
async def list_credentials(
    principal: CurrentTenant,
    service: Service,
    state: Annotated[CredentialState | None, Query()] = None,
) -> CredentialListResponse:
    """`?state=usable` backs the /integration page (BACKEND_PLAN §12.3)."""
    now = dt.datetime.now(dt.UTC)
    rows = await service.list_for_tenant(principal.session, state=state)
    # Unpaginated: a tenant holds a handful of credentials, not a page of them.
    # `total` is here for the same reason `UserListResponse` carries one.
    return CredentialListResponse(
        credentials=[_view(row, now=now) for row in rows], total=len(rows)
    )


@router.post(
    "/api-keys",
    response_model=IssuedCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a credential",
    # Every route here that mints or invalidates a secret, and none that only
    # read: `MAX_ACTIVE_API_KEYS_PER_TENANT` bounds how many can exist at once
    # but not how fast they can be cycled, and each cycle is an argon2 hash and
    # an audit row.
    dependencies=[ApiKeyRateLimit],
)
async def create_credential(
    body: CreateCredentialRequest,
    principal: CurrentTenant,
    service: Service,
    audit: TenantAudit,
) -> IssuedCredentialResponse:
    """One of exactly two routes that ever return a secret.

    Audited, and note what the details carry: the credential's name and its
    scopes. Not the secret, not its prefix, not the digest. `safe_details`
    would redact a key called `secret` anyway, but the real defence is that the
    handler never offers one — the audit trail records that a credential was
    issued, which is the fact an investigation needs, and knowing *which*
    credential is what `resource_ref` is for.
    """
    async with audit.action(AuditAction.CREDENTIAL, resource_type="api_key") as entry:
        issued = await service.create(
            principal.session,
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            name=body.name,
            scopes=[scope.value for scope in body.scopes],
            expires_in_days=body.expires_in_days,
        )
        entry.resource_ref = issued.api_key.key_id
        entry.details = {
            "operation": "create",
            "name": body.name,
            "scopes": ",".join(scope.value for scope in body.scopes),
        }
    return IssuedCredentialResponse(
        credential=_view(issued.api_key, now=dt.datetime.now(dt.UTC)),
        secret=issued.secret,
    )


@router.get(
    "/api-keys/{key_id}", response_model=CredentialResponse, summary="Describe a credential"
)
async def describe_credential(
    key_id: uuid.UUID, principal: CurrentTenant, service: Service
) -> CredentialResponse:
    api_key = await service.get(principal.session, key_id=key_id)
    return _view(api_key, now=dt.datetime.now(dt.UTC))


@router.post(
    "/api-keys/{key_id}:rotate",
    dependencies=[ApiKeyRateLimit],
    response_model=IssuedCredentialResponse,
    summary="Rotate a credential",
)
async def rotate_credential(
    key_id: uuid.UUID,
    body: RotateCredentialRequest,
    principal: CurrentTenant,
    service: Service,
    audit: TenantAudit,
) -> IssuedCredentialResponse:
    """The second and last route that returns a secret.

    Twice in a credential's life, then — at creation and here — and never
    retrievable afterwards. There is no read route that returns a secret and no
    column that could serve one.
    """
    async with audit.action(
        AuditAction.CREDENTIAL, resource_type="api_key", resource_ref=key_id
    ) as entry:
        issued = await service.rotate(
            principal.session,
            key_id=key_id,
            scopes=None if body.scopes is None else [scope.value for scope in body.scopes],
            grace_seconds=body.grace_seconds,
            reason=body.reason,
        )
        entry.details = {
            "operation": "rotate",
            "grace_seconds": body.grace_seconds,
            # The tenant's own words for why. Truncated by `safe_details`, and
            # the reason a rotation reads as deliberate rather than as an
            # unexplained key change six months later.
            "reason": body.reason,
        }
    return IssuedCredentialResponse(
        credential=_view(issued.api_key, now=dt.datetime.now(dt.UTC)),
        secret=issued.secret,
    )


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a credential",
)
async def revoke_credential(
    key_id: uuid.UUID, principal: CurrentTenant, service: Service, audit: TenantAudit
) -> Response:
    """Immediate and irreversible (dc.html L1157). Repeating it is safe.

    `DELETE` is the verb the recovered inventory uses, but nothing is deleted:
    no role holds a `DELETE` grant on `api_keys`, and the row survives with
    `revoked_at` set. A credential that submitted events is part of the audit
    trail.
    """
    async with audit.action(
        AuditAction.CREDENTIAL,
        resource_type="api_key",
        resource_ref=key_id,
        details={"operation": "revoke"},
    ):
        await service.revoke(principal.session, key_id=key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
