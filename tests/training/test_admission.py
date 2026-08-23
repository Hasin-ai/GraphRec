"""The four checks that decide whether a run may start, and the two ways a
second request is not a second run.

The exit criterion this file exists for: *two concurrent training requests yield
one job and one 409*. It is enforced by `uq_training_jobs_one_active`, a partial
unique index, and that is the point — application code that read the state and
then wrote a row would have a window between the read and the write, and two
requests arriving inside it would both pass.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
import sqlalchemy as sa

from graphrec.common.enums import JobState
from graphrec.common.errors import ConflictError, LimitError, ValidationError
from graphrec.domain.training.service import TrainingRequest, TrainingService
from tests.training.conftest import NOW

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _request(service, session, counters, tenant_id, ref, **kwargs):
    return await service.request(
        session,
        counters,
        tenant_id=tenant_id,
        requested_by=None,
        request=TrainingRequest(request_ref=ref, **kwargs),
    )


# ------------------------------------------------------------- the happy path


async def test_a_first_request_is_admitted_and_starts_at_stage_zero(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """`202 {state: "queued", stage_index: 0, progress: "waiting to start"}`.

    The row is written with the rail already at its first position rather than
    with a null the worker fills in, because a console polling between the
    insert and the first claim must have something honest to draw.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        outcome = await _request(service, session, counters, tenant, "run-1")

    assert outcome.created
    assert outcome.job.state == JobState.QUEUED.value
    assert outcome.job.stage_index == 0
    assert outcome.job.progress_text == "waiting to start"
    assert outcome.job.job_id is not None


async def test_the_first_request_creates_the_tenant_s_default_model(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """A model is a lazily created container, not something a tenant configures.

    The console never asks for one (L1677 collects four fields and none of them
    is a model), so requiring one would be requiring a step the product does not
    have.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        await _request(service, session, counters, tenant, "run-1")
        await _request(service, session, counters, tenant, "run-1")
        names = list(
            (await session.scalars(sa.text("SELECT name FROM models ORDER BY name"))).all()
        )

    assert names == ["default"]


# ------------------------------------------------------------- concurrency


async def test_two_concurrent_requests_yield_one_job_and_one_conflict(
    service, ingest_sessionmaker, tenant, counters, seed_interactions, bound
) -> None:
    """The exit criterion, run as a genuine race on two connections.

    Two sessions, two transactions, both past the eligibility read before either
    commits. Nothing in the service can prevent this; the index does, and the
    loser is translated into the console's conflict rather than into an
    `IntegrityError` a client cannot read.
    """
    await seed_interactions(tenant)

    from graphrec.db.tenant_context import bind_tenant

    async def attempt(ref: str) -> object:
        async with ingest_sessionmaker() as session, session.begin():
            await bind_tenant(session, tenant)
            try:
                outcome = await _request(service, session, counters, tenant, ref)
            except ConflictError as exc:
                return exc
            return outcome

    first, second = await asyncio.gather(attempt("race-a"), attempt("race-b"))

    outcomes = [r for r in (first, second) if not isinstance(r, Exception)]
    conflicts = [r for r in (first, second) if isinstance(r, ConflictError)]

    assert len(outcomes) == 1, "exactly one request may create a job"
    assert len(conflicts) == 1, "the other must be refused, not raise an integrity error"
    assert conflicts[0].code == "training_already_running"

    async with bound(tenant) as session:
        count = await session.scalar(sa.text("SELECT count(*) FROM training_jobs"))
    assert count == 1


async def test_a_second_request_while_one_runs_is_a_conflict_that_names_the_job(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """L1645's refusal, with the running job's identifier in it.

    Naming the job is what makes the message actionable: the console links
    straight to the run that is in the way rather than telling a tenant to go
    and find it.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        first = await _request(service, session, counters, tenant, "run-1")

    async with bound(tenant) as session:
        with pytest.raises(ConflictError) as raised:
            await _request(service, session, counters, tenant, "run-2")

    assert raised.value.code == "training_already_running"
    assert str(first.job.training_job_id) in str(raised.value.copy_args["job_id"])


async def test_a_finished_run_does_not_block_the_next_one(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """The index covers the nine non-terminal states and no others.

    Which is the only version of the rule that works: a tenant who has trained
    once must be able to train again, and a rule keyed on "has ever trained"
    would let them train exactly once.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        first = await _request(service, session, counters, tenant, "run-1")

    async with bound(tenant) as session:
        await session.execute(
            sa.text(
                "UPDATE training_jobs SET state = 'succeeded', completed_at = now() "
                "WHERE training_job_id = :id"
            ),
            {"id": first.job.training_job_id},
        )

    async with bound(tenant) as session:
        second = await _request(service, session, counters, tenant, "run-2")

    assert second.created
    assert second.job.training_job_id != first.job.training_job_id


async def test_one_tenant_s_active_run_does_not_block_another_tenant(
    service, bound, training_tenants, counters, seed_interactions
) -> None:
    """The index is on `(tenant_id)`, so the rule is per tenant.

    Deliberately weaker than ASM-03's platform-wide serialisation — see
    PHASE_9_REPORT §3 — and this test pins the behaviour that actually ships so
    that closing the gap later is a visible change rather than a silent one.
    """
    alpha, beta = training_tenants["alpha"], training_tenants["beta"]
    await seed_interactions(alpha)
    await seed_interactions(beta)

    async with bound(alpha) as session:
        await _request(service, session, counters, alpha, "run-a")
    async with bound(beta) as session:
        outcome = await _request(service, session, counters, beta, "run-b")

    assert outcome.created


# ------------------------------------------------------------- idempotency


async def test_replaying_a_request_ref_returns_the_original_job(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """§17.3: a repeat is a success, not a conflict.

    The identifier exists so a client that timed out on the first call can ask
    again. Answering `409` would make the safe retry indistinguishable from the
    dangerous one, and clients would stop retrying.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        first = await _request(service, session, counters, tenant, "same-ref")

    async with bound(tenant) as session:
        again = await _request(service, session, counters, tenant, "same-ref")

    assert not again.created
    assert again.job.training_job_id == first.job.training_job_id


async def test_a_replay_does_not_meter_a_second_grant(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """One run, one unit of quota, however many times it was asked for."""
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        await _request(service, session, counters, tenant, "same-ref")
    async with bound(tenant) as session:
        await _request(service, session, counters, tenant, "same-ref")
        granted = await session.scalar(
            sa.text(
                "SELECT count(*) FROM usage_events "
                "WHERE tenant_id = :tid AND usage_type = 'training'"
            ),
            {"tid": tenant},
        )

    assert granted == 1


async def test_a_replay_of_a_terminal_run_still_returns_it(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """The replay lookup is on the identifier, not on the state.

    A client retrying after a long timeout may be retrying a run that has since
    finished; handing it a fresh job would start a second training run for a
    request that was already honoured.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        first = await _request(service, session, counters, tenant, "ref")
        await session.execute(
            sa.text(
                "UPDATE training_jobs SET state = 'failed', completed_at = now(), "
                "  failure_reason = 'x' WHERE training_job_id = :id"
            ),
            {"id": first.job.training_job_id},
        )

    async with bound(tenant) as session:
        again = await _request(service, session, counters, tenant, "ref")

    assert again.job.training_job_id == first.job.training_job_id
    assert not again.created


# ------------------------------------------------------------------ refusals


async def test_too_little_interaction_data_is_refused_before_a_job_exists(
    bound, tenant, counters, seed_interactions
) -> None:
    """L697. A `422`, and nothing written.

    Admitting the run and failing it four stages later would spend a slot, a
    quota unit and a tenant's attention on a refusal that was knowable at the
    door.
    """
    await seed_interactions(tenant, users=2)
    strict = TrainingService(cooldown_seconds=0, min_sequences=1_000)

    async with bound(tenant) as session:
        with pytest.raises(ValidationError) as raised:
            await _request(strict, session, counters, tenant, "run-1")

    assert raised.value.code == "training_insufficient_data"

    async with bound(tenant) as session:
        count = await session.scalar(sa.text("SELECT count(*) FROM training_jobs"))
    assert count == 0


async def test_the_cooldown_refuses_a_request_made_too_soon_after_the_last(
    bound, tenant, counters, seed_interactions
) -> None:
    """The cooldown is measured from the previous request, not from its end.

    A run that failed in ten seconds is still a run that was requested, and the
    window exists to stop a retry loop from queueing eight of them.
    """
    await seed_interactions(tenant)
    cooling = TrainingService(cooldown_seconds=900, min_sequences=1)

    async with bound(tenant) as session:
        first = await cooling.request(
            session,
            counters,
            tenant_id=tenant,
            requested_by=None,
            request=TrainingRequest(request_ref="run-1"),
            now=NOW,
        )
        await session.execute(
            sa.text(
                "UPDATE training_jobs SET state = 'succeeded', completed_at = :at "
                "WHERE training_job_id = :id"
            ),
            {"id": first.job.training_job_id, "at": NOW},
        )

    async with bound(tenant) as session:
        with pytest.raises(ConflictError) as raised:
            await cooling.request(
                session,
                counters,
                tenant_id=tenant,
                requested_by=None,
                request=TrainingRequest(request_ref="run-2"),
                now=NOW + dt.timedelta(minutes=5),
            )

    assert raised.value.code == "training_cooldown"
    assert 0 < int(raised.value.copy_args["seconds"]) <= 600


async def test_the_cooldown_lapses(bound, tenant, counters, seed_interactions) -> None:
    await seed_interactions(tenant)
    cooling = TrainingService(cooldown_seconds=900, min_sequences=1)

    async with bound(tenant) as session:
        first = await cooling.request(
            session,
            counters,
            tenant_id=tenant,
            requested_by=None,
            request=TrainingRequest(request_ref="run-1"),
            now=NOW,
        )
        await session.execute(
            sa.text(
                "UPDATE training_jobs SET state = 'succeeded', completed_at = :at "
                "WHERE training_job_id = :id"
            ),
            {"id": first.job.training_job_id, "at": NOW},
        )

    async with bound(tenant) as session:
        outcome = await cooling.request(
            session,
            counters,
            tenant_id=tenant,
            requested_by=None,
            request=TrainingRequest(request_ref="run-2"),
            now=NOW + dt.timedelta(minutes=20),
        )

    assert outcome.created


async def test_an_exhausted_training_quota_is_a_429_not_a_409(
    bound, tenant, counters, seed_interactions, plan_limit
) -> None:
    """A limit reached is a limit, not a conflict.

    The distinction matters to a client: a `409` invites an immediate retry
    against a different state, and a `429` says the answer will not change until
    the period rolls over. `resets_on` is in the copy for exactly that reason.
    """
    await seed_interactions(tenant)
    plan_limit(tenant, training_limit=0)
    service = TrainingService(cooldown_seconds=0, min_sequences=1)

    async with bound(tenant) as session:
        with pytest.raises(LimitError) as raised:
            await _request(service, session, counters, tenant, "run-1")

    assert raised.value.code == "training_quota_exhausted"

    async with bound(tenant) as session:
        count = await session.scalar(sa.text("SELECT count(*) FROM training_jobs"))
    assert count == 0


async def test_an_unknown_model_type_is_refused(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """CON-01 names one family and the dialog offers one option.

    A request naming anything else is a client that invented a value, so the
    refusal says so rather than pretending the type might arrive later.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        with pytest.raises(ValidationError) as raised:
            await _request(service, session, counters, tenant, "run-1", model_type="SASRec")

    assert raised.value.code == "training_model_type_unknown"


# ---------------------------------------------------------------- the report


async def test_eligibility_reports_all_four_checks_even_when_one_blocks(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """The console draws four stat cards, not one (L1666-1669).

    Short-circuiting after the first blocker would leave three of them empty on
    exactly the page a tenant opens to find out why they cannot train.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        await _request(service, session, counters, tenant, "run-1")
        decision = await service.eligibility(session, counters, tenant_id=tenant)

    assert not decision.eligible
    assert decision.reason
    assert decision.concurrency.limit == 1
    assert decision.interaction_data.sequences > 0
    assert decision.quota.used >= 1
    assert decision.cooldown.window_seconds == 0


async def test_an_eligible_tenant_gets_an_empty_reason_not_a_message(
    service, bound, tenant, counters, seed_interactions
) -> None:
    """L1648: `reason: ''`.

    An optional field would invite `reason ?? 'ok'` in a client, and the string
    it substituted would not be ours.
    """
    await seed_interactions(tenant)

    async with bound(tenant) as session:
        decision = await service.eligibility(session, counters, tenant_id=tenant)

    assert decision.eligible
    assert decision.reason == ""


async def test_eligibility_is_readable_by_a_tenant_with_no_data_at_all(
    bound, tenant, counters
) -> None:
    """The page must render for a tenant on their first day.

    They are the tenant most likely to open it, and an endpoint that raised on
    an empty catalogue would leave them at an error screen instead of at the
    number that explains what to do next.
    """
    strict = TrainingService(cooldown_seconds=0, min_sequences=1_000)

    async with bound(tenant) as session:
        decision = await strict.eligibility(session, counters, tenant_id=tenant)

    assert not decision.eligible
    assert decision.interaction_data.sequences == 0
    assert decision.interaction_data.required == 1_000


async def test_a_blocked_decision_names_only_the_first_blocker(
    bound, tenant, counters, seed_interactions
) -> None:
    """Fixed order, so a tenant blocked by two things is told about the same one
    on every call.

    An active run is reported ahead of the cooldown, because clearing the
    cooldown does nothing while a run is in progress.
    """
    await seed_interactions(tenant)
    cooling = TrainingService(cooldown_seconds=900, min_sequences=1)

    async with bound(tenant) as session:
        await cooling.request(
            session,
            counters,
            tenant_id=tenant,
            requested_by=None,
            request=TrainingRequest(request_ref="run-1"),
            now=NOW,
        )
        decision = await cooling.eligibility(session, counters, tenant_id=tenant, now=NOW)

    with pytest.raises(ConflictError) as raised:
        decision.raise_if_blocked()
    assert raised.value.code == "training_already_running"


async def test_a_request_for_a_foreign_tenant_s_job_is_invisible(
    service, bound, training_tenants, counters, seed_interactions
) -> None:
    """Gate 4 by policy. A `404`, never a `403`.

    The session is bound, so the row is not a candidate; there is no comparison
    in the service that could be written the wrong way round.
    """
    from graphrec.common.errors import NotFoundError

    alpha, beta = training_tenants["alpha"], training_tenants["beta"]
    await seed_interactions(alpha)

    async with bound(alpha) as session:
        outcome = await _request(service, session, counters, alpha, "run-a")

    async with bound(beta) as session:
        with pytest.raises(NotFoundError):
            await service.get(session, training_job_id=outcome.job.training_job_id)


async def test_a_request_ref_is_unique_per_tenant_not_globally(
    service, bound, training_tenants, counters, seed_interactions
) -> None:
    """Two tenants may both call their run `nightly`.

    A global uniqueness rule would let one tenant's choice of identifier deny
    another tenant's, which is a cross-tenant coupling with no justification.
    """
    alpha, beta = training_tenants["alpha"], training_tenants["beta"]
    await seed_interactions(alpha)
    await seed_interactions(beta)

    async with bound(alpha) as session:
        first = await _request(service, session, counters, alpha, "nightly")
    async with bound(beta) as session:
        second = await _request(service, session, counters, beta, "nightly")

    assert first.job.training_job_id != second.job.training_job_id
    assert second.created


def test_the_stage_rail_is_the_prototype_s_nine_names() -> None:
    """dc.html L632, in order. The console draws this array literally."""
    from graphrec.training import states

    assert states.STAGE_NAMES == (
        "queued",
        "waiting_for_resources",
        "preparing_data",
        "building_graph",
        "training",
        "evaluating",
        "indexing_embeddings",
        "registering",
        "succeeded",
    )
    assert len(states.STAGE_NAMES) == 9
    assert states.STAGE_RAIL[0] is JobState.QUEUED
