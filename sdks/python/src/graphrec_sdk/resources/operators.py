"""D-04: operator sign-in and operator management (``/v1/platform/operators``)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, cast
from uuid import UUID

from ..models.operators import Operator, OperatorList, OperatorMe, OperatorSession
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncPlatformOperators", "PlatformOperators"]


def _update_body(display_name: Optional[str], roles: Optional[List[str]], status: Optional[str],
                 password: Optional[str]) -> Dict[str, Any]:
    body = {"display_name": display_name, "roles": roles, "status": status, "password": password}
    return {k: v for k, v in body.items() if v is not None}


class PlatformOperators(SyncResource):
    """Named operators with roles. Requires the ``operator_admin`` role."""

    def login(self, *, email: str, password: str) -> OperatorSession:
        """Sign in as an operator (``POST /v1/platform/auth/login``); use the returned
        ``access_token`` as the platform bearer token."""
        return cast(OperatorSession, self._client.request(
            "operators.login", json={"email": email, "password": password}, cast_to=OperatorSession))

    def me(self) -> OperatorMe:
        """The signed-in operator and roles (``GET /v1/platform/me``)."""
        return cast(OperatorMe, self._client.request("operators.me", cast_to=OperatorMe))

    def list(self) -> OperatorList:
        return cast(OperatorList, self._client.request("operators.list", cast_to=OperatorList))

    def create(self, *, email: str, display_name: str, password: str, roles: List[str]) -> Operator:
        return cast(Operator, self._client.request("operators.create", json={
            "email": email, "display_name": display_name, "password": password, "roles": roles}, cast_to=Operator))

    def update(self, operator_id: Union[str, UUID], *, display_name: Optional[str] = None,
               roles: Optional[List[str]] = None, status: Optional[str] = None,
               password: Optional[str] = None) -> Operator:
        """Change name, roles, status (``active``/``disabled``) or password; access changes end sessions."""
        return cast(Operator, self._client.request(
            "operators.update", path_params={"operator_id": operator_id},
            json=_update_body(display_name, roles, status, password), cast_to=Operator))


class AsyncPlatformOperators(AsyncResource):
    """Async variant of :class:`PlatformOperators`."""

    async def login(self, *, email: str, password: str) -> OperatorSession:
        return cast(OperatorSession, await self._client.request(
            "operators.login", json={"email": email, "password": password}, cast_to=OperatorSession))

    async def me(self) -> OperatorMe:
        return cast(OperatorMe, await self._client.request("operators.me", cast_to=OperatorMe))

    async def list(self) -> OperatorList:
        return cast(OperatorList, await self._client.request("operators.list", cast_to=OperatorList))

    async def create(self, *, email: str, display_name: str, password: str, roles: List[str]) -> Operator:
        return cast(Operator, await self._client.request("operators.create", json={
            "email": email, "display_name": display_name, "password": password, "roles": roles}, cast_to=Operator))

    async def update(self, operator_id: Union[str, UUID], *, display_name: Optional[str] = None,
                     roles: Optional[List[str]] = None, status: Optional[str] = None,
                     password: Optional[str] = None) -> Operator:
        return cast(Operator, await self._client.request(
            "operators.update", path_params={"operator_id": operator_id},
            json=_update_body(display_name, roles, status, password), cast_to=Operator))
