"""Metering where it is actually charged: the ingest path.

BUILD_PROMPT 7.5 puts the quota check "inside creating transactions", which is a
claim about a boundary rather than about a number. These tests exercise the
whole path — the API route, the domain service, the ledger and the counter —
because that is the only place the boundary can be observed: a check running in
its own transaction would pass here on a quiet database and fail in production
on a busy one.

Two people appear in every test, and that is the system working as designed. The
developer submits, because ingest is a developer's route (L1170); the
administrator reads the usage, because usage is an administrator's page (L1256).
The person who spends the quota is not the person who can see it, so the tests
have to hold both tokens to observe one fact.

The other thing asserted here is that the ledger records what was *accepted*,
not what was *submitted*. A duplicate event is confirmed to the tenant and must
not be charged twice; a refused write must leave nothing behind.
"""

from __future__ import annotations

import decimal

import pytest
import sqlalchemy as sa
from anyio import to_thread

from graphrec.common.enums import UsageType
from graphrec.domain.metering.periods import current_period
from graphrec.domain.quotas import utcnow
from tests.authz.conftest import auth

pytestmark = [pytest.mark.db]


@pytest.fixture(scope="session")
def metered_product(api, home_dev) -> str:
    """One product for the metered events to reference.

    Created through the API, the way the ingest suite's is, because an event
    naming a product inserted behind the API's back would exercise a catalogue
    state the API cannot produce.
    """
    external_id = "SKU-MET-1"
    api.put(
        f"/v1/products/{external_id}",
        json={"title": "Metering fixture product"},
        headers=auth(home_dev),
    )
    return external_id


def _event(event_id: str, product: str = "SKU-MET-1") -> dict:
    return {
        "event_id": event_id,
        "customer_id": "cus-metering",
        "external_product_id": product,
        "event_type": "purchase",
        "occurred_at": "2026-08-14T09:41:02Z",
    }


async def _off_loop(call):
    """Run a blocking `TestClient` call from an async test.

    The batch tests need the real worker, which is async, and the real HTTP
    surface, whose client is synchronous. Calling the client from a worker
    thread is the honest way to have both: the client runs its own portal, so
    nothing is nested inside this test's event loop.
    """
    return await to_thread.run_sync(call)


def _charged(api, home_admin) -> int:
    """What `/v1/usage` says the tenant has used, as an integer."""
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    events = next(item for item in body["items"] if item["usage_type"] == UsageType.EVENTS.value)
    return int(decimal.Decimal(str(events["measured"])))


# --------------------------------------------------------- what gets charged


def test_an_accepted_event_is_charged_once(api, home_admin, home_dev, metered_product) -> None:
    """The base case, end to end.

    Charged through the ledger and visible on `/usage` in the same breath: if
    the grant and the report disagreed, one of them would be the tenant's bill
    and the other would be the tenant's evidence.
    """
    before = _charged(api, home_admin)

    response = api.post("/v1/events", json=_event("evt-metered-1"), headers=auth(home_dev))
    assert response.status_code == 200, response.text

    assert _charged(api, home_admin) == before + 1


def test_a_duplicate_event_is_confirmed_and_not_charged_again(
    api, home_admin, home_dev, metered_product
) -> None:
    """Phase 6's `duplicate_confirmed` meets Phase 7's ledger.

    A retrying client — the reason `duplicate_confirmed` exists — must not be
    billed for its retries. The event was not written twice, so the usage it
    caused was not incurred twice.
    """
    api.post("/v1/events", json=_event("evt-metered-dup"), headers=auth(home_dev))
    after_first = _charged(api, home_admin)

    repeat = api.post("/v1/events", json=_event("evt-metered-dup"), headers=auth(home_dev))
    assert repeat.status_code == 200, repeat.text

    assert _charged(api, home_admin) == after_first


def test_a_rejected_event_is_not_charged(api, home_admin, home_dev) -> None:
    """An event naming a product that does not exist is refused, and refusing is
    free. Charging for work we declined to do is the clearest possible way to
    make a metering system untrustworthy."""
    before = _charged(api, home_admin)

    response = api.post(
        "/v1/events",
        json=_event("evt-metered-unknown", product="SKU-DOES-NOT-EXIST"),
        headers=auth(home_dev),
    )
    assert response.status_code == 422, response.text

    assert _charged(api, home_admin) == before


# ------------------------------------------------- the check and the insert


def test_an_exhausted_quota_refuses_the_write(
    api, home_admin, home_dev, metered_product, plan_limit, realm, tenant_scalar
) -> None:
    """429, and no event.

    This is the assertion that the check guards the insert rather than merely
    preceding it in the file. The tenant is put exactly at their limit, the
    write is attempted, and the count of stored events must be unchanged — a
    check in a separate transaction would let the insert proceed on its own.
    """
    tenant_id = realm["home"]["tenant_id"]
    plan_limit(tenant_id, event_limit=_charged(api, home_admin))

    before = _event_rows(tenant_scalar, tenant_id)
    assert before > 0, "an assertion about no new rows needs rows to begin with"

    response = api.post("/v1/events", json=_event("evt-over-quota"), headers=auth(home_dev))

    assert response.status_code == 429, response.text
    assert _event_rows(tenant_scalar, tenant_id) == before


def test_the_refusal_is_the_approved_sentence(
    api, home_admin, home_dev, metered_product, plan_limit, realm
) -> None:
    """The tenant is told the numbers, not just told no (L1603 / L1637)."""
    tenant_id = realm["home"]["tenant_id"]
    plan_limit(tenant_id, event_limit=_charged(api, home_admin))

    body = api.post("/v1/events", json=_event("evt-over-quota-copy"), headers=auth(home_dev)).json()

    assert body["error"]["class"] == "limit"
    reason = body["error"]["reason"]
    assert " events on plan " in reason
    assert "quota resets on" in reason


def test_a_quota_refusal_is_visible_to_the_administrator_as_no_remaining(
    api, home_admin, home_dev, metered_product, plan_limit, realm
) -> None:
    """The developer's 429 and the administrator's page are the same fact.

    A developer refused at the API and an administrator seeing allowance left
    would be two accounts of one month, and the support conversation that
    follows has no way to settle which is right.
    """
    plan_limit(realm["home"]["tenant_id"], event_limit=_charged(api, home_admin))
    refused = api.post("/v1/events", json=_event("evt-quota-view"), headers=auth(home_dev))
    assert refused.status_code == 429

    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    events = next(item for item in body["items"] if item["usage_type"] == UsageType.EVENTS.value)
    assert events["remaining"] == 0


@pytest.mark.anyio
async def test_a_batch_is_charged_for_what_it_accepted(
    api, home_admin, home_dev, metered_product, drain
) -> None:
    """The worker's half. Three submitted, one bad, two charged.

    The count that matters is the merge's, not the submission's: a batch is
    accepted at the door before anything in it has been validated, and charging
    on receipt would bill a tenant for items we then refused.
    """
    before = await _off_loop(lambda: _charged(api, home_admin))

    response = await _off_loop(
        lambda: api.post(
            "/v1/events/batches",
            json={
                "batch_id": "metered-batch-1",
                "events": [
                    _event("evt-batch-a"),
                    _event("evt-batch-b"),
                    _event("evt-batch-bad", product="SKU-DOES-NOT-EXIST"),
                ],
            },
            headers=auth(home_dev),
        )
    )
    assert response.status_code == 202, response.text
    await drain()

    submission_id = response.json()["submission_id"]
    submission = await _off_loop(
        lambda: api.get(f"/v1/submissions/{submission_id}", headers=auth(home_dev)).json()
    )
    accepted = submission["counts"]["accepted"] + submission["counts"]["updated"]

    assert accepted == 2
    assert await _off_loop(lambda: _charged(api, home_admin)) == before + accepted


@pytest.mark.anyio
async def test_the_batch_grant_is_keyed_to_the_submission(
    api, home_dev, metered_product, drain, bound, realm
) -> None:
    """One ledger row per submission, so a re-run of the handler cannot double it.

    A job whose lease expired mid-merge is retried by design (Phase 4), and the
    idempotency key is what makes that retry cost nothing.
    """
    response = await _off_loop(
        lambda: api.post(
            "/v1/events/batches",
            json={"batch_id": "metered-batch-2", "events": [_event("evt-batch-keyed")]},
            headers=auth(home_dev),
        )
    )
    submission_id = response.json()["submission_id"]
    await drain()

    async with bound(realm["home"]["tenant_id"]) as session:
        rows = await session.scalar(
            sa.text(
                "SELECT count(*) FROM usage_events "
                "WHERE usage_type = 'events' AND idempotency_key = :key"
            ),
            {"key": f"submission:{submission_id}"},
        )

    assert rows == 1


# ------------------------------------------------------------- the two views


def test_the_ledger_and_the_page_agree(
    api, home_admin, home_dev, metered_product, ledger_total, realm
) -> None:
    """The counter is a cache; the ledger is the account.

    `/usage` reads the fast counter, so this is the assertion that the fast path
    has not drifted from the durable one — the drift the rollup exists to
    repair, caught before it needs repairing.
    """
    api.post("/v1/events", json=_event("evt-agree"), headers=auth(home_dev))

    page = _charged(api, home_admin)
    durable = ledger_total(realm["home"]["tenant_id"], UsageType.EVENTS, current_period(utcnow()))

    assert durable == decimal.Decimal(page)


def _event_rows(tenant_scalar, tenant_id) -> int:
    return int(tenant_scalar(tenant_id, "SELECT count(*) FROM interaction_events") or 0)
