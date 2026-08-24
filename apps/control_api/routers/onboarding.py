"""`GET /v1/onboarding` — what `/home` renders above its launcher.

Open to both roles. A developer who cannot invite users still needs to see that
somebody has to, because the step they *can* do is blocked until it happens; a
checklist that hid other people's steps would leave them staring at a working
page and an integration that returns nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.control_api.deps import CurrentTenant
from apps.control_api.schemas import OnboardingResponse, OnboardingStepBody
from graphrec.domain.onboarding import OnboardingService

router = APIRouter(tags=["onboarding"])


def _service() -> OnboardingService:
    return OnboardingService()


Service = Annotated[OnboardingService, Depends(_service)]


@router.get("/onboarding", response_model=OnboardingResponse, summary="The §3.5 checklist")
async def get_onboarding(principal: CurrentTenant, service: Service) -> OnboardingResponse:
    """Eight existence queries in one transaction, so the answers agree with each other.

    Eight round trips is the cost of the guarantee. The alternative — one query
    with eight correlated subselects — is faster and unreadable, and this runs
    once per visit to a page somebody opens a few times a day.
    """
    state = await service.state(principal.session)
    role = principal.user.role
    return OnboardingResponse(
        steps=[
            OnboardingStepBody(
                key=step.key,
                title=step.title,
                detail=step.detail,
                route=step.route,
                complete=step.complete,
                required_role=step.required_role,
                permitted=step.required_role is None or step.required_role == role,
            )
            for step in state.steps
        ],
        completed=state.completed,
        total=state.total,
    )


__all__ = ["router"]
