"""Tenant user administration (``/v1/tenant/users``) - administrator bearer tokens only."""

from __future__ import annotations

from typing import Any, Dict, Optional, cast

from ..errors import InputValidationError
from ..models.tenant_users import TenantUserInvitation, TenantUserList
from ._base import AsyncResource, SyncResource

ROLES = ("tenant_administrator", "tenant_developer")


def _invite_body(email: str, role: str, display_name: Optional[str]) -> Dict[str, Any]:
    if not email or "@" not in email:
        raise InputValidationError("email must be a valid address")
    if role not in ROLES:
        raise InputValidationError(f"role must be one of {ROLES}")
    body: Dict[str, Any] = {"email": email, "role": role}
    if display_name is not None:
        body["display_name"] = display_name
    return body


class TenantUsers(SyncResource):
    def list(self) -> TenantUserList:
        """``GET /v1/tenant/users``."""

        return cast(TenantUserList, self._client.request("tenant_users.list", cast_to=TenantUserList))

    def invite(
        self, email: str, *, role: str = "tenant_developer", display_name: Optional[str] = None
    ) -> TenantUserInvitation:
        """Invite a user (``POST /v1/tenant/users``).

        The response carries a one-time ``setup_token`` the invitee redeems with
        :meth:`Authentication.setup_password`; it is never shown again.
        """

        return cast(
            TenantUserInvitation,
            self._client.request(
                "tenant_users.invite",
                json=_invite_body(email, role, display_name),
                cast_to=TenantUserInvitation,
            ),
        )


class AsyncTenantUsers(AsyncResource):
    async def list(self) -> TenantUserList:
        """Async variant of :meth:`TenantUsers.list`."""

        return cast(
            TenantUserList, await self._client.request("tenant_users.list", cast_to=TenantUserList)
        )

    async def invite(
        self, email: str, *, role: str = "tenant_developer", display_name: Optional[str] = None
    ) -> TenantUserInvitation:
        """Async variant of :meth:`TenantUsers.invite`."""

        return cast(
            TenantUserInvitation,
            await self._client.request(
                "tenant_users.invite",
                json=_invite_body(email, role, display_name),
                cast_to=TenantUserInvitation,
            ),
        )
