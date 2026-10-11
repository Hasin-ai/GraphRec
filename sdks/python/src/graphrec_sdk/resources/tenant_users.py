"""Tenant user administration (``/v1/tenant/users``) - administrator bearer tokens only."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union, cast
from uuid import UUID

from ..errors import InputValidationError
from ..models.tenant_users import TenantUser, TenantUserInvitation, TenantUserList
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncTenantUsers", "TenantUsers"]

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


def _update_body(role: Optional[str], status: Optional[str], reason: Optional[str]) -> Dict[str, Any]:
    if role is not None and role not in ROLES:
        raise InputValidationError(f"role must be one of {ROLES}")
    if status is not None and status not in ("active", "locked", "disabled"):
        raise InputValidationError("status must be active, locked or disabled")
    body = {k: v for k, v in (("role", role), ("status", status), ("reason", reason)) if v is not None}
    if not set(body) - {"reason"}:
        raise InputValidationError("provide role or status")
    return body


class TenantUsers(SyncResource):
    """Tenant user administration. Administrator bearer tokens only (scope ``users:write``)."""

    def list(self) -> TenantUserList:
        """``GET /v1/tenant/users``."""

        return cast(
            TenantUserList, self._client.request("tenant_users.list", cast_to=TenantUserList)
        )

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

    def get(self, user_id: Union[str, UUID]) -> TenantUser:
        """``GET /v1/tenant/users/{user_id}``."""
        return cast(TenantUser, self._client.request("tenant_users.get", path_params={"user_id": user_id}, cast_to=TenantUser))

    def update(self, user_id: Union[str, UUID], *, role: Optional[str] = None, status: Optional[str] = None,
               reason: Optional[str] = None) -> TenantUser:
        """Change a member's role or status (``active``, ``locked``, ``disabled``).

        ``PATCH /v1/tenant/users/{user_id}``. Ends the member's sessions. The last
        active administrator cannot be demoted, locked or disabled (ConflictError).
        """
        return cast(TenantUser, self._client.request("tenant_users.update", path_params={"user_id": user_id},
                                                     json=_update_body(role, status, reason), cast_to=TenantUser))

    def resend_invitation(self, user_id: Union[str, UUID]) -> TenantUserInvitation:
        """Issue a new one-time setup link; the previous one stops working."""
        return cast(TenantUserInvitation, self._client.request(
            "tenant_users.resend_invitation", path_params={"user_id": user_id}, cast_to=TenantUserInvitation))

    def revoke_invitation(self, user_id: Union[str, UUID]) -> TenantUser:
        """Withdraw a pending invitation; its one-time setup link stops working.

        ``DELETE /v1/tenant/users/{user_id}/invitation``. Raises
        :class:`~graphrec_sdk.NotFoundError` for unknown users and a
        :class:`~graphrec_sdk.ConflictError` when the user is no longer invited.
        """

        return cast(
            TenantUser,
            self._client.request(
                "tenant_users.revoke_invitation",
                path_params={"user_id": user_id},
                cast_to=TenantUser,
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

    async def get(self, user_id: Union[str, UUID]) -> TenantUser:
        """``GET /v1/tenant/users/{user_id}``."""
        return cast(TenantUser, await self._client.request("tenant_users.get", path_params={"user_id": user_id}, cast_to=TenantUser))

    async def update(self, user_id: Union[str, UUID], *, role: Optional[str] = None, status: Optional[str] = None,
               reason: Optional[str] = None) -> TenantUser:
        """Change a member's role or status (``active``, ``locked``, ``disabled``).

        ``PATCH /v1/tenant/users/{user_id}``. Ends the member's sessions. The last
        active administrator cannot be demoted, locked or disabled (ConflictError).
        """
        return cast(TenantUser, await self._client.request("tenant_users.update", path_params={"user_id": user_id},
                                                     json=_update_body(role, status, reason), cast_to=TenantUser))

    async def resend_invitation(self, user_id: Union[str, UUID]) -> TenantUserInvitation:
        """Issue a new one-time setup link; the previous one stops working."""
        return cast(TenantUserInvitation, await self._client.request(
            "tenant_users.resend_invitation", path_params={"user_id": user_id}, cast_to=TenantUserInvitation))

    async def revoke_invitation(self, user_id: Union[str, UUID]) -> TenantUser:
        """Async variant of :meth:`TenantUsers.revoke_invitation`."""

        return cast(
            TenantUser,
            await self._client.request(
                "tenant_users.revoke_invitation",
                path_params={"user_id": user_id},
                cast_to=TenantUser,
            ),
        )
