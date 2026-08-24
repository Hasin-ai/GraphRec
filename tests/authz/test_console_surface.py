"""The console-only endpoints, and the fields the console cannot render without.

BUILD_PROMPT §10.9 names seven endpoints that exist because a console needs them
and an integration does not, and one field — `is_last_active_administrator` —
that exists because a button has to be disabled *before* it is pressed. Both are
easy to get subtly wrong in a way no other suite would catch: the endpoints have
no integration caller to notice, and the field is only wrong at the moment it
matters, which is the moment a tenant is one click from having no administrator.

Every test here builds its own tenant. These are the mutating paths — a password
change, a role change, an invitation reissue — and running them against the
shared `realm` would change what later tests sign in with.
"""

from __future__ import annotations

import uuid

import pytest

from tests.authz.conftest import PASSWORD, auth

pytestmark = [pytest.mark.authz, pytest.mark.db]

NEW_PASSWORD = "a-replacement-passphrase-of-adequate-length"


@pytest.fixture(scope="module")
def home(fresh_tenant) -> dict:
    return fresh_tenant("cna")


@pytest.fixture(scope="module")
def foreign(fresh_tenant) -> dict:
    """A second tenant, only ever used as a source of identifiers that must 404."""
    return fresh_tenant("cnb")


def _invite(api, token: str, *, role: str = "tenant_developer") -> dict:
    email = f"console-{uuid.uuid4().hex[:10]}@example.com"
    response = api.post(
        "/v1/users",
        headers=auth(token),
        json={"email": email, "display_name": "Invitee", "role": role},
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()
    body["email"] = email
    return body


# --------------------------------------------------------------- onboarding


def test_onboarding_returns_every_step_including_somebody_else_s(api, home) -> None:
    """A developer sees the administrator's steps, marked as not theirs.

    The alternative — filtering the list by role — would show a developer a
    complete-looking checklist and an integration that returns nothing, because
    the step blocking them is one they cannot see.
    """
    body = api.get("/v1/onboarding", headers=auth(home["dev_token"])).json()

    assert body["total"] == len(body["steps"]) == 8
    users_step = next(step for step in body["steps"] if step["key"] == "configure_users")
    assert users_step["required_role"] == "tenant_administrator"
    assert users_step["permitted"] is False
    assert users_step["route"] == "/users"

    # Same list, same completion, different permission. The checklist is a fact
    # about the tenant; only `permitted` is a fact about the caller.
    as_admin = api.get("/v1/onboarding", headers=auth(home["admin_token"])).json()
    assert [step["key"] for step in as_admin["steps"]] == [step["key"] for step in body["steps"]]
    assert [step["complete"] for step in as_admin["steps"]] == [
        step["complete"] for step in body["steps"]
    ]
    assert next(step for step in as_admin["steps"] if step["key"] == "configure_users")["permitted"]


def test_a_step_completes_only_when_its_own_thing_exists(api, fresh_tenant) -> None:
    """Creating a credential ticks the credential step and nothing else.

    This is the property the service docstring claims and the one a refactor
    would quietly lose: steps are eight independent existence questions, not a
    progress bar where reaching step 3 implies steps 1 and 2.
    """
    tenant = fresh_tenant("cnc")
    before = api.get("/v1/onboarding", headers=auth(tenant["admin_token"])).json()

    issued = api.post(
        "/v1/api-keys",
        headers=auth(tenant["admin_token"]),
        json={"name": "checklist", "scopes": ["events:write"], "expires_in_days": 90},
    )
    assert issued.status_code == 201, issued.text

    after = api.get("/v1/onboarding", headers=auth(tenant["admin_token"])).json()
    changed = {
        step["key"]
        for before_step, step in zip(before["steps"], after["steps"], strict=True)
        if before_step["complete"] != step["complete"]
    }
    assert changed == {"create_credential"}
    assert after["completed"] == before["completed"] + 1


def test_onboarding_counts_agree_with_the_steps_they_summarise(api, home) -> None:
    """`completed` and `total` are computed server-side; they must not drift."""
    body = api.get("/v1/onboarding", headers=auth(home["admin_token"])).json()
    assert body["completed"] == sum(1 for step in body["steps"] if step["complete"])
    assert body["total"] == len(body["steps"])


# ------------------------------------------------------------ GET /users/{id}


def test_reading_one_user_answers_the_same_as_the_list_does(api, home) -> None:
    listed = api.get("/v1/users", headers=auth(home["admin_token"])).json()
    target = next(user for user in listed["users"] if user["role"] == "tenant_developer")

    response = api.get(f"/v1/users/{target['tenant_user_id']}", headers=auth(home["admin_token"]))

    assert response.status_code == 200
    assert response.json() == target
    # Neither the digest nor the tenant belongs in a response about a person.
    assert "credential_digest" not in response.json()
    assert "tenant_id" not in response.json()


def test_a_developer_may_read_a_colleague(api, home) -> None:
    """Read is open to both roles. Seeing who else is in your own tenant is not
    a leak, and a developer who cannot see the administrator cannot be told who
    to ask for the thing they are blocked on."""
    listed = api.get("/v1/users", headers=auth(home["dev_token"])).json()
    target = listed["users"][0]["tenant_user_id"]

    assert api.get(f"/v1/users/{target}", headers=auth(home["dev_token"])).status_code == 200


def test_another_tenant_s_user_is_not_found_rather_than_forbidden(api, home, foreign) -> None:
    """Gate 4. 403 would confirm the identifier names somebody real."""
    theirs = api.get("/v1/users", headers=auth(foreign["admin_token"])).json()["users"][0]

    response = api.get(f"/v1/users/{theirs['tenant_user_id']}", headers=auth(home["admin_token"]))
    invented = api.get(f"/v1/users/{uuid.uuid4()}", headers=auth(home["admin_token"]))

    assert response.status_code == invented.status_code == 404
    assert response.json()["error"]["code"] == invented.json()["error"]["code"]
    assert theirs["email"] not in response.text


# ------------------------------------------- is_last_active_administrator


def test_the_only_administrator_is_flagged_and_the_developer_is_not(api, home) -> None:
    users = api.get("/v1/users", headers=auth(home["admin_token"])).json()["users"]
    by_role = {user["role"]: user for user in users}

    assert by_role["tenant_administrator"]["is_last_active_administrator"] is True
    assert by_role["tenant_developer"]["is_last_active_administrator"] is False


def test_the_flag_clears_once_a_second_administrator_is_active(api, fresh_tenant) -> None:
    """Promoting the developer is the console's own remedy for the disabled button.

    The flag has to clear on the *count of active administrators*, not on
    "somebody else holds the role" — an invited or disabled administrator is not
    holding the tenant open, and if this read `role` alone the console would
    offer a demotion the server then refuses, which is the console-and-server
    disagreement §10.4 names.
    """
    tenant = fresh_tenant("cnd")
    users = api.get("/v1/users", headers=auth(tenant["admin_token"])).json()["users"]
    developer = next(user for user in users if user["role"] == "tenant_developer")

    # An *invited* administrator does not count: nobody has accepted yet.
    invited = _invite(api, tenant["admin_token"], role="tenant_administrator")
    assert invited["user"]["status"] == "invited"
    still = api.get("/v1/users", headers=auth(tenant["admin_token"])).json()["users"]
    assert next(
        u for u in still if u["role"] == "tenant_administrator" and u["status"] == "active"
    )["is_last_active_administrator"]

    promoted = api.patch(
        f"/v1/users/{developer['tenant_user_id']}/role",
        headers=auth(tenant["admin_token"]),
        json={"role": "tenant_administrator"},
    )
    assert promoted.status_code == 200, promoted.text

    after = api.get("/v1/users", headers=auth(tenant["admin_token"])).json()["users"]
    actives = [u for u in after if u["role"] == "tenant_administrator" and u["status"] == "active"]
    assert len(actives) == 2
    assert not any(user["is_last_active_administrator"] for user in actives)


def test_the_flag_and_the_refusal_are_the_same_condition(api, fresh_tenant) -> None:
    """The disabled button and the 409 behind it must agree.

    A flag computed one way and a refusal computed another is a button that is
    enabled and does not work, or disabled and would have.
    """
    tenant = fresh_tenant("cne")
    users = api.get("/v1/users", headers=auth(tenant["admin_token"])).json()["users"]
    administrator = next(u for u in users if u["role"] == "tenant_administrator")
    assert administrator["is_last_active_administrator"] is True

    refused = api.patch(
        f"/v1/users/{administrator['tenant_user_id']}/role",
        headers=auth(tenant["admin_token"]),
        json={"role": "tenant_developer"},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "last_active_administrator"


# ------------------------------------------------------- resend-invitation


def test_resending_issues_a_new_token_and_retires_the_old_one(api, fresh_tenant) -> None:
    """ "Resend" is necessarily "reissue": the first token was never stored.

    Retiring the old one is the part worth pinning. An administrator who resends
    believes the previous link is dead, and a link that still opens the account
    is one sitting in whichever chat log the first attempt was pasted into.
    """
    tenant = fresh_tenant("cnf")
    invited = _invite(api, tenant["admin_token"])

    reissued = api.post(
        f"/v1/users/{invited['user']['tenant_user_id']}:resend-invitation",
        headers=auth(tenant["admin_token"]),
    )
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["invitation_token"] != invited["invitation_token"]

    stale = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "invitation_invalid"

    accepted = api.post(
        "/v1/invitations:accept",
        json={
            "token": reissued.json()["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "active"


def test_resending_to_somebody_already_active_is_refused(api, home) -> None:
    """Otherwise this mints a password-setting token for a live account, which
    is account takeover with an administrator's signature on it."""
    users = api.get("/v1/users", headers=auth(home["admin_token"])).json()["users"]
    active = next(user for user in users if user["status"] == "active")

    response = api.post(
        f"/v1/users/{active['tenant_user_id']}:resend-invitation",
        headers=auth(home["admin_token"]),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_not_invited"


def test_only_an_administrator_may_resend(api, home) -> None:
    invited = _invite(api, home["admin_token"])

    response = api.post(
        f"/v1/users/{invited['user']['tenant_user_id']}:resend-invitation",
        headers=auth(home["dev_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


# ---------------------------------------------------------------- PATCH /me


def test_a_user_may_rename_themselves_and_nothing_else(api, fresh_tenant) -> None:
    tenant = fresh_tenant("cng")
    before = api.get("/v1/me", headers=auth(tenant["dev_token"])).json()

    response = api.patch(
        "/v1/me", headers=auth(tenant["dev_token"]), json={"display_name": "  Renamed  "}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "Renamed"
    assert body["role"] == before["role"]
    assert body["status"] == before["status"]
    assert body["email"] == before["email"]
    assert body["tenant_user_id"] == before["tenant_user_id"]


def test_a_blank_display_name_is_refused(api, home) -> None:
    """Refused at the boundary rather than in the service.

    `_Body` strips whitespace and the field is `min_length=1`, so "   " never
    reaches `update_own_profile` — its own `display_name_required` check is the
    second line of the same defence and stays there for the direct caller of the
    service. What the test pins is that the refusal names the field, because an
    unnamed 422 leaves the console with nothing to put under the input.
    """
    response = api.patch("/v1/me", headers=auth(home["dev_token"]), json={"display_name": "   "})

    assert response.status_code == 422
    body = response.json()["error"]
    assert "display_name" in {field["field"] for field in body["field_errors"]}


def test_patching_me_cannot_reach_another_user(api, home) -> None:
    """There is no `{tenant_user_id}` in this path and there must not be. A field
    that named one would be a second way to edit somebody else, sitting beside
    `/users` which is gate-3 protected — and only one of the two is checked."""
    users = api.get("/v1/users", headers=auth(home["admin_token"])).json()["users"]
    other = next(user for user in users if user["role"] == "tenant_administrator")

    response = api.patch(
        "/v1/me",
        headers=auth(home["dev_token"]),
        json={"display_name": "Hijacked", "tenant_user_id": str(other["tenant_user_id"])},
    )

    assert response.status_code == 422
    assert (
        api.get(f"/v1/users/{other['tenant_user_id']}", headers=auth(home["admin_token"])).json()[
            "display_name"
        ]
        != "Hijacked"
    )


# ------------------------------------------------------ change-password


def test_changing_a_password_requires_the_current_one(api, home) -> None:
    """A session proves the account was open on this device once. It does not
    prove who is at the keyboard now."""
    response = api.post(
        "/v1/me:change-password",
        headers=auth(home["dev_token"]),
        json={
            "current_password": "not-the-current-passphrase",
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "current_password_invalid"
    assert {field["field"] for field in response.json()["error"]["field_errors"]} == {
        "current_password"
    }


def test_a_mistyped_confirmation_is_caught_before_the_current_password(api, home) -> None:
    """Order matters: the comparison discloses nothing, so checking it first
    costs nothing, and checking it last spends a verification attempt on a typo."""
    response = api.post(
        "/v1/me:change-password",
        headers=auth(home["dev_token"]),
        json={
            "current_password": "also-not-the-current-passphrase",
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD + "-typo",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "password_confirmation_mismatch"


def test_a_changed_password_replaces_the_old_one(api, fresh_tenant) -> None:
    tenant = fresh_tenant("cnh")
    response = api.post(
        "/v1/me:change-password",
        headers=auth(tenant["dev_token"]),
        json={
            "current_password": PASSWORD,
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text

    def sign_in(password: str):
        return api.post(
            "/v1/auth/sign-in",
            json={
                "tenant_code": tenant["code"],
                "email": tenant["dev_email"],
                "password": password,
            },
        )

    assert sign_in(PASSWORD).status_code == 401
    assert sign_in(NEW_PASSWORD).status_code == 200


def test_keep_session_spares_the_tab_the_change_was_made_in(api, fresh_tenant) -> None:
    """Every other refresh session is revoked; the named one survives.

    Revoking all of them signs the user out of the tab they are typing in, which
    teaches people that the button is broken. Revoking none leaves a thief signed
    in, which is what the change was for.
    """
    tenant = fresh_tenant("cni")

    def sign_in() -> dict:
        response = api.post(
            "/v1/auth/sign-in",
            json={
                "tenant_code": tenant["code"],
                "email": tenant["dev_email"],
                "password": PASSWORD,
            },
        )
        assert response.status_code == 200, response.text
        body: dict = response.json()
        return body

    keeping = sign_in()
    elsewhere = sign_in()

    changed = api.post(
        "/v1/me:change-password",
        headers=auth(keeping["access_token"]),
        json={
            "current_password": PASSWORD,
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
            "keep_session": keeping["refresh_token"],
        },
    )
    assert changed.status_code == 200, changed.text

    assert (
        api.post("/v1/auth/refresh", json={"refresh_token": keeping["refresh_token"]}).status_code
        == 200
    )
    assert (
        api.post("/v1/auth/refresh", json={"refresh_token": elsewhere["refresh_token"]}).status_code
        == 401
    )


# ------------------------------------------------------------------ totals


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("/v1/users", "users"),
        ("/v1/api-keys", "credentials"),
        ("/v1/training-jobs", "jobs"),
        ("/v1/model-versions", "versions"),
    ],
)
def test_every_console_list_reports_a_total(api, home, path, key) -> None:
    """§10.9 requires every table to render "N of M", so `total` is present even
    on the lists that are not paginated. A list that grows a `limit` later should
    not also have to grow a field — and a console reading `data.length` instead
    would then silently start saying "20 of 20" about a hundred rows."""
    body = api.get(path, headers=auth(home["admin_token"])).json()

    assert isinstance(body["total"], int)
    assert body["total"] >= len(body[key])


def test_a_total_counts_what_was_created(api, fresh_tenant) -> None:
    tenant = fresh_tenant("cnj")
    assert api.get("/v1/api-keys", headers=auth(tenant["admin_token"])).json()["total"] == 0

    for name in ("first", "second"):
        created = api.post(
            "/v1/api-keys",
            headers=auth(tenant["admin_token"]),
            json={"name": name, "scopes": ["events:write"], "expires_in_days": 90},
        )
        assert created.status_code == 201, created.text

    body = api.get("/v1/api-keys", headers=auth(tenant["admin_token"])).json()
    assert body["total"] == len(body["credentials"]) == 2
