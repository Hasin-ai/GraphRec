"""The catalogue service: the three write verbs, the quota, and the tenant wall.

Every test runs as `graphrec_app` inside a bound transaction, which is what a
request does. Nothing here passes a `tenant_id` to a read — that is the property
being relied on, not an omission.
"""

from __future__ import annotations

import decimal
import uuid

import pytest
import sqlalchemy as sa

from graphrec.common.errors import ConflictError, LimitError, NotFoundError, ValidationError
from graphrec.db.models import Product, ProductCategory
from graphrec.domain.catalog import CatalogService, ProductFilter, ProductWrite

# Every test starts from an empty catalogue. Applied to the module rather than
# named per test: a test that forgot it would pass on its own and fail when the
# suite ran in a different order, which is the worst kind of red.
pytestmark = [pytest.mark.db, pytest.mark.usefixtures("_empty_catalog")]


@pytest.fixture
def service() -> CatalogService:
    return CatalogService()


def _write(**kwargs) -> ProductWrite:
    return ProductWrite(**kwargs)


async def _create(service, session, tenant_id, external_id, **kwargs) -> Product:
    return await service.create(
        session,
        tenant_id=tenant_id,
        external_product_id=external_id,
        write=_write(title=kwargs.pop("title", "Brass hinge, 75mm"), **kwargs),
    )


# ------------------------------------------------------------------ create


async def test_a_product_is_created_and_serves(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        product = await _create(service, session, catalog_tenants["alpha"], "SKU-0001")
        assert product.eligible
        assert product.ineligibility is None
        assert product.is_active


async def test_a_duplicate_identifier_is_a_conflict_with_the_prototypes_words(
    service, bound, catalog_tenants
) -> None:
    """L1604, second sentence included — it is the half that says what to do next."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-4471")

    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(ConflictError) as caught:
            await _create(service, session, catalog_tenants["alpha"], "SKU-4471")

    assert caught.value.code == "product_already_exists"
    assert caught.value.reason() == (
        "A product with identifier SKU-4471 already exists. "
        "Use a different identifier or update the existing product."
    )
    assert [(f.field, f.reason) for f in caught.value.field_errors] == [
        ("external_product_id", "Already exists in this tenant.")
    ]


async def test_two_tenants_may_hold_the_same_external_identifier(
    service, bound, catalog_tenants
) -> None:
    """Uniqueness is per tenant. Anything else would leak the other tenant's catalogue."""
    for name in ("alpha", "beta"):
        async with bound(catalog_tenants[name]) as session:
            await _create(service, session, catalog_tenants[name], "SKU-SHARED")

    async with bound(catalog_tenants["alpha"]) as session:
        assert (await service.list_products(session)).total == 1


async def test_an_empty_identifier_is_refused_with_the_field_copy(
    service, bound, catalog_tenants
) -> None:
    """L1602: the sentence in the banner, "Required." beside the input."""
    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(ValidationError) as caught:
            await _create(service, session, catalog_tenants["alpha"], "   ")
    assert caught.value.reason() == "An external product identifier is required."
    assert [(f.field, f.reason) for f in caught.value.field_errors] == [
        ("external_product_id", "Required.")
    ]


async def test_an_empty_title_is_refused(service, bound, catalog_tenants) -> None:
    """L1605."""
    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(ValidationError) as caught:
            await _create(service, session, catalog_tenants["alpha"], "SKU-0002", title="  ")
    assert caught.value.reason() == "A title is required."


async def test_a_negative_price_is_refused(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(ValidationError) as caught:
            await _create(
                service,
                session,
                catalog_tenants["alpha"],
                "SKU-0003",
                price=decimal.Decimal("-1.00"),
            )
    assert [f.field for f in caught.value.field_errors] == ["price"]


# ------------------------------------------------------------------- quota


async def test_the_quota_is_enforced_before_the_insert(
    service, bound, catalog_tenants, grant_override
) -> None:
    """L1603, with the counts and the plan code the message quotes."""
    grant_override(catalog_tenants["alpha"], usage_type="products", limit_value=1)

    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")

    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(LimitError) as caught:
            await _create(service, session, catalog_tenants["alpha"], "SKU-0002")

    assert caught.value.code == "product_quota_exhausted"
    assert caught.value.reason() == (
        "This tenant holds 1 of 1 products on plan GROWTH. "
        "Disable products you no longer sell, "
        "or ask your platform contact about a quota override."
    )

    # And the refused product was not written. "Rejected before the operation is
    # accepted" (L1170) is a promise about side effects, not only about status
    # codes.
    async with bound(catalog_tenants["alpha"]) as session:
        assert (await service.list_products(session)).total == 1


async def test_one_tenants_quota_does_not_bind_another(
    service, bound, catalog_tenants, grant_override
) -> None:
    grant_override(catalog_tenants["alpha"], usage_type="products", limit_value=0)

    async with bound(catalog_tenants["beta"]) as session:
        product = await _create(service, session, catalog_tenants["beta"], "SKU-0001")
        assert product.product_id is not None


async def test_a_disabled_product_still_counts_against_the_quota(
    service, bound, catalog_tenants, grant_override
) -> None:
    """ "The record is retained" (L1340). A retained record occupies a row.

    Disabling to make room would be a quota that can be evaded by leaving the
    catalogue exactly as large as it was.
    """
    grant_override(catalog_tenants["alpha"], usage_type="products", limit_value=1)

    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")
        await service.disable(
            session, external_product_id="SKU-0001", reason="Discontinued by supplier"
        )

    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(LimitError):
            await _create(service, session, catalog_tenants["alpha"], "SKU-0002")


# --------------------------------------------------------------- read / list


async def test_a_foreign_product_is_not_found_rather_than_forbidden(
    service, bound, catalog_tenants
) -> None:
    """Gate 4. The 404 also never names what was not found."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-PRIVATE")

    async with bound(catalog_tenants["beta"]) as session:
        with pytest.raises(NotFoundError) as caught:
            await service.get(session, external_product_id="SKU-PRIVATE")

    assert caught.value.status_code == 404
    assert "product" not in caught.value.reason().lower()


async def test_a_list_is_only_the_callers_catalogue(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        for index in range(3):
            await _create(service, session, catalog_tenants["alpha"], f"A-{index}")
    async with bound(catalog_tenants["beta"]) as session:
        await _create(service, session, catalog_tenants["beta"], "B-0")

    async with bound(catalog_tenants["alpha"]) as session:
        page = await service.list_products(session)
    assert page.total == 3
    assert {p.external_product_id for p in page.items} == {"A-0", "A-1", "A-2"}


async def test_the_total_counts_the_filter_not_the_page(service, bound, catalog_tenants) -> None:
    """The console renders "8 of 12" (L1316), so the total is the filtered count."""
    async with bound(catalog_tenants["alpha"]) as session:
        for index in range(5):
            await _create(service, session, catalog_tenants["alpha"], f"SKU-{index}")

    async with bound(catalog_tenants["alpha"]) as session:
        page = await service.list_products(session, limit=2)

    assert len(page.items) == 2
    assert page.total == 5


async def test_the_three_filters_are_the_prototypes_three(service, bound, catalog_tenants) -> None:
    """Category, availability, and "identifier or title" (L1314)."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-HW-1", category="Hardware")
        await _create(
            service,
            session,
            catalog_tenants["alpha"],
            "SKU-TM-1",
            category="Timber",
            availability="low_stock",
            title="Softwood batten",
        )

    async with bound(catalog_tenants["alpha"]) as session:
        by_category = await service.list_products(session, filters=ProductFilter(category="Timber"))
        by_availability = await service.list_products(
            session, filters=ProductFilter(availability="low_stock")
        )
        by_identifier = await service.list_products(session, filters=ProductFilter(search="hw"))
        by_title = await service.list_products(session, filters=ProductFilter(search="softwood"))

    assert [p.external_product_id for p in by_category.items] == ["SKU-TM-1"]
    assert [p.external_product_id for p in by_availability.items] == ["SKU-TM-1"]
    assert [p.external_product_id for p in by_identifier.items] == ["SKU-HW-1"]
    assert [p.external_product_id for p in by_title.items] == ["SKU-TM-1"]


async def test_a_search_for_a_wildcard_is_a_search_for_the_character(
    service, bound, catalog_tenants
) -> None:
    """An unescaped `%` would make the search box match the whole catalogue."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001", title="Plain")
        await _create(service, session, catalog_tenants["alpha"], "SKU-0002", title="50% off")

    async with bound(catalog_tenants["alpha"]) as session:
        page = await service.list_products(session, filters=ProductFilter(search="50%"))

    assert [p.external_product_id for p in page.items] == ["SKU-0002"]


async def test_a_removed_product_is_not_listed(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        product = await _create(service, session, catalog_tenants["alpha"], "SKU-GONE")
        product.deleted_at = sa.func.now()

    async with bound(catalog_tenants["alpha"]) as session:
        assert (await service.list_products(session)).total == 0
        with pytest.raises(NotFoundError):
            await service.get(session, external_product_id="SKU-GONE")


# ------------------------------------------------------------ upsert / patch


async def test_a_put_creates_then_is_idempotent(service, bound, catalog_tenants) -> None:
    """The external identifier is the idempotency key (L1320)."""
    async with bound(catalog_tenants["alpha"]) as session:
        first, created = await service.upsert(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(title="Brass hinge"),
        )
        first_id = first.product_id
    assert created is True

    async with bound(catalog_tenants["alpha"]) as session:
        second, created_again = await service.upsert(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(title="Brass hinge"),
        )
        assert second.product_id == first_id
    assert created_again is False


async def test_a_put_replaces_and_a_patch_does_not(service, bound, catalog_tenants) -> None:
    """The whole of D9 in one test.

    A `PUT` that omitted the brand and left it standing would be a `PATCH`
    wearing a different verb, and an integration that relied on replacement
    would carry a stale brand forever without an error anywhere.
    """
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(
            service,
            session,
            catalog_tenants["alpha"],
            "SKU-0001",
            brand="Northgate",
            price=decimal.Decimal("8.40"),
        )

    async with bound(catalog_tenants["alpha"]) as session:
        replaced, _ = await service.upsert(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(title="Brass hinge, 75mm"),
        )
        assert replaced.brand is None
        assert replaced.price is None

    async with bound(catalog_tenants["alpha"]) as session:
        await service.patch(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(brand="Northgate"),
        )
    async with bound(catalog_tenants["alpha"]) as session:
        patched = await service.patch(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(title="Brass hinge, 100mm"),
        )
        assert patched.brand == "Northgate"
        assert patched.title == "Brass hinge, 100mm"


async def test_a_patch_can_clear_a_field_explicitly(service, bound, catalog_tenants) -> None:
    """`None` clears; absent leaves alone. That is why the sentinel is not `None`."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001", brand="Northgate")

    async with bound(catalog_tenants["alpha"]) as session:
        patched = await service.patch(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(brand=None),
        )
        assert patched.brand is None


async def test_patching_a_foreign_product_is_not_found(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-PRIVATE")

    async with bound(catalog_tenants["beta"]) as session:
        with pytest.raises(NotFoundError):
            await service.patch(
                session,
                tenant_id=catalog_tenants["beta"],
                external_product_id="SKU-PRIVATE",
                write=_write(title="Renamed"),
            )


async def test_a_put_by_a_second_tenant_creates_its_own_product(
    service, bound, catalog_tenants
) -> None:
    """A `PUT` must never become an update of somebody else's row.

    The upsert looks the product up by external id with no tenant predicate, so
    if RLS were not carrying the scope this would silently overwrite alpha's
    product with beta's title.
    """
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-SHARED", title="Alpha's")

    async with bound(catalog_tenants["beta"]) as session:
        product, created = await service.upsert(
            session,
            tenant_id=catalog_tenants["beta"],
            external_product_id="SKU-SHARED",
            write=_write(title="Beta's"),
        )
        assert created is True
        assert product.tenant_id == catalog_tenants["beta"]

    async with bound(catalog_tenants["alpha"]) as session:
        kept = await service.get(session, external_product_id="SKU-SHARED")
        assert kept.title == "Alpha's"


# ---------------------------------------------------------------- categories


async def test_a_category_is_created_on_first_reference_and_reused(
    service, bound, catalog_tenants
) -> None:
    """The console has no category-management screen, and a sync carries names inline."""
    async with bound(catalog_tenants["alpha"]) as session:
        first = await _create(
            service, session, catalog_tenants["alpha"], "SKU-0001", category="Hardware"
        )
        second = await _create(
            service, session, catalog_tenants["alpha"], "SKU-0002", category="Hardware"
        )
        assert first.category_id == second.category_id

    async with bound(catalog_tenants["alpha"]) as session:
        count = await session.scalar(sa.select(sa.func.count()).select_from(ProductCategory))
    assert count == 1


async def test_a_category_is_not_shared_between_tenants(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        alpha = await _create(
            service, session, catalog_tenants["alpha"], "SKU-0001", category="Hardware"
        )
        alpha_category = alpha.category_id
    async with bound(catalog_tenants["beta"]) as session:
        beta = await _create(
            service, session, catalog_tenants["beta"], "SKU-0001", category="Hardware"
        )
        assert beta.category_id != alpha_category


# ------------------------------------------------------------------ disable


async def test_disabling_stops_serving_and_keeps_the_record(
    service, bound, catalog_tenants
) -> None:
    """L1339-L1340. Not a delete — there is no `DELETE` grant that would allow one."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")

    async with bound(catalog_tenants["alpha"]) as session:
        disabled = await service.disable(
            session, external_product_id="SKU-0001", reason="Discontinued by supplier"
        )
        assert disabled.is_active is False
        assert disabled.eligible is False
        assert disabled.ineligibility == "product_inactive"
        assert disabled.disabled_reason == "Discontinued by supplier"
        assert disabled.disabled_at is not None

    async with bound(catalog_tenants["alpha"]) as session:
        assert (await service.list_products(session)).total == 1
        assert await service.eligible_ids(session) == []


async def test_disabling_twice_is_a_conflict(service, bound, catalog_tenants) -> None:
    """L1331, which is also the console's reason for the disabled control."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")
        await service.disable(session, external_product_id="SKU-0001", reason="Discontinued")

    async with bound(catalog_tenants["alpha"]) as session:
        with pytest.raises(ConflictError) as caught:
            await service.disable(session, external_product_id="SKU-0001", reason="Again")
    assert caught.value.reason() == "This product is already disabled."


async def test_a_short_reason_is_refused_with_the_dialogs_words(
    service, bound, catalog_tenants
) -> None:
    """L1342 — `f.reason.trim().length < 4` in the prototype's own commit."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")
        with pytest.raises(ValidationError) as caught:
            await service.disable(session, external_product_id="SKU-0001", reason=" no ")
    assert caught.value.reason() == "A reason is required for this action."


async def test_a_reason_of_exactly_four_characters_is_accepted(
    service, bound, catalog_tenants
) -> None:
    """The floor is `< 4`, so four is enough. Off-by-one, pinned."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")
        product = await service.disable(session, external_product_id="SKU-0001", reason="gone")
        assert product.disabled_reason == "gone"


async def test_disabling_a_foreign_product_is_not_found(service, bound, catalog_tenants) -> None:
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-PRIVATE")

    async with bound(catalog_tenants["beta"]) as session:
        with pytest.raises(NotFoundError):
            await service.disable(
                session, external_product_id="SKU-PRIVATE", reason="Not mine to disable"
            )


async def test_an_update_re_enables_a_disabled_product(service, bound, catalog_tenants) -> None:
    """ "can be re-enabled by an update" (L1340), and the stale reason goes with it."""
    async with bound(catalog_tenants["alpha"]) as session:
        await _create(service, session, catalog_tenants["alpha"], "SKU-0001")
        await service.disable(session, external_product_id="SKU-0001", reason="Discontinued")

    async with bound(catalog_tenants["alpha"]) as session:
        product = await service.patch(
            session,
            tenant_id=catalog_tenants["alpha"],
            external_product_id="SKU-0001",
            write=_write(is_active=True),
        )
        assert product.is_active is True
        assert product.disabled_reason is None
        assert product.disabled_at is None
        assert product.eligible is True


async def test_the_catalogue_never_writes_to_another_tenants_row(
    service, bound, catalog_tenants
) -> None:
    """The `WITH CHECK` half of the policy, stated as a test.

    A `USING`-only policy would let a tenant read nothing and still insert a row
    stamped with somebody else's identifier.
    """
    async with bound(catalog_tenants["alpha"]) as session:
        session.add(
            Product(
                tenant_id=catalog_tenants["beta"],
                external_product_id="SMUGGLED",
                title="Smuggled",
            )
        )
        with pytest.raises(sa.exc.ProgrammingError):
            await session.flush()


async def test_an_unbound_session_sees_no_catalogue(
    service, catalog_sessionmaker, catalog_tenants
) -> None:
    """Default deny: no `app.tenant_id`, no rows. Not "all rows"."""
    async with catalog_sessionmaker() as session, session.begin():
        # No `bind_tenant`. `current_setting('app.tenant_id', true)` is NULL and
        # the policy's comparison is therefore NULL, which is not TRUE.
        count = await session.scalar(sa.select(sa.func.count()).select_from(Product))
    assert count == 0


async def test_the_repr_of_a_product_carries_no_commercial_data(service) -> None:
    """NR-NF-06 — a repr reaches logs, and a catalogue is commercially sensitive."""
    product = Product(
        tenant_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        external_product_id="SKU-0001",
        title="Brass hinge, 75mm",
        price=decimal.Decimal("8.40"),
    )
    rendered = repr(product)
    assert "Brass hinge" not in rendered
    assert "8.40" not in rendered
