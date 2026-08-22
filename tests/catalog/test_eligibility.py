"""One rule, four call sites, and the test that they cannot drift.

Phase 5's completion bar is that "the eligibility function returns identical
results from both call sites". There are in fact four spellings of the rule, and
this module evaluates every one of them over the whole input space:

1. `product_ineligibility(...)` — the SQL function, called directly;
2. `Product.ineligibility` on an **instance** — the Python branch of the hybrid;
3. `Product.ineligibility` in a **query** — the SQL branch of the hybrid, which
   is a call to (1);
4. `ix_products_eligible` — the partial index whose predicate is (1), and which
   the serving path has to be able to walk.

The input space is small enough to enumerate exhaustively: two values of
`is_active`, three of `availability`, two of `deleted_at`. Twelve combinations,
all of them checked, so "we tested the interesting cases" is not a judgement
anybody has to make.

A drift here would be silent. The catalogue screen would show a green `served`
badge while the recommender never returned the product, or the index would omit
a row the serving query expected to find, and nothing would raise.
"""

from __future__ import annotations

import datetime as dt
import itertools
import uuid

import pytest
import sqlalchemy as sa

from graphrec.catalog.eligibility import EXCLUSION_COPY, Ineligibility, exclusion_reason
from graphrec.common.enums import Availability
from graphrec.db.models import Product

pytestmark = [pytest.mark.db, pytest.mark.contract]

REMOVED_AT = dt.datetime(2026, 3, 4, 9, 30, tzinfo=dt.UTC)

#: Every combination of the three inputs the rule reads.
COMBINATIONS = [
    (is_active, availability.value, deleted_at)
    for is_active, availability, deleted_at in itertools.product(
        (True, False),
        tuple(Availability),
        (None, REMOVED_AT),
    )
]


def _expected(is_active: bool, availability: str, deleted_at: dt.datetime | None) -> str | None:
    """The rule, written a fifth time, on purpose.

    Not a helper that calls one of the four — that would compare an
    implementation with itself. This is the specification restated from
    BACKEND_PLAN §3.5, and it is what the other four are measured against.
    """
    if deleted_at is not None:
        return "product_removed"
    if not is_active:
        return "product_inactive"
    if availability == "out_of_stock":
        return "product_out_of_stock"
    return None


@pytest.fixture
async def twelve_products(bound, catalog_tenants, _empty_catalog) -> dict[str, tuple]:
    """One product per combination, in the alpha tenant."""
    rows = {}
    async with bound(catalog_tenants["alpha"]) as session:
        for index, (is_active, availability, deleted_at) in enumerate(COMBINATIONS):
            external_id = f"COMBO-{index:02d}"
            session.add(
                Product(
                    tenant_id=catalog_tenants["alpha"],
                    external_product_id=external_id,
                    title=f"Combination {index}",
                    is_active=is_active,
                    availability=availability,
                    deleted_at=deleted_at,
                    # `ck_products_disabled_has_reason`: an inactive product
                    # carries the reason it was made inactive. The constraint is
                    # the model refusing to let a fixture invent a state the
                    # product does not have.
                    disabled_reason=None if is_active else "Fixture.",
                    disabled_at=None if is_active else REMOVED_AT,
                )
            )
            rows[external_id] = (is_active, availability, deleted_at)
        await session.flush()
    return rows


@pytest.mark.parametrize(("is_active", "availability", "deleted_at"), COMBINATIONS)
async def test_the_sql_function_matches_the_specification(
    bound, catalog_tenants, is_active, availability, deleted_at
) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        result = await session.scalar(
            sa.text("SELECT product_ineligibility(:a, :b, :c)"),
            {"a": is_active, "b": availability, "c": deleted_at},
        )
    assert result == _expected(is_active, availability, deleted_at)


@pytest.mark.parametrize(("is_active", "availability", "deleted_at"), COMBINATIONS)
def test_the_python_branch_matches_the_specification(is_active, availability, deleted_at) -> None:
    """A transient instance — no database involved, which is the point.

    This is the branch that runs when a handler has just written a product and
    renders it back without re-reading it.
    """
    product = Product(
        tenant_id=uuid.uuid4(),
        external_product_id="TRANSIENT",
        title="Transient",
        is_active=is_active,
        availability=availability,
        deleted_at=deleted_at,
    )
    assert product.ineligibility == _expected(is_active, availability, deleted_at)
    assert product.eligible is (_expected(is_active, availability, deleted_at) is None)


async def test_the_query_branch_and_the_instance_branch_agree(
    bound, catalog_tenants, twelve_products
) -> None:
    """The exit criterion, stated as one assertion per product.

    The instance branch is Python; the query branch compiles to a call to the
    SQL function. Twelve rows, and each has to give the same answer twice.
    """
    async with bound(catalog_tenants["alpha"]) as session:
        rows = (
            await session.execute(
                sa.select(
                    Product.external_product_id,
                    Product.ineligibility,
                    Product.eligible,
                ).order_by(Product.external_product_id)
            )
        ).all()
        instances = {
            product.external_product_id: product
            for product in await session.scalars(sa.select(Product))
        }

    assert len(rows) == len(COMBINATIONS)
    for external_id, from_sql, eligible_from_sql in rows:
        instance = instances[external_id]
        expected = _expected(*twelve_products[external_id])
        assert from_sql == expected, f"{external_id}: SQL branch"
        assert instance.ineligibility == expected, f"{external_id}: Python branch"
        assert eligible_from_sql is (expected is None)
        assert instance.eligible is eligible_from_sql, f"{external_id}: eligible disagrees"


async def test_the_serving_filter_returns_exactly_the_eligible_products(
    bound, catalog_tenants, twelve_products
) -> None:
    """`eligible_ids` is the serving path's call site. It must agree with the badge."""
    from graphrec.domain.catalog import CatalogService

    service = CatalogService()
    async with bound(catalog_tenants["alpha"]) as session:
        served = set(await service.eligible_ids(session))
        everything = {
            product.product_id: product for product in await session.scalars(sa.select(Product))
        }

    by_badge = {pid for pid, product in everything.items() if product.eligible}
    assert served == by_badge
    # Exactly two of the twelve serve: active, in stock or low stock, not removed.
    assert len(served) == 2


async def test_the_partial_index_covers_the_serving_filter(
    bound, catalog_tenants, twelve_products
) -> None:
    """The index predicate and the serving predicate are the same expression.

    If they were merely equivalent-looking, the planner would refuse the index
    and the serving path would seq-scan the whole catalogue — correct, and
    unusable at 250,000 products. `enable_seqscan = off` makes the planner state
    its preference on a table too small to have one naturally.
    """
    async with bound(catalog_tenants["alpha"]) as session:
        await session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in await session.execute(
                sa.text(
                    "EXPLAIN SELECT product_id FROM products "
                    "WHERE product_ineligibility(is_active, availability, deleted_at) IS NULL"
                )
            )
        )
    assert "ix_products_eligible" in plan, plan


def test_every_reason_the_function_can_return_has_approved_copy() -> None:
    """A reason with no wording would reach the console as a blank explanation."""
    returned = {
        _expected(is_active, availability, deleted_at)
        for is_active, availability, deleted_at in COMBINATIONS
    } - {None}
    assert returned == {member.value for member in Ineligibility}
    for code in returned:
        assert exclusion_reason(code)
    assert set(EXCLUSION_COPY) == set(Ineligibility)


def test_an_eligible_product_carries_no_explanation() -> None:
    """L1302 — `sub: p.eligible ? '' : p.why`, so `None` rather than a blank string."""
    assert exclusion_reason(None) is None


def test_inactive_wins_over_out_of_stock() -> None:
    """A product that is both is reported as inactive.

    That is the state the tenant chose and the one they can act on; stock is a
    fact about the world. The ordering is the function's, and it is pinned here
    because a future edit could reorder the `CASE` without any other test
    noticing.
    """
    assert _expected(False, "out_of_stock", None) == "product_inactive"
    product = Product(
        tenant_id=uuid.uuid4(),
        external_product_id="BOTH",
        title="Both",
        is_active=False,
        availability="out_of_stock",
    )
    assert product.ineligibility == "product_inactive"
