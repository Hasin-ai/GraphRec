"""The four-stage funnel: what comes back, in what order, and why.

Three claims are asserted here and each one is a requirement rather than a
preference:

* **ER-F-05** — `model_version` and `strategy` are on every response, including
  the fallback one, where `model_version` is `null`. A field that is sometimes
  absent is a field a client has to guess about.
* **ER-NF-06** — the same request against the same data returns the same order.
  Asserted by running it twice and comparing, not by inspecting the sort key: a
  tie-break that happened to be stable for one fixture and not for another would
  pass an inspection and fail a repeat.
* **Isolation** — alpha's products are never returned to beta. The two
  catalogues share external ids on purpose, because a leak with distinct ids
  looks like an error and a leak with matching ids looks like a correct answer.

The fallback lanes each get a test, because "the response is non-empty" is the
whole promise a fallback makes and each lane is a different way of keeping it.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from graphrec.common.enums import ModelVersionStatus
from graphrec.common.errors import UnavailableError
from graphrec.domain.serving.recommend import (
    RecentEvent,
    RecommendationInput,
    RecommendationService,
)
from graphrec.ml.bundle import BUNDLE_NAME, load_bundle
from graphrec.ml.index import InProcessIndex, build_index
from graphrec.serving.states import CandidateSource, RequestStatus, ServingErrorClass, Strategy
from tests.serving.conftest import CATALOGUE, NOW, WITHDRAWN

pytestmark = [pytest.mark.db]


def _request(**overrides) -> RecommendationInput:
    fields = {
        "external_request_id": f"req-{uuid.uuid4().hex[:12]}",
        "top_n": 5,
        "external_customer_id": "CUST-1",
    }
    fields.update(overrides)
    return RecommendationInput(**fields)


@pytest.fixture
def loaded_index(artifact_store, publish_bundle, tmp_path):
    """An index holding a real bundle, loaded the way a replica loads one.

    `load_bundle` rather than `Bundle(...)` because the digest check is part of
    what makes the matrix trustworthy, and a test that constructed the object
    directly would be asserting against bytes nobody verified.
    """

    def _load(tenant_id: uuid.UUID, version_id: uuid.UUID, **kwargs) -> InProcessIndex:
        publish_bundle(tenant_id, version_id, **kwargs)
        from graphrec.storage import keys

        path = tmp_path / f"read-{version_id.hex[:8]}.safetensors"
        artifact_store.get_file(keys.bundle_key(tenant_id, version_id, BUNDLE_NAME), path)
        index = InProcessIndex()
        build_index(index, load_bundle(path, tenant_id=tenant_id))
        return index

    return _load


# ------------------------------------------------------------------ ER-F-05


async def test_every_response_names_its_model_version_and_strategy(
    serving_tenants, seed_catalogue, seed_model_version, bound_serving, loaded_index
) -> None:
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    index = loaded_index(tenant_id, version_id)
    service = RecommendationService(index=index, pinned_version_id=version_id)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(session, tenant_id=tenant_id, request=_request(), now=NOW)

    assert answer.model_version_id == version_id
    assert answer.model_version_number == 1
    assert answer.strategy is Strategy.PERSONALIZED
    assert answer.fallback_applied is False
    assert answer.ordering_policy_version >= 1
    assert len(answer.items) == 5


async def test_a_fallback_response_still_carries_the_fields_with_a_null_version(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    """`null` is a statement; an absent key is an omission.

    No version, no index — the shape of a tenant who has ingested a catalogue
    and not yet trained. They get popular items and a `strategy` that says so.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(session, tenant_id=tenant_id, request=_request(), now=NOW)

    assert answer.model_version_id is None
    assert answer.model_version_number is None
    assert answer.strategy is Strategy.FALLBACK
    assert answer.fallback_applied is True
    assert answer.items, "a fallback that returns nothing has not fallen back"


# ----------------------------------------------------------------- ER-NF-06


async def test_the_same_request_twice_returns_the_same_order(
    serving_tenants, seed_catalogue, seed_model_version, bound_serving, loaded_index
) -> None:
    """Determinism as a property of the output, not of the sort key.

    Two runs, compared item for item including the scores. A tie-break that was
    stable by accident would survive an inspection of `_sort_key` and fail here.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    index = loaded_index(tenant_id, version_id)
    service = RecommendationService(index=index, pinned_version_id=version_id)

    orders = []
    for _ in range(3):
        async with bound_serving(tenant_id) as session:
            answer = await service.recommend(
                session, tenant_id=tenant_id, request=_request(), now=NOW
            )
        orders.append([(item.external_product_id, item.rank, item.score) for item in answer.items])

    assert orders[0] == orders[1] == orders[2]
    assert [item[1] for item in orders[0]] == [1, 2, 3, 4, 5], "ranks are dense and start at one"


async def test_the_popularity_fallback_is_ordered_by_events_then_by_reference(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    """The seeded counts descend with the product number, so the expected order
    is stateable rather than discoverable — and a change in tie-breaking is
    visible as a change in this list."""
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(
            session,
            tenant_id=tenant_id,
            request=_request(external_customer_id=None, session_id="anon-1", top_n=4),
            now=NOW,
        )

    assert [item.external_product_id for item in answer.items] == [
        "SKU-01",
        "SKU-02",
        "SKU-03",
        "SKU-04",
    ]
    assert {item.candidate_source for item in answer.items} == {CandidateSource.POPULARITY}


# ------------------------------------------------------------- fallback lanes


async def test_a_caller_with_no_history_gets_cold_start(
    serving_tenants, seed_catalogue, seed_model_version, bound_serving, loaded_index
) -> None:
    """A model that loaded, and a customer it has never seen.

    Not a fallback: the version is named on the response, because the tenant's
    model *is* available and the reason for the generic answer is the customer,
    not the platform.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    index = loaded_index(tenant_id, version_id)
    service = RecommendationService(index=index, pinned_version_id=version_id)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(
            session,
            tenant_id=tenant_id,
            request=_request(external_customer_id="NEVER-SEEN"),
            now=NOW,
        )

    assert answer.strategy is Strategy.COLD_START
    assert answer.fallback_applied is False
    assert answer.model_version_id == version_id
    assert answer.items


async def test_inline_events_produce_a_session_answer_without_retraining(
    serving_tenants, seed_catalogue, seed_model_version, bound_serving, loaded_index
) -> None:
    """XR-F-09. The anonymous path, answered from what the caller just sent."""
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    index = loaded_index(tenant_id, version_id)
    service = RecommendationService(index=index, pinned_version_id=version_id)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(
            session,
            tenant_id=tenant_id,
            request=_request(
                external_customer_id=None,
                session_id="anon-7",
                recent_events=(RecentEvent(external_product_id="SKU-06"),),
            ),
            now=NOW,
        )

    assert answer.strategy is Strategy.SESSION
    assert "SKU-06" not in {
        item.external_product_id for item in answer.items
    }, "the item the customer is looking at is the least useful thing to show back"


async def test_a_caller_who_declines_the_fallback_is_refused_rather_than_degraded(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    """The plan's `503`, and the only condition that produces one.

    Refused only when nothing can answer *and* the caller said they would rather
    have an error than a degraded answer. `allow_fallback` defaults to true, so
    this is opt-in.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)

    async with bound_serving(tenant_id) as session:
        with pytest.raises(UnavailableError) as raised:
            await service.recommend(
                session,
                tenant_id=tenant_id,
                request=_request(allow_fallback=False),
                now=NOW,
            )

    assert raised.value.code == "model_not_ready"


async def test_a_refusal_is_recorded_on_a_session_of_its_own(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    """`/service-status/errors` must show a serving path that failed.

    A row written inside the transaction that raised would be rolled back with
    it, and the console would report a serving path that was never asked.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)
    request = _request(allow_fallback=False)

    async with bound_serving(tenant_id) as session:
        with pytest.raises(UnavailableError):
            await service.recommend(session, tenant_id=tenant_id, request=request, now=NOW)

    async with bound_serving(tenant_id) as session:
        recorded = await service.record_refusal(
            session,
            tenant_id=tenant_id,
            request=request,
            error_class=ServingErrorClass.UNAVAILABLE,
            reason_key="model_not_ready",
        )
    assert recorded is not None

    async with bound_serving(tenant_id) as session:
        status, error_class, reason, returned = (
            await session.execute(
                sa.text(
                    "SELECT status, error_class, error_reason, returned_count "
                    "FROM recommendation_requests WHERE request_id = :rid"
                ),
                {"rid": recorded},
            )
        ).one()

    assert status == RequestStatus.REFUSED.value
    assert error_class == ServingErrorClass.UNAVAILABLE.value
    assert returned == 0
    # Approved copy, resolved at insert time. There is no path by which a
    # caller's string reaches this column.
    assert reason is not None
    assert request.external_request_id not in reason


# ------------------------------------------------------------------ catalogue


async def test_an_inactive_product_is_never_returned_by_any_lane(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    """The eligibility predicate is read once and applied to the merged set.

    Asked for the whole catalogue, so the withdrawn item's absence is a
    filtering decision rather than a consequence of the list being short.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(
            session,
            tenant_id=tenant_id,
            request=_request(top_n=len(CATALOGUE)),
            now=NOW,
        )

    assert WITHDRAWN not in {item.external_product_id for item in answer.items}


async def test_a_caller_exclusion_is_honoured(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)

    async with bound_serving(tenant_id) as session:
        answer = await service.recommend(
            session,
            tenant_id=tenant_id,
            request=_request(top_n=4, exclude_product_ids=("SKU-01", "SKU-02")),
            now=NOW,
        )

    returned = {item.external_product_id for item in answer.items}
    assert returned.isdisjoint({"SKU-01", "SKU-02"})


async def test_one_tenants_products_are_never_returned_to_another(
    serving_tenants, seed_catalogue, seed_model_version, bound_serving, loaded_index
) -> None:
    """The external ids collide on purpose.

    With distinct ids a leak looks like an error; with matching ids a leak looks
    like a correct answer, and only the internal product id tells them apart. So
    this asserts on the ids the two tenants' rows actually have.
    """
    alpha, beta = serving_tenants["alpha"], serving_tenants["beta"]
    alpha_ids = seed_catalogue(alpha)
    beta_ids = seed_catalogue(beta)
    version_id = seed_model_version(beta, version_number=1, status=ModelVersionStatus.ACTIVE)
    index = loaded_index(beta, version_id)
    service = RecommendationService(index=index, pinned_version_id=version_id)

    async with bound_serving(beta) as session:
        answer = await service.recommend(
            session, tenant_id=beta, request=_request(top_n=len(CATALOGUE)), now=NOW
        )

    returned = {item.external_product_id for item in answer.items}
    assert returned, "beta must get an answer of its own"

    # Every returned reference resolves to a beta row, and none of alpha's
    # product ids appear anywhere in beta's recorded results.
    async with bound_serving(beta) as session:
        product_ids = set(
            (
                await session.scalars(
                    sa.text(
                        "SELECT product_id FROM recommendation_results " "WHERE tenant_id = :tid"
                    ),
                    {"tid": beta},
                )
            ).all()
        )

    alpha_products = {value for key, value in alpha_ids.items() if key in CATALOGUE}
    beta_products = {value for key, value in beta_ids.items() if key in CATALOGUE}
    assert product_ids <= beta_products
    assert product_ids.isdisjoint(alpha_products)


async def test_a_request_naming_nobody_is_refused(
    serving_tenants, seed_catalogue, bound_serving
) -> None:
    """Not a cold-start request — a request whose feedback can never be
    attributed to anything."""
    from graphrec.common.errors import ValidationError

    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    service = RecommendationService(index=None)

    async with bound_serving(tenant_id) as session:
        with pytest.raises(ValidationError):
            await service.recommend(
                session,
                tenant_id=tenant_id,
                request=_request(external_customer_id=None),
                now=NOW,
            )
