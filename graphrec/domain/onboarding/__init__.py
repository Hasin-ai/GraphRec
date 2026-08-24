"""The `/home` checklist, computed server-side.

BUILD_PROMPT §10.9 names `GET /v1/onboarding` as one of the seven endpoints that
exist only because the console cannot compute what the prototype computed. The
prototype held the entire mock store in memory and worked out `hasProducts`,
`hasEvents`, `okJob` and `act` inline (dc.html L1088). A real client would need
five list calls and would still be reading five inconsistent moments.
"""

from graphrec.domain.onboarding.service import (
    OnboardingService,
    OnboardingState,
    OnboardingStep,
)

__all__ = ["OnboardingService", "OnboardingState", "OnboardingStep"]
