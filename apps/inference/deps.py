"""Gates 1, 2 and 3 for the data plane, and the pin that makes 4 unnecessary.

The credential realm only. A session token presented here is refused, because
`/v1/recommendations` is a program's endpoint and a person's browser has no
business holding a customer's session identifier. That is the same realm
separation `apps/control_api/deps.py` enforces from the other side.

**This file is not an import of the control API's, and that is deliberate.** The
import-linter contract in `pyproject.toml` forbids one app from importing
another, and the reason is visible here: this process resolves a *pinned* tenant
and refuses any credential belonging to anyone else, which the control API must
never do. Sharing the dependency would mean one function with a mode flag, and
the mode flag would be the thing an audit had to reason about. What *is* shared
is `graphrec.domain.credentials`, where a presented secret becomes a verified
credential — there is still exactly one implementation of that.

**Gate 4 does not appear here because there is nothing to own.** Every route in
this app addresses the tenant's own recommendations, and RLS binds the session
to the tenant the credential resolved to. A request naming another tenant's
product does not get a `403`; it gets a product that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from graphrec.common.config import Settings
from graphrec.common.enums import CredentialScope
from graphrec.common.errors import AuthError, ForbiddenError
from graphrec.common.logging import actor_id_var, tenant_id_var
from graphrec.db.models import Tenant
from graphrec.domain.credentials.service import CredentialService

# `HTTPAuthorizationCredentials` and `Settings` are imported at runtime, not
# under `TYPE_CHECKING`. `from __future__ import annotations` makes every
# annotation a string, and FastAPI resolves the ones on a dependency's
# parameters against this module's globals. A name it cannot resolve does not
# raise — the parameter silently stops being a dependency and becomes a *body*
# field, so every authenticated route answers 422 asking for `credentials`.
if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator, Callable, Coroutine
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.db.models import ApiKey

# `auto_error=False` so a missing header raises this module's `AuthError` with
# the approved copy, rather than FastAPI's own 403 with a body nothing designed.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class DataPlanePrincipal:
    """A verified credential, its scopes, and a session bound to its tenant."""

    api_key: ApiKey
    scopes: frozenset[CredentialScope]
    session: AsyncSession

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.api_key.tenant_id

    @property
    def key_id(self) -> uuid.UUID:
        return self.api_key.key_id

    def has(self, scope: CredentialScope) -> bool:
        return scope in self.scopes


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_tenant_id(request: Request) -> uuid.UUID:
    """The tenant this process is pinned to (`GRAPHREC_TENANT_ID`)."""
    pinned: uuid.UUID = request.app.state.tenant_id
    return pinned


async def current_credential(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AsyncIterator[DataPlanePrincipal]:
    """Gates 1 and 2, plus the process pin.

    Order matters and is the same as everywhere else: verify, then bind, then
    read. `CredentialService.verify` binds `app.tenant_id` from the credential
    it resolved, so every query after it — including the one that loads the
    tenant — runs inside the tenant's own row-level view.

    **The pin is checked before anything is yielded.** A credential belonging to
    another tenant is a valid credential presented to the wrong process, most
    likely a misrouted request. It is refused with the same message as an
    invalid one: telling a caller "your credential is fine, but this process
    serves someone else" would confirm that both tenants exist.
    """
    presented = _token(credentials)

    service = CredentialService(
        pepper=settings.api_key_hmac_pepper.get_secret_value(),
        hash_version=settings.api_key_hash_version,
        max_active_per_tenant=settings.max_active_api_keys_per_tenant,
        max_scopes=settings.max_api_key_scopes,
        max_name_length=settings.max_api_key_name_length,
        max_grace_seconds=settings.max_api_key_grace_seconds,
    )

    pinned: uuid.UUID = request.app.state.tenant_id
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as bound, bound.begin():
        verified = await service.verify(bound, presented=presented)
        if verified.tenant_id != pinned:
            raise AuthError("invalid_credentials")

        tenant = await bound.scalar(select(Tenant).where(Tenant.tenant_id == verified.tenant_id))
        if tenant is None:
            raise AuthError("invalid_credentials")

        # ------------------------------------------------ gate 2: tenant state
        if not tenant.is_operable:
            raise ForbiddenError("tenant_not_active")

        tenant_id_var.set(str(verified.tenant_id))
        # The credential is the actor. Never the prefix and never the secret.
        actor_id_var.set(str(verified.api_key.key_id))

        yield DataPlanePrincipal(
            api_key=verified.api_key,
            scopes=verified.scopes,
            session=bound,
        )


CurrentCredential = Annotated[DataPlanePrincipal, Depends(current_credential)]


def require_scope(
    *scopes: CredentialScope,
) -> Callable[[DataPlanePrincipal], Coroutine[Any, Any, DataPlanePrincipal]]:
    """Require **all** the named scopes, before the work rather than after.

    dc.html L1170: "Only the operations granted to a credential may be performed
    with it. Anything else is rejected before the operation is accepted." A
    refused call therefore writes no `recommendation_requests` row and moves no
    usage counter.
    """
    required = frozenset(scopes)

    async def _guard(principal: CurrentCredential) -> DataPlanePrincipal:
        if not required.issubset(principal.scopes):
            raise ForbiddenError("insufficient_scope")
        return principal

    return _guard


RequireRecommendations = Annotated[
    DataPlanePrincipal, Depends(require_scope(CredentialScope.RECOMMENDATIONS_READ))
]
RequireFeedback = Annotated[
    DataPlanePrincipal, Depends(require_scope(CredentialScope.FEEDBACK_WRITE))
]


def _token(credentials: HTTPAuthorizationCredentials | None) -> str:
    """One message for absent, malformed and unverifiable.

    Distinguishing them would tell a caller whether what they sent was *shaped*
    like a credential, which is a small oracle given away for nothing.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("invalid_credentials")
    return credentials.credentials


__all__ = [
    "CurrentCredential",
    "DataPlanePrincipal",
    "RequireFeedback",
    "RequireRecommendations",
    "current_credential",
    "get_settings_dep",
    "get_tenant_id",
    "require_scope",
]
