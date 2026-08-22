"""`/v1/products*` over HTTP: the role gate, the wire vocabulary, the verbs.

The gate is the surprising part and it is tested first. All four catalogue
screens are declared `[DEV]` in the prototype's route table (dc.html L645-646),
and L1256 says an administrator has "No catalog access and no event submission."
**Read included** — which is the opposite of `/users`, where read is open to
both roles. An administrator being able to list the catalogue would not be a
leak between tenants, but it would be the product doing something the
specification says it does not.
"""

from __future__ import annotations

import pytest

from tests.authz.conftest import auth

pytestmark = [pytest.mark.db, pytest.mark.authz, pytest.mark.usefixtures("_empty_catalog")]

CATALOG_ROUTES = (
    ("get", "/v1/products", None),
    ("get", "/v1/products/SKU-0001", None),
    ("post", "/v1/products", {"external_id": "SKU-0001", "title": "Brass hinge"}),
    ("put", "/v1/products/SKU-0001", {"title": "Brass hinge"}),
    ("patch", "/v1/products/SKU-0001", {"title": "Brass hinge"}),
    ("post", "/v1/products/SKU-0001:disable", {"reason": "Discontinued by supplier"}),
)


def _call(api, method, path, body, headers=None):
    """`TestClient.get` takes no `json=`, so the parametrised sweeps go through here."""
    kwargs = {} if body is None else {"json": body}
    if headers is not None:
        kwargs["headers"] = headers
    return getattr(api, method)(path, **kwargs)


def _create(api, token, external_id="SKU-0001", **fields):
    body = {"external_id": external_id, "title": "Brass hinge, 75mm", **fields}
    return api.post("/v1/products", json=body, headers=auth(token))


# --------------------------------------------------------------- gate 3


@pytest.mark.parametrize(("method", "path", "body"), CATALOG_ROUTES)
def test_an_administrator_is_refused_every_catalogue_route(
    api, home_admin, method, path, body
) -> None:
    """Including the reads. L1256: "No catalog access"."""
    response = _call(api, method, path, body, auth(home_admin))
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "insufficient_role"


@pytest.mark.parametrize(("method", "path", "body"), CATALOG_ROUTES)
def test_no_credential_is_refused_before_the_role_is_considered(api, method, path, body) -> None:
    """Gate 1 runs before gate 3, so an anonymous caller learns nothing about roles."""
    response = _call(api, method, path, body)
    assert response.status_code == 401


def test_the_role_refusal_says_there_is_nothing_to_retry(api, home_admin) -> None:
    """L1063 — the last sentence tells the console not to offer a retry."""
    response = api.get("/v1/products", headers=auth(home_admin))
    assert response.json()["error"]["reason"] == (
        "Your role or named permission does not include this operation. "
        "There is nothing to retry here."
    )


def test_a_developer_reaches_the_catalogue(api, home_dev) -> None:
    response = api.get("/v1/products", headers=auth(home_dev))
    assert response.status_code == 200
    assert response.json() == {"products": [], "total": 0, "limit": 50, "offset": 0}


# ------------------------------------------------------------- create


def test_a_created_product_uses_the_prototypes_field_names(api, home_dev) -> None:
    """L1173's payload: `external_id`, `title`, `category`, `brand`, `price`,
    `active`, `availability` — not the column names."""
    response = _create(
        api,
        home_dev,
        external_id="SKU-4471",
        category="Hardware",
        brand="Northgate",
        price="8.40",
        active=True,
        availability="in_stock",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["external_id"] == "SKU-4471"
    assert body["category"] == "Hardware"
    assert body["brand"] == "Northgate"
    assert body["price"] == "8.40"
    assert body["active"] is True
    assert body["availability"] == "in_stock"
    assert body["eligible"] is True
    assert body["ineligibility"] is None
    assert body["exclusion_reason"] is None
    assert body["can_disable"] is True
    assert body["blocked_reason"] is None


def test_a_response_never_carries_an_internal_identifier(api, home_dev) -> None:
    """No `product_id`, no `tenant_id`, no `category_id`.

    The external identifier is the product's name on the wire. Publishing the
    internal key as well would give integrations a second thing to key on.
    """
    body = _create(api, home_dev).json()
    assert "product_id" not in body
    assert "tenant_id" not in body
    assert "category_id" not in body


def test_a_price_is_carried_as_a_string(api, home_dev) -> None:
    """ "8.40", not 8.4. A float price is a price that cannot be represented exactly."""
    body = _create(api, home_dev, price="8.40").json()
    assert body["price"] == "8.40"


def test_a_duplicate_is_a_conflict_with_the_prototypes_sentence(api, home_dev) -> None:
    _create(api, home_dev, external_id="SKU-4471")
    response = _create(api, home_dev, external_id="SKU-4471")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["class"] == "conflict"
    assert error["code"] == "product_already_exists"
    assert error["reason"] == (
        "A product with identifier SKU-4471 already exists. "
        "Use a different identifier or update the existing product."
    )
    assert error["field_errors"] == [
        {"field": "external_product_id", "reason": "Already exists in this tenant."}
    ]


def test_a_body_carrying_a_tenant_id_is_refused(api, home_dev) -> None:
    """Tenant scope comes from the verified token. A body field would be a second source."""
    response = api.post(
        "/v1/products",
        json={"external_id": "SKU-0001", "title": "Brass hinge", "tenant_id": "x"},
        headers=auth(home_dev),
    )
    assert response.status_code == 422


def test_an_unknown_availability_is_refused(api, home_dev) -> None:
    response = _create(api, home_dev, availability="on_backorder")
    assert response.status_code == 422


# ------------------------------------------------------------- read / list


def test_a_foreign_product_is_404_and_names_nothing(api, home_dev, other_admin, realm) -> None:
    """Gate 4. The same answer a missing product gives, to the byte."""
    _create(api, home_dev, external_id="SKU-PRIVATE")

    missing = api.get("/v1/products/SKU-NEVER-EXISTED", headers=auth(home_dev)).json()["error"]
    assert missing["code"] == "not_found"
    for noun in ("product", "catalog", "sku"):
        assert noun not in missing["reason"].lower()


def test_the_list_reports_a_total_alongside_the_page(api, home_dev) -> None:
    """D10: the console renders "8 of 12" (L1316), which a cursor cannot produce."""
    for index in range(3):
        _create(api, home_dev, external_id=f"SKU-{index:04d}")

    body = api.get("/v1/products?limit=2", headers=auth(home_dev)).json()
    assert len(body["products"]) == 2
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_the_search_filter_is_named_q_as_the_prototype_names_it(api, home_dev) -> None:
    _create(api, home_dev, external_id="SKU-HW-1")
    _create(api, home_dev, external_id="SKU-TM-1", title="Softwood batten")

    body = api.get("/v1/products?q=softwood", headers=auth(home_dev)).json()
    assert [p["external_id"] for p in body["products"]] == ["SKU-TM-1"]


def test_a_page_size_beyond_the_bound_is_refused(api, home_dev) -> None:
    assert api.get("/v1/products?limit=5000", headers=auth(home_dev)).status_code == 422


# ------------------------------------------------------------- put / patch


def test_a_put_answers_201_then_200(api, home_dev) -> None:
    """A retried `PUT` has to be able to tell whether it was the call that created."""
    first = api.put("/v1/products/SKU-0001", json={"title": "Brass hinge"}, headers=auth(home_dev))
    second = api.put("/v1/products/SKU-0001", json={"title": "Brass hinge"}, headers=auth(home_dev))
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text


def test_a_put_replaces_the_fields_it_omits(api, home_dev) -> None:
    _create(api, home_dev, brand="Northgate", price="8.40")
    body = api.put(
        "/v1/products/SKU-0001", json={"title": "Brass hinge"}, headers=auth(home_dev)
    ).json()
    assert body["brand"] is None
    assert body["price"] is None


def test_a_patch_leaves_the_fields_it_omits(api, home_dev) -> None:
    _create(api, home_dev, brand="Northgate", price="8.40")
    body = api.patch(
        "/v1/products/SKU-0001", json={"title": "Brass hinge, 100mm"}, headers=auth(home_dev)
    ).json()
    assert body["title"] == "Brass hinge, 100mm"
    assert body["brand"] == "Northgate"
    assert body["price"] == "8.40"


def test_a_patch_can_clear_a_field_by_sending_null(api, home_dev) -> None:
    _create(api, home_dev, brand="Northgate")
    body = api.patch("/v1/products/SKU-0001", json={"brand": None}, headers=auth(home_dev)).json()
    assert body["brand"] is None


# ----------------------------------------------------------------- disable


def test_disabling_flips_the_serving_badge_and_explains_why(api, home_dev) -> None:
    """L683/686's wording, rendered by the server rather than assembled by the client."""
    _create(api, home_dev)
    response = api.post(
        "/v1/products/SKU-0001:disable",
        json={"reason": "Discontinued by supplier"},
        headers=auth(home_dev),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active"] is False
    assert body["eligible"] is False
    assert body["ineligibility"] == "product_inactive"
    assert body["exclusion_reason"] == "Inactive — excluded from serving"
    assert body["disabled_reason"] == "Discontinued by supplier"
    assert body["can_disable"] is False
    assert body["blocked_reason"] == "This product is already disabled."


def test_an_out_of_stock_product_says_so(api, home_dev) -> None:
    body = _create(api, home_dev, availability="out_of_stock").json()
    assert body["eligible"] is False
    assert body["exclusion_reason"] == "Out of stock — excluded from serving"
    # Still active, so the Disable action remains available.
    assert body["can_disable"] is True


def test_disabling_twice_is_a_conflict(api, home_dev) -> None:
    _create(api, home_dev)
    api.post(
        "/v1/products/SKU-0001:disable",
        json={"reason": "Discontinued by supplier"},
        headers=auth(home_dev),
    )
    again = api.post(
        "/v1/products/SKU-0001:disable",
        json={"reason": "Discontinued by supplier"},
        headers=auth(home_dev),
    )
    assert again.status_code == 409
    assert again.json()["error"]["reason"] == "This product is already disabled."


def test_a_short_reason_is_refused(api, home_dev) -> None:
    _create(api, home_dev)
    response = api.post(
        "/v1/products/SKU-0001:disable", json={"reason": "no"}, headers=auth(home_dev)
    )
    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "A reason is required for this action."


def test_disabling_a_missing_product_is_404_not_409(api, home_dev) -> None:
    """Gate 4 runs before gate 5. A 409 here would confirm the product exists."""
    response = api.post(
        "/v1/products/SKU-NOPE:disable",
        json={"reason": "Discontinued by supplier"},
        headers=auth(home_dev),
    )
    assert response.status_code == 404
