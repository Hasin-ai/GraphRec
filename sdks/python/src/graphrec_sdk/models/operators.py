"""D-04: platform operator models."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from ._base import GraphRecModel, ItemList

__all__ = ["Operator", "OperatorList", "OperatorMe", "OperatorSession"]


class OperatorSession(GraphRecModel):
    """Result of ``POST /v1/platform/auth/login``."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    operator_id: UUID
    email: str
    display_name: str
    roles: List[str]


class Operator(GraphRecModel):
    id: UUID
    email: str
    display_name: str
    roles: List[str]
    status: str
    created_at: datetime
    last_login_at: Optional[datetime] = None


class OperatorList(ItemList[Operator]):
    pass


class OperatorMe(GraphRecModel):
    operator_id: Optional[UUID] = None
    email: Optional[str] = None
    roles: List[str]
    kind: str
