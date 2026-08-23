"""The four admission checks, computed once and used twice.

`GET /v1/training-jobs/eligibility` renders them as five stat cards and one
sentence (dc.html L1666). `POST /v1/training-jobs` refuses on them. Those are
the same four questions, and asking them in two places with two implementations
is how a console comes to enable a button the server then rejects — the exact
failure BUILD_PROMPT §gate-5 exists to prevent. So the checks live here, the
endpoint renders this, and the creating transaction raises from this.

**Which is not to say the endpoint is the enforcement.** It cannot be: between
reading it and pressing the button a tenant can be beaten to the queue. Two of
the four are re-checked inside the creating transaction, and the most important
one — one active job — is not checked in Python at all on the write path. It is
a partial unique index (migration 0010), because a `SELECT` followed by an
`INSERT` has a window and an index does not. This module's version of that check
exists to *explain* the refusal, not to produce it.

The order matters and is the order the errors are listed in (BACKEND_PLAN
L1111): an already-running job, then the cooldown, then the quota, then the
data. Cheapest and most likely first, and — more to the point — a tenant whose
job is already running does not also need to be told their quota is fine.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.enums import UsageType
from graphrec.common.errors import (
    ConflictError,
    GraphRecError,
    LimitError,
    ValidationError,
)
from graphrec.domain import quotas
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering.periods import current_period
from graphrec.domain.training import snapshot
from graphrec.training import states

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.domain.metering.counters import UsageCounters

#: L1665: "platform-wide". The limit is one job across the whole installation
#: (ASM-03), but it is *enforced* per tenant by the partial unique index, which
#: is a weaker rule. The gap is deliberate and recorded in the phase report:
#: four tenants (ASM-02) can each hold one job, and the reconciler's leader lock
#: is where a genuinely global serialisation would go if the assumption changed.
CONCURRENCY_SCOPE = "platform"


@dataclass(frozen=True, slots=True)
class Concurrency:
    limit: int
    scope: str = CONCURRENCY_SCOPE


@dataclass(frozen=True, slots=True)
class InteractionData:
    """L1667: "4.18 M · sufficient — 1,000 sequences required"."""

    sequences: int
    required: int

    @property
    def sufficient(self) -> bool:
        return self.sequences >= self.required


@dataclass(frozen=True, slots=True)
class Quota:
    """L1668: "6 / 8 · resets 2026-09-01".

    `used` and `limit` are integers rather than decimals because a training run
    is a countable thing; `remaining` is `None` only when nothing bounds it,
    which the console renders as unlimited rather than as zero.
    """

    used: int
    limit: int | None
    resets_at: dt.date

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(self.limit - self.used, 0)

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


@dataclass(frozen=True, slots=True)
class Cooldown:
    """L1669: "none · 15 min between requests".

    Provisional. The window appears on a stat card in the prototype and nowhere
    in the SRS (BACKEND_PLAN §7.3), so it is a setting that can be turned off by
    setting it to zero rather than a rule wired into the schema.
    """

    seconds_remaining: int
    window_seconds: int

    @property
    def active(self) -> bool:
        return self.window_seconds > 0 and self.seconds_remaining > 0


@dataclass(frozen=True, slots=True)
class Eligibility:
    """All four answers, and the one sentence that summarises them."""

    concurrency: Concurrency
    interaction_data: InteractionData
    quota: Quota
    cooldown: Cooldown
    #: The job in the way, when there is one. Carried so the sentence can name
    #: it — "Job job-2292 is already running" — without a second query.
    active_job_id: uuid.UUID | None
    #: The refusal this would raise, or `None`. Built eagerly so `reason` and
    #: `raise_if_blocked` cannot disagree about which check fired first.
    blocker: Exception | None

    @property
    def eligible(self) -> bool:
        return self.blocker is None

    @property
    def reason(self) -> str:
        """The prototype returns `''` when eligible (L1648), not `null`. Kept,
        because the console concatenates it into a tooltip.

        `GraphRecError.reason` is a method, not an attribute — it resolves the
        copy catalogue on each call — so this calls it. Reading it as an
        attribute is not a type error and not a runtime error: it yields the
        repr of a bound method, and the console renders that at the tenant.
        """
        if isinstance(self.blocker, GraphRecError):
            return self.blocker.reason()
        return ""

    def raise_if_blocked(self) -> None:
        if self.blocker is not None:
            raise self.blocker


async def evaluate(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    now: dt.datetime,
    concurrency_limit: int,
    cooldown_seconds: int,
    min_sequences: int,
    window_days: int,
) -> Eligibility:
    """Ask all four, in order, and keep the first refusal.

    All four are computed even when the first one blocks. The endpoint renders
    five cards regardless of eligibility — a tenant whose job is running still
    sees how much quota they have — so short-circuiting would save one aggregate
    query and cost the page its content.
    """
    active_job_id = await active_job(session)
    sequences = await snapshot.count_eligible_sequences(
        session, cutoff_at=now, window_days=window_days
    )
    quota = await _quota(session, counters, tenant_id=tenant_id, now=now)
    cooldown = await _cooldown(session, now=now, window_seconds=cooldown_seconds)

    interaction_data = InteractionData(sequences=sequences, required=min_sequences)
    blocker = _first_blocker(
        active_job_id=active_job_id,
        concurrency_limit=concurrency_limit,
        cooldown=cooldown,
        quota=quota,
        interaction_data=interaction_data,
    )
    return Eligibility(
        concurrency=Concurrency(limit=concurrency_limit),
        interaction_data=interaction_data,
        quota=quota,
        cooldown=cooldown,
        active_job_id=active_job_id,
        blocker=blocker,
    )


def _first_blocker(
    *,
    active_job_id: uuid.UUID | None,
    concurrency_limit: int,
    cooldown: Cooldown,
    quota: Quota,
    interaction_data: InteractionData,
) -> Exception | None:
    if active_job_id is not None:
        return ConflictError(
            "training_already_running",
            copy_args={"job_id": str(active_job_id), "concurrency": concurrency_limit},
        )
    if cooldown.active:
        return ConflictError("training_cooldown", copy_args={"seconds": cooldown.seconds_remaining})
    if quota.exhausted:
        return LimitError(
            "training_quota_exhausted", copy_args={"resets_on": quota.resets_at.isoformat()}
        )
    if not interaction_data.sufficient:
        return ValidationError(
            "training_insufficient_data", copy_args={"minimum": interaction_data.required}
        )
    return None


async def active_job(session: AsyncSession) -> uuid.UUID | None:
    """The tenant's non-terminal run, if any.

    Reads the same nine states the partial unique index covers, spelled from
    `graphrec.training.states` so the two cannot drift. Ordered and limited
    because the index guarantees at most one and a query that assumed so without
    saying so would raise `MultipleResultsFound` on the day the guarantee broke.
    """
    found: uuid.UUID | None = await session.scalar(
        sa.text(
            "SELECT training_job_id FROM training_jobs "
            "WHERE state = ANY(:states) ORDER BY requested_at DESC LIMIT 1"
        ).bindparams(
            sa.bindparam(
                "states",
                value=sorted(state.value for state in states.ACTIVE_STATES),
                type_=sa.ARRAY(sa.Text),
            )
        )
    )
    return found


async def _quota(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    now: dt.datetime,
) -> Quota:
    period = current_period(now)
    limit = await quotas.resolve(
        session, tenant_id=tenant_id, usage_type=UsageType.TRAINING, now=now
    )
    used = await counter_ops.current(
        session, counters, tenant_id=tenant_id, usage_type=UsageType.TRAINING, period=period
    )
    return Quota(used=int(used), limit=limit.value, resets_at=period.end)


async def _cooldown(session: AsyncSession, *, now: dt.datetime, window_seconds: int) -> Cooldown:
    """Measured from the last *request*, not the last completion.

    A run that failed after four seconds still spent a request, and a tenant who
    can retry a broken configuration instantly is a tenant who can occupy the
    global slot in a loop. The prototype's card says "between requests" (L1669)
    and this is that, literally.
    """
    if window_seconds <= 0:
        return Cooldown(seconds_remaining=0, window_seconds=0)

    last = await session.scalar(sa.text("SELECT max(requested_at) FROM training_jobs"))
    if last is None:
        return Cooldown(seconds_remaining=0, window_seconds=window_seconds)

    elapsed = (now - last).total_seconds()
    remaining = max(0, int(window_seconds - elapsed))
    return Cooldown(seconds_remaining=remaining, window_seconds=window_seconds)


def as_dict(eligibility: Eligibility) -> dict[str, Any]:
    """The wire shape, spelled once (BACKEND_PLAN L1098-1104).

    A plain dictionary rather than a response model because the router owns the
    schema and the domain owns the numbers; putting a Pydantic model here would
    make `graphrec.domain` depend on the API's vocabulary.
    """
    return {
        "eligible": eligibility.eligible,
        "reason": eligibility.reason,
        "concurrency": dataclasses.asdict(eligibility.concurrency),
        "interaction_data": {
            "sequences": eligibility.interaction_data.sequences,
            "required": eligibility.interaction_data.required,
            "sufficient": eligibility.interaction_data.sufficient,
        },
        "quota": {
            "used": eligibility.quota.used,
            "limit": eligibility.quota.limit,
            "remaining": eligibility.quota.remaining,
            "resets_at": eligibility.quota.resets_at,
        },
        "cooldown": {
            "active": eligibility.cooldown.active,
            "seconds_remaining": eligibility.cooldown.seconds_remaining,
            "window_seconds": eligibility.cooldown.window_seconds,
        },
    }


__all__ = [
    "CONCURRENCY_SCOPE",
    "Concurrency",
    "Cooldown",
    "Eligibility",
    "InteractionData",
    "Quota",
    "active_job",
    "as_dict",
    "evaluate",
]
