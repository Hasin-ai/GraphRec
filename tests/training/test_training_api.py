"""The seven training routes over HTTP.

What these check that `test_pipeline.py` and `test_admission.py` cannot: that
the routes exist at the paths BACKEND_PLAN §1090-1131 publishes, that each of
the four admission refusals arrives with the status code the console branches
on, and that the stage rail and gate-5 fields are on the wire rather than only
in the domain objects that produce them.

**Every app here is built with its own `Settings`.** The knobs that matter to
training — the sequence floor and the cooldown — are settings, and a suite that
could only observe their defaults would be a suite that could not test the two
refusals they cause. The tokens are the authorization suite's, which is safe
because the signing key is a file on disk rather than a per-instance secret.

The one thing deliberately not exercised here is a credential: training is a
session-only surface (L1663) and `CurrentTenant` refuses an API key before any
of this code runs, which the realm-separation suite already proves.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from graphrec.common.enums import JobState
from graphrec.common.error_copy import resolve_copy
from graphrec.training import states
from tests.authz.conftest import auth

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = [pytest.mark.db]

WINDOW = 90


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def home(realm) -> uuid.UUID:
    """The realm's home tenant, which is the one the tokens speak for."""
    tenant_id = realm["home"]["tenant_id"]
    assert isinstance(tenant_id, uuid.UUID)
    return tenant_id


@pytest.fixture
def build_api(_empty_ingestion, _empty_training) -> Iterator[Callable[..., TestClient]]:
    """A client per test, over an app whose training settings the test chose.

    Function-scoped and closed on the way out: an app left running would keep a
    connection pool bound to a database the next test is about to empty.

    Both wipes are dependencies rather than something each test remembers. The
    ingestion one matters as much as training's here: these tests seed the same
    catalogue into the same tenant every time, and the second one would collide
    on `uq_products_tenant_external` rather than on anything under test.
    """
    from apps.control_api.main import create_app
    from graphrec.common.config import Settings

    clients: list[TestClient] = []

    def _build(**overrides: object) -> TestClient:
        settings = Settings(environment="ci", **overrides)  # type: ignore[arg-type]
        client = TestClient(create_app(settings), raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _build

    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def trainable(build_api, home, seed_interactions):
    """An app that will admit a run, over a tenant that has the data for one.

    The floor is one sequence rather than a thousand because the suite seeds
    twenty-four users, and the cooldown is off because most of these tests make
    two requests in a row and the cooldown is not what they are about.
    """

    async def _make() -> TestClient:
        await seed_interactions(home)
        return build_api(training_min_sequences=1, training_cooldown_seconds=0)

    return _make


def _request(api: TestClient, token: str, ref: str, **overrides: object) -> object:
    body = {"request_ref": ref, "model_type": "DGSR", "interaction_window_days": WINDOW}
    body.update(overrides)
    return api.post("/v1/training-jobs", json=body, headers=auth(token))


async def _settle(bound, tenant_id: uuid.UUID, training_job_id: str, state: JobState) -> None:
    """Put a run into a terminal state without running it.

    Several of these tests need a *finished* run — to observe the cooldown, or
    to observe that a terminal run cannot be cancelled — and running nine real
    stages to get one would make an API test into a training test.
    """
    async with bound(tenant_id) as session:
        await session.execute(
            sa.text(
                "UPDATE training_jobs SET state = :state, completed_at = now() "
                " WHERE training_job_id = :id"
            ),
            {"state": state.value, "id": training_job_id},
        )
        await session.execute(
            sa.text(
                "UPDATE jobs SET status = 'succeeded', completed_at = now(), "
                "  lease_owner = NULL, lease_expires_at = NULL "
                " FROM training_jobs AS t "
                " WHERE t.job_id = jobs.job_id AND t.training_job_id = :id"
            ),
            {"id": training_job_id},
        )


# --------------------------------------------------------------- eligibility


async def test_eligibility_answers_all_four_checks_before_anything_is_requested(
    trainable, home_dev
) -> None:
    """L1666-1669. Five cards, and a sentence that is empty when nothing blocks."""
    api = await trainable()

    response = api.get("/v1/training-jobs/eligibility", headers=auth(home_dev))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eligible"] is True
    assert body["reason"] == "", "L1648: eligible means an empty sentence, not a null one"
    assert body["concurrency"]["limit"] >= 1
    assert body["interaction_data"]["sufficient"] is True
    assert body["quota"]["resets_at"]
    assert body["cooldown"]["active"] is False


async def test_eligibility_names_the_run_in_the_way(trainable, home_dev) -> None:
    """A tenant blocked by their own job is told which job, not just that one exists."""
    api = await trainable()
    first = _request(api, home_dev, "ref-blocking")
    assert first.status_code == 202, first.text

    response = api.get("/v1/training-jobs/eligibility", headers=auth(home_dev))

    body = response.json()
    assert body["eligible"] is False
    assert first.json()["training_job_id"] in body["reason"]


# -------------------------------------------------------------- requesting


async def test_requesting_a_run_returns_202_and_the_whole_stage_rail(trainable, home_dev) -> None:
    """The rail is server-rendered (BACKEND_PLAN L1114), so it is on the wire in full."""
    api = await trainable()

    response = _request(api, home_dev, "ref-first")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == JobState.QUEUED.value
    assert body["stages"] == list(states.STAGE_NAMES)
    assert body["stage_index"] == 0
    assert body["progress"] == "waiting to start"
    assert body["can_cancel"] is True
    assert body["blocked_reason"] is None
    assert body["snapshot"] is None, "nothing has been frozen yet"


async def test_the_same_request_ref_replays_as_200_with_the_original_run(
    trainable, home_dev
) -> None:
    """§17.3. A retry of a call that may have succeeded is a success, not a `409`."""
    api = await trainable()

    first = _request(api, home_dev, "ref-replayed")
    second = _request(api, home_dev, "ref-replayed")

    assert first.status_code == 202
    assert second.status_code == 200, "the status line carries the difference"
    assert second.json()["training_job_id"] == first.json()["training_job_id"]


async def test_a_second_run_while_one_is_active_is_a_409(trainable, home_dev) -> None:
    """The first exit criterion, at the HTTP surface."""
    api = await trainable()
    _request(api, home_dev, "ref-one")

    response = _request(api, home_dev, "ref-two")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "training_already_running"


async def test_not_enough_history_is_a_422(build_api, home, home_dev, seed_interactions) -> None:
    """The floor is a `422` and not a `409`: the request is well-formed, the
    tenant's data is not yet what it needs to be."""
    await seed_interactions(home)
    api = build_api(training_min_sequences=1_000_000, training_cooldown_seconds=0)

    response = _request(api, home_dev, "ref-thin")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "training_insufficient_data"


async def test_the_cooldown_is_a_409_once_the_previous_run_has_finished(
    build_api, bound, home, home_dev, seed_interactions
) -> None:
    """Measured from the last request, so a finished run still holds the window shut."""
    await seed_interactions(home)
    api = build_api(training_min_sequences=1, training_cooldown_seconds=900)

    first = _request(api, home_dev, "ref-cooling")
    assert first.status_code == 202, first.text
    await _settle(bound, home, first.json()["training_job_id"], JobState.SUCCEEDED)

    response = _request(api, home_dev, "ref-too-soon")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "training_cooldown"


async def test_an_exhausted_quota_is_a_429(trainable, home, home_dev, plan_limit) -> None:
    """NR-F-09. The quota is a rate refusal, which is a `429` and not a `403`."""
    api = await trainable()
    plan_limit(home, training_limit=0)

    response = _request(api, home_dev, "ref-over-quota")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "training_quota_exhausted"


async def test_a_window_the_console_does_not_offer_is_refused_by_the_schema(
    trainable, home_dev
) -> None:
    """L1673 offers 30, 90 and 180 days. A fourth value is a client bug."""
    response = _request(await trainable(), home_dev, "ref-odd-window", interaction_window_days=45)

    assert response.status_code == 422


# ------------------------------------------------------------- cancellation


async def test_cancelling_requires_a_reason(trainable, home_dev) -> None:
    """L1714's dialog has a required field, and the server is where required lives."""
    api = await trainable()
    job = _request(api, home_dev, "ref-cancel-me").json()["training_job_id"]

    response = api.post(
        f"/v1/training-jobs/{job}:cancel", json={"reason": "  "}, headers=auth(home_dev)
    )

    assert response.status_code == 422


async def test_cancelling_a_run_nobody_has_claimed_settles_it_immediately(
    trainable, home_dev
) -> None:
    """There is no worker to observe the boundary, so `cancelling` would be a lie.

    A run still on the queue is stopped by the queue itself, which is why this
    lands on `cancelled` rather than on the intermediate state a running job
    would show. The stage index is 0 because it never left `queued`.
    """
    api = await trainable()
    job = _request(api, home_dev, "ref-stop").json()["training_job_id"]

    response = api.post(
        f"/v1/training-jobs/{job}:cancel",
        json={"reason": "operator changed their mind"},
        headers=auth(home_dev),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == JobState.CANCELLED.value
    assert body["stage_index"] == 0
    assert body["cancel_reason"] == "Cancelled by requester: operator changed their mind"
    assert body["can_cancel"] is False
    assert body["blocked_reason"] == resolve_copy("job_not_cancellable")


async def test_a_running_job_reports_cancelling_and_disables_the_control(
    trainable, bound, home, home_dev
) -> None:
    """L1714: "The job moves to cancelling and then to cancelled."

    The queue row is put into `running` by hand rather than by a worker: what
    is under test is the response a console would poll during the gap, and the
    gap only exists while somebody holds the lease.
    """
    api = await trainable()
    job = _request(api, home_dev, "ref-mid-flight").json()["training_job_id"]
    async with bound(home) as session:
        await session.execute(
            sa.text(
                "UPDATE jobs SET status = 'running', lease_owner = 'test', "
                "  lease_expires_at = now() + interval '2 minutes' "
                " FROM training_jobs AS t "
                " WHERE t.job_id = jobs.job_id AND t.training_job_id = :id"
            ),
            {"id": job},
        )

    response = api.post(
        f"/v1/training-jobs/{job}:cancel",
        json={"reason": "wrong window"},
        headers=auth(home_dev),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == JobState.CANCELLING.value
    assert body["can_cancel"] is False
    assert body["blocked_reason"] == resolve_copy("job_already_cancelling")


async def test_a_finished_run_cannot_be_cancelled(trainable, bound, home, home_dev) -> None:
    api = await trainable()
    job = _request(api, home_dev, "ref-already-done").json()["training_job_id"]
    await _settle(bound, home, job, JobState.SUCCEEDED)

    response = api.post(
        f"/v1/training-jobs/{job}:cancel", json={"reason": "too late"}, headers=auth(home_dev)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_cancellable"


# -------------------------------------------------------------------- reads


async def test_a_run_is_readable_by_id_with_its_rail(trainable, home_dev) -> None:
    api = await trainable()
    job = _request(api, home_dev, "ref-readable").json()["training_job_id"]

    response = api.get(f"/v1/training-jobs/{job}", headers=auth(home_dev))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["training_job_id"] == job
    assert body["stages"] == list(states.STAGE_NAMES)
    assert body["note"]


async def test_the_list_is_newest_first_and_filterable_by_state(
    trainable, bound, home, home_dev
) -> None:
    api = await trainable()
    first = _request(api, home_dev, "ref-older").json()["training_job_id"]
    await _settle(bound, home, first, JobState.SUCCEEDED)
    second = _request(api, home_dev, "ref-newer").json()["training_job_id"]

    listed = api.get("/v1/training-jobs", headers=auth(home_dev)).json()["jobs"]
    filtered = api.get(
        "/v1/training-jobs", params={"state": JobState.SUCCEEDED.value}, headers=auth(home_dev)
    ).json()["jobs"]

    assert [row["training_job_id"] for row in listed] == [second, first]
    assert [row["training_job_id"] for row in filtered] == [first]


async def test_another_tenants_run_is_a_404_and_not_a_403(trainable, home_dev, other_admin) -> None:
    """Gate 4. A `403` would confirm the identifier names something real."""
    api = await trainable()
    job = _request(api, home_dev, "ref-private").json()["training_job_id"]

    response = api.get(f"/v1/training-jobs/{job}", headers=auth(other_admin))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_the_curve_starts_at_the_baseline_and_is_readable_by_job(
    trainable, bound, home, home_dev
) -> None:
    """Epoch 0 is the popularity baseline, which is what makes the rest readable."""
    api = await trainable()
    job = _request(api, home_dev, "ref-curve").json()["training_job_id"]
    async with bound(home) as session:
        for epoch, value in ((0, "0.100000"), (1, "0.220000")):
            await session.execute(
                sa.text(
                    "INSERT INTO training_metrics "
                    "  (metric_id, tenant_id, training_job_id, epoch, metric_name, value) "
                    "VALUES (gen_random_uuid(), :tid, :job, :epoch, 'recall_at_10', :value)"
                ),
                {"tid": home, "job": job, "epoch": epoch, "value": value},
            )

    response = api.get(f"/v1/training-jobs/{job}/metrics", headers=auth(home_dev))

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(row["epoch"], row["value"]) for row in body["metrics"]] == [(0, 0.1), (1, 0.22)]


async def test_a_snapshot_is_readable_by_id_and_invisible_to_another_tenant(
    trainable, bound, home, home_dev, other_admin
) -> None:
    """BACKEND_PLAN L1131 puts the snapshot at its own address, not under the job."""
    api = await trainable()
    job = _request(api, home_dev, "ref-snapshot").json()["training_job_id"]
    snapshot_id = uuid.uuid4()
    async with bound(home) as session:
        await session.execute(
            sa.text(
                "INSERT INTO dataset_snapshots "
                "  (snapshot_id, tenant_id, training_job_id, cutoff_at, window_days, "
                "   uri, checksum, sequence_count, product_count, event_count) "
                "VALUES (:sid, :tid, :job, now(), :window, 's3://bundles/x.npz', "
                "        :checksum, 24, 12, 192)"
            ),
            {
                "sid": snapshot_id,
                "tid": home,
                "job": job,
                "window": WINDOW,
                # `ck_dataset_snapshots_checksum` wants a whole digest, not
                # a plausible-looking prefix.
                "checksum": f"sha256:{'a' * 64}",
            },
        )

    mine = api.get(f"/v1/datasets/snapshots/{snapshot_id}", headers=auth(home_dev))
    theirs = api.get(f"/v1/datasets/snapshots/{snapshot_id}", headers=auth(other_admin))

    assert mine.status_code == 200, mine.text
    assert mine.json()["sequence_count"] == 24
    assert mine.json()["training_job_id"] == job
    assert theirs.status_code == 404


async def test_training_is_closed_to_the_unauthenticated(trainable) -> None:
    response = (await trainable()).get("/v1/training-jobs")

    assert response.status_code == 401
