"""The composed tenant detail: three sections, three permissions, one status code.

This is the half of the phase's exit criterion that is easy to get wrong in a
way nobody notices, because the wrong behaviour looks responsible. An operator
holding `platform` but not `plan_management` opens a tenant; the obvious
implementation checks the permission, finds it missing, and returns `403`. The
page then shows nothing at all — including the status section they *are*
entitled to — and the operator learns that they are not allowed to look at this
tenant, which is false.

L1436 asks for the other behaviour: `200`, with the sections they hold, and each
withheld section replaced by a sentence saying which permission it needs. So the
authorization decision is rendered *inside* the page rather than instead of it.

Two properties are asserted throughout, and they are separable:

* the withheld section carries no `data` — not an empty object, not zeros, which
  would be indistinguishable from a tenant who has used nothing;
* the withheld section carries a `reason` from the copy catalogue, so the
  console never composes its own explanation of an authorization decision.
"""

from __future__ import annotations

import pytest

from graphrec.common.error_copy import WITHHELD_SECTION_COPY
from tests.platform.conftest import auth

#: The three sections, and the permission each is gated on. `status` has no
#: entry because it is gated on the same permission as the route itself: an
#: operator who can open the page can always see whether the tenant is running.
SECTION_PERMISSION = {"plan": "plan_management", "usage": "platform_scope"}


def _detail(api, token, tenant_id):
    response = api.get(f"/v1/platform/tenants/{tenant_id}", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def test_an_operator_holding_everything_sees_all_three_sections(
    platform_api, full_operator, estate
) -> None:
    body = _detail(platform_api, full_operator, estate["tenants"]["acme"]["tenant_id"])
    sections = body["sections"]
    assert set(sections) == {"status", "plan", "usage"}
    for name, section in sections.items():
        assert section["granted"], name
        assert section["data"] is not None, name
        assert section["reason"] is None, name


@pytest.mark.parametrize("withheld", sorted(SECTION_PERMISSION))
def test_a_partially_permitted_operator_gets_the_page_with_that_section_withheld(
    platform_api, operator, estate, withheld
) -> None:
    """The status code is 200. That is the assertion this test exists for."""
    held = [name for name in SECTION_PERMISSION.values() if name != SECTION_PERMISSION[withheld]]
    token = operator("platform", *held)
    body = _detail(platform_api, token, estate["tenants"]["acme"]["tenant_id"])

    absent = body["sections"][withheld]
    assert absent["granted"] is False
    assert absent["data"] is None, "a withheld section leaked its data"
    assert absent["reason"] == WITHHELD_SECTION_COPY[SECTION_PERMISSION[withheld]]

    # And everything they do hold still arrived.
    assert body["sections"]["status"]["granted"] is True
    for name in SECTION_PERMISSION:
        if name != withheld:
            assert body["sections"][name]["granted"] is True, name


def test_an_operator_holding_only_the_base_permission_still_gets_a_page(
    platform_api, operator, estate
) -> None:
    """The minimal case, and the one a `403` would have swallowed entirely."""
    token = operator("platform")
    body = _detail(platform_api, token, estate["tenants"]["acme"]["tenant_id"])

    assert body["tenant"]["tenant_code"] == estate["tenants"]["acme"]["code"]
    assert body["sections"]["status"]["granted"] is True
    assert body["sections"]["status"]["data"]["status"] == "active"
    for name in SECTION_PERMISSION:
        assert body["sections"][name]["granted"] is False
        assert body["sections"][name]["data"] is None


def test_the_withheld_reason_names_the_permission_rather_than_the_data(
    platform_api, operator, estate
) -> None:
    """A reason that described what was hidden would defeat hiding it.

    "This tenant is over its event limit — sign in with plan-management to see
    by how much" tells the operator the thing the permission exists to gate.
    """
    token = operator("platform")
    body = _detail(platform_api, token, estate["tenants"]["acme"]["tenant_id"])
    reason = body["sections"]["usage"]["reason"]
    assert "permission" in reason or "scope" in reason
    assert estate["tenants"]["acme"]["code"] not in reason


def test_an_operator_without_the_platform_permission_is_refused_the_route(
    platform_api, operator, estate
) -> None:
    """Composition applies to sections, not to the route.

    Someone holding only `audit` has no business on a tenant page at all, and
    receives a 403 rather than a page of three withheld sections — which would
    be a page confirming that the tenant exists.
    """
    token = operator("audit")
    response = platform_api.get(
        f"/v1/platform/tenants/{estate['tenants']['acme']['tenant_id']}", headers=auth(token)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_an_unknown_tenant_is_a_404_even_for_an_operator_holding_everything(
    platform_api, full_operator
) -> None:
    import uuid

    response = platform_api.get(f"/v1/platform/tenants/{uuid.uuid4()}", headers=auth(full_operator))
    assert response.status_code == 404
