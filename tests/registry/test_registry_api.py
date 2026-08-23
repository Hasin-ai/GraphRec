"""The four registry routes over HTTP, against the real database.

What these check that the unit files cannot: that the routes are at the paths
BACKEND_PLAN §12.8 publishes, that the three-way comparison arrives assembled
rather than as three requests a client would have to reconcile, that the
`actions` block is on the wire beside every version, and that the archive
refusals arrive as `409` carrying the same sentence the disabled button carries.

The two that matter most are the last two. **Gate 4**: another tenant's version
is a `404`, because a `403` would confirm the id exists. **Gate 5**: the reason
the endpoint refuses with and the reason the console disables with are read from
the same function, and the test that proves it asserts the *same string* in both
places rather than two strings that look alike.

Sessions only. The registry is `[DEV]`/`[ADM]` and no credential scope names it,
so `CurrentTenant` refuses an API key before any of this code runs — which the
realm-separation suite already proves and this suite does not repeat.
"""

from __future__ import annotations

import uuid

import pytest

from graphrec.common.enums import ModelVersionStatus
from graphrec.common.error_copy import resolve_copy
from tests.authz.conftest import auth
from tests.registry.conftest import BASELINE, MEASURED

pytestmark = [pytest.mark.db]


# ---------------------------------------------------------------- the list


async def test_the_list_is_newest_version_first(registry, home, home_dev, seed_version) -> None:
    """L1726's table. Ordered by number, which is the column it renders."""
    for number in (1, 2, 3):
        await seed_version(home, version_number=number, status=ModelVersionStatus.RETIRED)

    response = registry.get("/v1/model-versions", headers=auth(home_dev))

    assert response.status_code == 200, response.text
    numbers = [row["version_number"] for row in response.json()["versions"]]
    assert numbers == [3, 2, 1]


async def test_a_list_row_carries_its_headline_metrics_and_its_verdict(
    registry, home, home_dev, seed_version
) -> None:
    await seed_version(home, version_number=1, status=ModelVersionStatus.ELIGIBLE)

    row = registry.get("/v1/model-versions", headers=auth(home_dev)).json()["versions"][0]

    assert row["model_type"] == "DGSR"
    assert row["metrics"]["recall_at_10"] == pytest.approx(MEASURED["recall_at_10"])
    assert row["eligible"] is True
    assert row["serving"] is False
    assert row["can_activate"] is True
    assert row["blocked_reason"] is None


async def test_the_active_version_is_the_one_marked_serving(
    registry, home, home_dev, seed_version
) -> None:
    """L1733's last column, as a boolean rather than as the em-dash."""
    await seed_version(home, version_number=1, status=ModelVersionStatus.RETIRED)
    await seed_version(home, version_number=2, status=ModelVersionStatus.ACTIVE)

    rows = registry.get("/v1/model-versions", headers=auth(home_dev)).json()["versions"]

    serving = [row["version_number"] for row in rows if row["serving"]]
    assert serving == [2]


async def test_an_active_version_cannot_be_activated_again_and_says_so_in_the_row(
    registry, home, home_dev, seed_version
) -> None:
    """Gate 5 in the list, not only on the detail page: the table draws the
    control too."""
    await seed_version(home, version_number=1, status=ModelVersionStatus.ACTIVE)

    row = registry.get("/v1/model-versions", headers=auth(home_dev)).json()["versions"][0]

    assert row["can_activate"] is False
    assert row["blocked_reason"] == resolve_copy("version_already_active")


async def test_the_list_filters_by_status(registry, home, home_dev, seed_version) -> None:
    await seed_version(home, version_number=1, status=ModelVersionStatus.REJECTED)
    await seed_version(home, version_number=2, status=ModelVersionStatus.ELIGIBLE)

    response = registry.get("/v1/model-versions?status=eligible", headers=auth(home_dev))

    versions = response.json()["versions"]
    assert [row["version_number"] for row in versions] == [2]


async def test_a_status_the_enum_does_not_have_is_a_422(registry, home_dev) -> None:
    """The filter is the seven-value lifecycle, not free text — so a typo is a
    validation failure rather than an empty table."""
    response = registry.get("/v1/model-versions?status=retiring", headers=auth(home_dev))

    assert response.status_code == 422


async def test_the_list_shows_nothing_of_another_tenants_registry(
    registry, home, away, home_dev, seed_version
) -> None:
    await seed_version(away, version_number=1, status=ModelVersionStatus.ACTIVE)
    await seed_version(home, version_number=1, status=ModelVersionStatus.ELIGIBLE)

    rows = registry.get("/v1/model-versions", headers=auth(home_dev)).json()["versions"]

    assert len(rows) == 1
    assert rows[0]["status"] == ModelVersionStatus.ELIGIBLE.value


async def test_the_registry_is_session_only(registry) -> None:
    """No token, no registry — before any handler runs."""
    assert registry.get("/v1/model-versions").status_code == 401


# ------------------------------------------------------------- the summary


async def test_the_summary_counts_the_five_cards(registry, home, home_dev, seed_version) -> None:
    """L1737. `desired` is 1 whenever there is something to serve."""
    await seed_version(home, version_number=1, status=ModelVersionStatus.RETIRED)
    await seed_version(home, version_number=2, status=ModelVersionStatus.FAILED_DEPLOYMENT)
    await seed_version(home, version_number=3, status=ModelVersionStatus.ELIGIBLE)
    await seed_version(home, version_number=4, status=ModelVersionStatus.ACTIVE)

    body = registry.get("/v1/model-versions/summary", headers=auth(home_dev)).json()

    assert body == {
        "active": 1,
        "desired": 1,
        "eligible": 1,
        "retired": 1,
        "failed_deployment": 1,
    }


async def test_an_empty_registry_desires_nothing(registry, home_dev) -> None:
    """ "Desired 1, active 0" over an empty registry would read as a fault
    rather than as a tenant who has not trained yet."""
    body = registry.get("/v1/model-versions/summary", headers=auth(home_dev)).json()

    assert body["desired"] == 0
    assert body["active"] == 0


async def test_summary_is_matched_before_the_version_id_route(
    registry, home, home_dev, seed_version
) -> None:
    """`/summary` is declared above `/{version_id}`. If that ever inverted, this
    is a `422` about a malformed UUID rather than five counts."""
    await seed_version(home, version_number=1)

    response = registry.get("/v1/model-versions/summary", headers=auth(home_dev))

    assert response.status_code == 200
    assert "active" in response.json()


# -------------------------------------------------------------- the detail


async def test_the_detail_compares_the_version_against_the_baseline(
    registry, home, home_dev, seed_version
) -> None:
    """CON-01: the popularity ranker is a floor, so the number it scored is
    beside the version's own rather than a page away."""
    version_id = await seed_version(home, version_number=1)

    body = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev)).json()

    assert body["metrics"]["recall_at_10"] == pytest.approx(MEASURED["recall_at_10"])
    assert body["baseline"]["recall_at_10"] == pytest.approx(BASELINE["recall_at_10"])
    assert body["baseline"]["coverage"] == pytest.approx(BASELINE["coverage"])


async def test_the_detail_is_a_three_way_comparison_when_something_is_serving(
    registry, home, home_dev, seed_version
) -> None:
    """XR-F-10 and UC-17: "better than popularity" and "better than what is
    serving" are two questions, and the activation decision needs both."""
    serving_scores = {**MEASURED, "recall_at_10": 0.180}
    await seed_version(
        home, version_number=1, status=ModelVersionStatus.ACTIVE, measured=serving_scores
    )
    candidate = await seed_version(home, version_number=2, status=ModelVersionStatus.ELIGIBLE)

    body = registry.get(f"/v1/model-versions/{candidate}", headers=auth(home_dev)).json()

    comparison = body["active_comparison"]
    assert comparison is not None
    assert comparison["version_number"] == 1
    assert comparison["recall_at_10"] == pytest.approx(0.180)
    assert body["metrics"]["recall_at_10"] == pytest.approx(MEASURED["recall_at_10"])


async def test_a_version_is_not_compared_against_itself(
    registry, home, home_dev, seed_version
) -> None:
    """L1756's em-dash. Four columns of zeroes would mean nothing."""
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.ACTIVE)

    body = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev)).json()

    assert body["active_comparison"] is None


async def test_nothing_serving_means_no_comparison_column(
    registry, home, home_dev, seed_version
) -> None:
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.ELIGIBLE)

    body = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev)).json()

    assert body["active_comparison"] is None


async def test_the_detail_renders_the_artifact_and_its_feature_contract(
    registry, home, home_dev, seed_version
) -> None:
    """L1758: the contract is a sentence on the page, and `jsonb` in the row."""
    version_id = await seed_version(home, version_number=1)

    artifact = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev)).json()[
        "artifact"
    ]

    assert artifact["digest"].startswith("sha256:")
    assert artifact["embedding_dim"] == 128
    assert artifact["feature_contract"] == "sequence · product · category"


async def test_the_detail_carries_all_three_gate_five_actions(
    registry, home, home_dev, seed_version
) -> None:
    """One request, three controls, each with its own reason — BUILD_PROMPT
    §gate-5 forbids a second round trip for the reason."""
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.ELIGIBLE)

    actions = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev)).json()[
        "actions"
    ]

    assert set(actions) == {"activate", "rollback", "archive"}
    assert actions["activate"] == {"allowed": True, "reason": None}
    assert actions["rollback"]["allowed"] is False
    assert actions["rollback"]["reason"] == resolve_copy("rollback_requires_target")
    # `eligible` is not archivable: the prototype's list is registered,
    # rejected, retired.
    assert actions["archive"]["allowed"] is False


async def test_a_rejected_version_keeps_its_measurements_and_its_note(
    registry, home, home_dev, seed_version
) -> None:
    """ADR 0027: rejection is a measurement a tenant can read, not a deletion."""
    version_id = await seed_version(
        home,
        version_number=1,
        status=ModelVersionStatus.REJECTED,
        measured={**MEASURED, "recall_at_10": 0.08},
        failure_note="This version scored 0.080 on recall_at_10.",
    )

    body = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev)).json()

    assert body["eligible"] is False
    assert body["failure_note"] is not None
    assert body["metrics"]["recall_at_10"] == pytest.approx(0.08)
    assert body["actions"]["archive"]["allowed"] is True


async def test_another_tenants_version_is_a_404_and_not_a_403(
    registry, away, home_dev, seed_version
) -> None:
    """Gate 4. A `403` on an id that exists is a confirmation that it exists."""
    version_id = await seed_version(away, version_number=1)

    response = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_dev))

    assert response.status_code == 404


async def test_a_version_that_never_existed_is_the_same_404(registry, home_dev) -> None:
    """The two must be indistinguishable, or the difference is the oracle."""
    response = registry.get(f"/v1/model-versions/{uuid.uuid4()}", headers=auth(home_dev))

    assert response.status_code == 404


# ------------------------------------------------------------------ archive


async def test_archiving_a_rejected_version_keeps_the_row_and_dates_it(
    registry, home, home_admin, seed_version
) -> None:
    """L1799: "retained for audit but can no longer be activated"."""
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.REJECTED)

    response = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_admin)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == ModelVersionStatus.ARCHIVED.value
    assert body["archived_at"] is not None
    assert body["metrics"]["recall_at_10"] is not None, "history stays queryable"


async def test_archiving_is_offered_to_a_developer_too(
    registry, home, home_dev, seed_version
) -> None:
    """`[DEV]`/`[ADM]`, per §12.8 — the registry is not an admin-only surface."""
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.REGISTERED)

    response = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_dev)
    )

    assert response.status_code == 200, response.text


async def test_archiving_the_active_version_is_a_409_with_the_buttons_sentence(
    registry, home, home_admin, seed_version
) -> None:
    """Gate 5, at its sharpest: the same string in both places."""
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.ACTIVE)

    detail = registry.get(f"/v1/model-versions/{version_id}", headers=auth(home_admin)).json()
    response = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_admin)
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["reason"] == detail["actions"]["archive"]["reason"]


async def test_the_retained_rollback_target_cannot_be_archived(
    registry, home, home_admin, seed_version
) -> None:
    """The phase's stated protection, over HTTP and over real rows."""
    target = await seed_version(home, version_number=1, status=ModelVersionStatus.RETIRED)
    await seed_version(home, version_number=2, status=ModelVersionStatus.ACTIVE)

    response = registry.post(
        f"/v1/model-versions/{target}:archive", json={}, headers=auth(home_admin)
    )

    assert response.status_code == 409
    assert response.json()["error"]["reason"] == resolve_copy("archive_rollback_target")


async def test_an_older_retired_version_may_be_archived(
    registry, home, home_admin, seed_version
) -> None:
    """The protection is one version deep, not all of history."""
    old = await seed_version(home, version_number=1, status=ModelVersionStatus.RETIRED)
    await seed_version(home, version_number=2, status=ModelVersionStatus.RETIRED)
    await seed_version(home, version_number=3, status=ModelVersionStatus.ACTIVE)

    response = registry.post(f"/v1/model-versions/{old}:archive", json={}, headers=auth(home_admin))

    assert response.status_code == 200, response.text


async def test_archiving_twice_is_a_409_rather_than_a_second_success(
    registry, home, home_admin, seed_version
) -> None:
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.REJECTED)
    first = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_admin)
    )
    second = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_admin)
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["reason"] == resolve_copy("archive_already_archived")


async def test_archiving_another_tenants_version_is_a_404(
    registry, away, home_admin, seed_version
) -> None:
    """Gate 4 on the write path, where the consequence of getting it wrong is
    not a disclosure but a deletion."""
    version_id = await seed_version(away, version_number=1, status=ModelVersionStatus.REJECTED)

    response = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_admin)
    )

    assert response.status_code == 404


async def test_an_archived_version_is_no_longer_activatable(
    registry, home, home_admin, seed_version
) -> None:
    """The point of the state, per L1799."""
    version_id = await seed_version(home, version_number=1, status=ModelVersionStatus.REJECTED)

    body = registry.post(
        f"/v1/model-versions/{version_id}:archive", json={}, headers=auth(home_admin)
    ).json()

    assert body["actions"]["activate"]["allowed"] is False
    assert body["actions"]["archive"]["allowed"] is False
