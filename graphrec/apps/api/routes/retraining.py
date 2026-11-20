"""XR-F-02 / XR-F-03: tenant retraining policy (schedule + event trigger)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.retraining.service import RetrainingService
from graphrec_core.schemas.retraining import RetrainingPolicyResource, RetrainingPolicyUpdate

router = APIRouter(prefix="/v1", tags=["training"])


@router.get("/retraining-policy", response_model=RetrainingPolicyResource)
def get_retraining_policy(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RetrainingPolicyResource:
    principal.require_scope("training:read")
    return RetrainingService(db, principal).get_policy(principal.tenant_id)


@router.put("/retraining-policy", response_model=RetrainingPolicyResource)
def put_retraining_policy(
    payload: RetrainingPolicyUpdate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RetrainingPolicyResource:
    principal.require_scope("training:write")
    return RetrainingService(db, principal, request.state.correlation_id).update_policy(principal.tenant_id, payload)
