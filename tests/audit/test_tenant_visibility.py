"""The exit criterion, asserted directly: a tenant's audit page shows a tenant
its own history and nothing else.

"Nothing else" has three distinct meanings, and each is defeated by a different
mistake, so each gets its own test:

* **No other tenant's rows.** Defeated by a missing RLS policy, or by a handler
  that grew its own `WHERE` and got it subtly wrong.
* **No unattributable rows.** A sign-in refused for an address that belongs to
  no tenant is recorded with `tenant_id IS NULL` — visible to the platform,
  invisible here, because `NULL = <tenant>` is not true. Defeated by a policy
  written with `IS NOT DISTINCT FROM`.
* **No columns the tenant is not owed.** `actor_id`, `details`, `tenant_id` and
  `correlation_ref` exist on the row and are absent from the response.
  Defeated by a serialiser widened to "just return the model".

The rows are seeded through SQL rather than by driving eight endpoints. What is
under test is the *read* — the policy, the projection and the gate — and seeding
through the writer would make a failure ambiguous between the two.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

TENANT_FIELDS = {"occurred_at", "actor_type", "action", "resource_type", "resource_ref", "outcome"}


def _write(engine, *, tenant_id, reference: str, actor_type: str = "tenant_user") -> None:
    """One audit row, written as the role that writes them in production."""
    with engine.connect() as conn, conn.begin():
        if tenant_id is not None:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
        conn.execute(
            sa.text(
                "INSERT INTO audit_logs (tenant_id, occurred_at, actor_type, actor_id, action, "
                "resource_type, resource_ref, outcome, details) "
                "VALUES (:tid, now(), :actor_type, :actor_id, 'credential', 'api_key', :ref, "
                "'succeeded', '{\"secret\": \"never-rendered\"}'::jsonb)"
            ),
            {
                "tid": tenant_id,
                "actor_type": actor_type,
                "actor_id": str(uuid.uuid4()),
                "ref": reference,
            },
        )


@pytest.fixture
def three_rows(audit_app_engine, audited_tenants) -> dict[str, str]:
    """One row for the caller, one for a stranger, one attributable to nobody."""
    references = {kind: uuid.uuid4().hex[:12] for kind in ("mine", "theirs", "nobody")}
    _write(
        audit_app_engine,
        tenant_id=audited_tenants["left"]["tenant_id"],
        reference=references["mine"],
    )
    _write(
        audit_app_engine,
        tenant_id=audited_tenants["right"]["tenant_id"],
        reference=references["theirs"],
    )
    _write(audit_app_engine, tenant_id=None, reference=references["nobody"])
    return references


def test_a_tenants_audit_page_shows_its_own_rows(audit_api, left_admin, three_rows) -> None:
    response = audit_api.get(
        "/v1/audit-logs", headers={"Authorization": f"Bearer {left_admin}"}, params={"limit": 200}
    )
    assert response.status_code == 200, response.text
    references = {entry["resource_ref"] for entry in response.json()["entries"]}
    assert three_rows["mine"] in references


def test_a_tenants_audit_page_never_shows_another_tenants_row(
    audit_api, left_admin, three_rows
) -> None:
    """The row exists, was written a moment ago, and is not on this page."""
    response = audit_api.get(
        "/v1/audit-logs", headers={"Authorization": f"Bearer {left_admin}"}, params={"limit": 200}
    )
    references = {entry["resource_ref"] for entry in response.json()["entries"]}
    assert three_rows["theirs"] not in references


def test_a_tenants_audit_page_never_shows_an_unattributed_row(
    audit_api, left_admin, three_rows
) -> None:
    """`tenant_id IS NULL` is how a refusal by a stranger is recorded.

    Showing it here would tell a tenant that someone, somewhere, tried something
    — which is a fact about the installation, not about them.
    """
    response = audit_api.get(
        "/v1/audit-logs", headers={"Authorization": f"Bearer {left_admin}"}, params={"limit": 200}
    )
    references = {entry["resource_ref"] for entry in response.json()["entries"]}
    assert three_rows["nobody"] not in references


def test_the_response_carries_six_fields_and_no_actor_identity(
    audit_api, left_admin, three_rows
) -> None:
    """Redaction is a property of the projection, so assert the exact key set.

    An inequality — "does not contain actor_id" — passes for a response that has
    grown `details` instead. The whole set is the assertion.
    """
    response = audit_api.get(
        "/v1/audit-logs", headers={"Authorization": f"Bearer {left_admin}"}, params={"limit": 200}
    )
    entries = response.json()["entries"]
    assert entries, "seeded a row and the page was empty"
    for entry in entries:
        assert set(entry) == TENANT_FIELDS
    assert "never-rendered" not in response.text


def test_the_total_accompanies_the_page(audit_api, left_admin, three_rows) -> None:
    """D10: limit/offset *with a total*, because the table renders "20 of 143"."""
    response = audit_api.get(
        "/v1/audit-logs", headers={"Authorization": f"Bearer {left_admin}"}, params={"limit": 1}
    )
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["total"] >= 1
    assert body["limit"] == 1
    assert body["offset"] == 0


def test_an_unauthenticated_caller_is_refused(audit_api) -> None:
    assert audit_api.get("/v1/audit-logs").status_code == 401


def test_a_developer_is_refused_the_audit_page(audit_api, left_developer) -> None:
    """`[Admin]` in the route table (L1420). A developer integrates; an
    administrator accounts, and the history is an accounting artefact."""
    response = audit_api.get(
        "/v1/audit-logs", headers={"Authorization": f"Bearer {left_developer}"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"
