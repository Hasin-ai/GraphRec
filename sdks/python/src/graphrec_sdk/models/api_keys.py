from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from ._base import GraphRecModel, ItemList

__all__ = ["ApiKey", "ApiKeyList", "ApiKeyWithSecret"]


class ApiKey(GraphRecModel):
    id: UUID
    name: str
    #: Non-secret identifier such as ``gr_live_AbCdEfGh``.
    prefix: str
    scopes: List[str]
    #: ``active``, ``expired`` or ``revoked``.
    status: str
    expires_at: Optional[datetime] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    #: While set and in the future, the previous secret is still accepted.
    grace_expires_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class ApiKeyWithSecret(ApiKey):
    """Returned once by create/rotate. Store ``secret`` now - it cannot be read again."""

    secret: str

    def __repr__(self) -> str:
        return (
            f"ApiKeyWithSecret(id={self.id!s}, name={self.name!r}, "
            f"prefix={self.prefix!r}, secret=***)"
        )


class ApiKeyList(ItemList[ApiKey]):
    pass
