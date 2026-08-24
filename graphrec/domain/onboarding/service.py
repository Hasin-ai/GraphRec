"""What a tenant has actually done, in the order SRS §3.5 tells them to do it.

Eight steps, each answering one question with one existence query. The queries
carry no `tenant_id` predicate: the session is bound, so every count is already
this tenant's, and a predicate added here would be a second copy of a check the
database makes — the copy being the one that drifts.

Two properties are deliberate and easy to lose:

* **A step is complete because something exists, never because a later step
  is.** "Activate a version" does not mark "review quality" complete, even
  though you cannot activate without a version. If the states can disagree —
  and after an archive they can — the checklist should say so rather than
  paper over it.
* **A step the caller's role cannot perform is still shown.** A developer sees
  "configure users" as somebody else's step with a reason, not as a missing
  row, because a checklist with holes in it reads as a broken checklist.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.enums import (
    DeploymentState,
    JobState,
    ModelVersionStatus,
    TenantRole,
    UserStatus,
)
from graphrec.db.models import (
    ApiKey,
    InteractionEvent,
    ModelDeployment,
    ModelVersion,
    Product,
    TenantUser,
    TrainingJob,
    UsageEvent,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclasses.dataclass(frozen=True, slots=True)
class OnboardingStep:
    """One row of the checklist."""

    key: str
    title: str
    detail: str
    route: str
    complete: bool
    #: `None` when any role may perform it.
    required_role: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class OnboardingState:
    steps: tuple[OnboardingStep, ...]

    @property
    def completed(self) -> int:
        return sum(1 for step in self.steps if step.complete)

    @property
    def total(self) -> int:
        return len(self.steps)


_ADMIN = TenantRole.TENANT_ADMINISTRATOR.value
_DEVELOPER = TenantRole.TENANT_DEVELOPER.value


class OnboardingService:
    async def _exists(self, session: AsyncSession, query: sa.Select[Any]) -> bool:
        """`EXISTS`, not `count`. The question is never "how many"."""
        return bool(await session.scalar(sa.select(sa.literal(True)).where(query.exists())))

    async def state(self, session: AsyncSession) -> OnboardingState:
        has_other_user = await self._exists(
            session,
            sa.select(TenantUser.tenant_user_id).where(
                TenantUser.status.in_((UserStatus.INVITED.value, UserStatus.ACTIVE.value)),
                # The registering administrator does not count: they exist
                # because the tenant exists, so counting them would mark this
                # step complete before anybody has done anything.
                TenantUser.role == _DEVELOPER,
            ),
        )
        has_credential = await self._exists(
            session, sa.select(ApiKey.key_id).where(ApiKey.revoked_at.is_(None))
        )
        has_products = await self._exists(session, sa.select(Product.product_id))
        has_events = await self._exists(session, sa.select(InteractionEvent.event_id))
        has_training = await self._exists(session, sa.select(TrainingJob.training_job_id))
        has_succeeded = await self._exists(
            session,
            sa.select(TrainingJob.training_job_id).where(
                TrainingJob.state == JobState.SUCCEEDED.value
            ),
        )
        has_active_version = await self._exists(
            session,
            sa.select(ModelVersion.model_version_id).where(
                ModelVersion.status == ModelVersionStatus.ACTIVE.value
            ),
        )
        # "Monitor" is complete once there is something to monitor: a deployment
        # that has left `pending`, or any metered activity at all. A tenant who
        # has served nothing has not finished onboarding, however many boxes
        # above are ticked.
        has_serving = await self._exists(
            session,
            sa.select(ModelDeployment.deployment_id).where(
                ModelDeployment.state != DeploymentState.PENDING.value
            ),
        )
        has_usage = await self._exists(session, sa.select(UsageEvent.usage_event_id))

        return OnboardingState(
            steps=(
                OnboardingStep(
                    key="configure_users",
                    title="Invite the people who will use this",
                    detail=(
                        "A developer integrates the API; an administrator manages the catalogue "
                        "and the model."
                    ),
                    route="/users",
                    complete=has_other_user,
                    required_role=_ADMIN,
                ),
                OnboardingStep(
                    key="create_credential",
                    title="Create an API credential",
                    detail=(
                        "The secret is shown once, at creation. Scope it to the operations the "
                        "integration actually performs."
                    ),
                    route="/credentials",
                    complete=has_credential,
                    required_role=None,
                ),
                OnboardingStep(
                    key="synchronise_catalogue",
                    title="Synchronise your product catalogue",
                    detail="Nothing can be recommended before it exists here.",
                    route="/products/sync",
                    complete=has_products,
                    required_role=_DEVELOPER,
                ),
                OnboardingStep(
                    key="submit_events",
                    title="Submit interaction events",
                    detail=(
                        "The model learns from what your customers did. This is the step that "
                        "takes real time — the others take minutes."
                    ),
                    route="/events/submit",
                    complete=has_events,
                    required_role=_DEVELOPER,
                ),
                OnboardingStep(
                    key="request_training",
                    title="Request training",
                    detail="One run at a time, and only when there is enough data to learn from.",
                    route="/training",
                    complete=has_training,
                    required_role=_ADMIN,
                ),
                OnboardingStep(
                    key="review_quality",
                    title="Review the quality of what was produced",
                    detail=(
                        "A run that finished is not a run worth serving. Compare it against the "
                        "baseline before you activate anything."
                    ),
                    route="/models",
                    complete=has_succeeded,
                    required_role=_ADMIN,
                ),
                OnboardingStep(
                    key="activate_version",
                    title="Activate a model version",
                    detail=(
                        "Until a version is active, recommendation requests have nothing "
                        "to serve."
                    ),
                    route="/models",
                    complete=has_active_version,
                    required_role=_ADMIN,
                ),
                OnboardingStep(
                    key="monitor",
                    title="Watch usage and service status",
                    detail="Availability, capacity and consumption against your plan's limits.",
                    route="/service-status",
                    complete=has_serving or has_usage,
                    required_role=_ADMIN,
                ),
            )
        )
