"""D-04: operator sign-in and operator account management."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.platform import (
    ROLES,
    OperatorPrincipal,
    platform_administrator,
)
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError

Role = Literal["platform", "plan_management", "monitoring", "audit", "operator_admin"]

router = APIRouter(prefix="/v1/platform", tags=["platform"], dependencies=[Depends(platform_administrator)])


class OperatorLogin(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class OperatorSession(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    operator_id: UUID
    email: str
    display_name: str
    roles: list[Role]


class OperatorResource(BaseModel):
    id: UUID
    email: str
    display_name: str
    roles: list[Role]
    status: Literal["active", "disabled"]
    created_at: datetime
    last_login_at: datetime | None = None


class OperatorList(BaseModel):
    items: list[OperatorResource]


class OperatorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    roles: list[Role] = Field(min_length=1, max_length=len(ROLES))


class OperatorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    roles: list[Role] | None = Field(default=None, min_length=1, max_length=len(ROLES))
    status: Literal["active", "disabled"] | None = None
    password: str | None = Field(default=None, min_length=12, max_length=1024)


class Me(BaseModel):
    operator_id: UUID | None
    email: str | None
    roles: list[Role]
    kind: Literal["operator", "bootstrap_token"]


def _security_event(db: Session, event_type: str, severity: str, detail: dict, source: str = "operator-api") -> None:
    db.execute(text("INSERT INTO security_events (id, tenant_id, event_type, severity, source_hash, sanitized_detail, occurred_at) "
                    "VALUES (:id, NULL, :type, :severity, :source, CAST(:detail AS jsonb), now())"),
               {"id": uuid4(), "type": event_type, "severity": severity, "source": protected_auth_hash(source),
                "detail": json.dumps(detail)})


@router.get("/me", response_model=Me)
def whoami(request: Request) -> Me:
    principal: OperatorPrincipal = request.state.operator
    return Me(operator_id=principal.operator_id, email=principal.email, roles=sorted(principal.roles),
              kind=principal.kind)  # type: ignore[arg-type]


SELECT_OPERATOR = ("SELECT id, email::text AS email, display_name, roles, status, created_at, last_login_at "
                   "FROM platform_operators")


@router.get("/operators", response_model=OperatorList)
def list_operators(db: Session = Depends(get_db)) -> OperatorList:
    rows = db.execute(text(SELECT_OPERATOR + " ORDER BY created_at")).mappings().all()
    return OperatorList(items=[OperatorResource(**row) for row in rows])


@router.post("/operators", response_model=OperatorResource, status_code=201)
def create_operator(payload: OperatorCreate, request: Request, db: Session = Depends(get_db)) -> OperatorResource:
    principal: OperatorPrincipal = request.state.operator
    try:
        row = db.execute(text(
            "INSERT INTO platform_operators (id, email, display_name, password_hash, roles, created_by) "
            "VALUES (:id, :email, :name, :hash, :roles, :by) RETURNING id, email::text AS email, display_name, roles, "
            "status, created_at, last_login_at"),
            {"id": uuid4(), "email": str(payload.email), "name": payload.display_name,
             "hash": hash_password(payload.password), "roles": sorted(set(payload.roles)),
             "by": principal.operator_id}).mappings().one()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "duplicate_resource", "An operator with this email already exists.",
                       details={"fields": [{"field": "email", "message": "Already in use"}]}) from exc
    _security_event(db, "operator_created", "info", {"operator_id": str(row["id"]), "roles": sorted(payload.roles),
                    "created_by": str(principal.operator_id) if principal.operator_id else "bootstrap_token",
                    "correlation_id": str(request.state.correlation_id)})
    db.commit()
    return OperatorResource(**row)


@router.patch("/operators/{operator_id}", response_model=OperatorResource)
def update_operator(operator_id: UUID, payload: OperatorUpdate, request: Request,
                    db: Session = Depends(get_db)) -> OperatorResource:
    principal: OperatorPrincipal = request.state.operator
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise ApiError(422, "validation_failed", "Provide at least one change.")
    if principal.operator_id == operator_id and (changes.get("status") == "disabled"
                                                  or ("roles" in changes and "operator_admin" not in changes["roles"])):
        raise ApiError(409, "conflict", "You cannot disable yourself or remove your own operator_admin role.")
    sets, params = [], {"id": operator_id}
    if "display_name" in changes:
        sets.append("display_name = :name"); params["name"] = changes["display_name"]
    if "roles" in changes:
        sets.append("roles = :roles"); params["roles"] = sorted(set(changes["roles"]))
    if "status" in changes:
        sets.append("status = :status"); params["status"] = changes["status"]
    if "password" in changes:
        sets.append("password_hash = :hash"); params["hash"] = hash_password(changes["password"])
    # Any change to access ends the operator's current sessions.
    if {"roles", "status", "password"} & set(changes):
        sets.append("auth_epoch = auth_epoch + 1")
    row = db.execute(text(f"UPDATE platform_operators SET {', '.join(sets)} WHERE id = :id RETURNING id, email::text AS email, "
                          "display_name, roles, status, created_at, last_login_at"), params).mappings().one_or_none()
    if row is None:
        db.rollback()
        raise ApiError(404, "resource_not_found", "Operator not found.")
    _security_event(db, "operator_updated", "info", {"operator_id": str(operator_id), "changed": sorted(changes) ,
                    "by": str(principal.operator_id) if principal.operator_id else "bootstrap_token",
                    "correlation_id": str(request.state.correlation_id)})
    db.commit()
    return OperatorResource(**row)
