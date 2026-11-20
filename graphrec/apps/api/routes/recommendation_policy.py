"""XR-F-04: tenant diversity and freshness re-ranking rules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.recommendation_policy_service import RecommendationPolicyService
from graphrec_core.schemas.recommendation_policy import RecommendationPolicyResource, RecommendationPolicyUpdate

router = APIRouter(prefix="/v1", tags=["recommendations"])


@router.get("/recommendation-policy", response_model=RecommendationPolicyResource)
def get_recommendation_policy(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RecommendationPolicyResource:
    principal.require_scope("models:read")
    return RecommendationPolicyService(db, principal).get(principal.tenant_id)


@router.put("/recommendation-policy", response_model=RecommendationPolicyResource)
def put_recommendation_policy(
    payload: RecommendationPolicyUpdate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> RecommendationPolicyResource:
    principal.require_scope("models:deploy")
    return RecommendationPolicyService(db, principal, request.state.correlation_id).update(principal.tenant_id, payload)
