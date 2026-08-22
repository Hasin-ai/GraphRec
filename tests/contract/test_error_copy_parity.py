"""Error-copy parity with the console prototype.

BUILD_PROMPT §9 designates the prototype's ~40 user-facing strings approved
product copy, to be returned as `error.reason` rather than paraphrased. These
tests assert the catalogue still says what the prototype says, at the cited
lines, byte for byte — including its curly quotation marks.

The test is deliberately strict. A "harmless" rewording is exactly the drift
this guards: the console pre-validates against the same catalogue, so a divergence
means the two surfaces tell a tenant different things about the same failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graphrec.common.error_copy import ERROR_COPY, FIELD_ERROR_COPY, resolve_copy

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "Design system decision pending" / "GraphRec Console.dc.html"

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def prototype_lines() -> list[str]:
    return PROTOTYPE.read_text(encoding="utf-8").splitlines()


#: (error code, the line the string appears on, the exact expected text).
#: Line numbers are those cited in BUILD_PROMPT §9.
VERBATIM_AT_LINE: list[tuple[str, int, str]] = [
    (
        "invalid_credentials",
        1572,
        "The credentials supplied are not valid, or the account cannot sign in. "
        "If the problem continues, contact your tenant administrator.",
    ),
    (
        "user_already_exists",
        1235,
        "A user with this email already exists in this tenant. "
        "Email is unique per tenant, so this is a conflict rather than a validation error.",
    ),
    (
        "last_active_administrator",
        1244,
        "The last active administrator cannot be demoted or disabled.",
    ),
    (
        "credential_requires_scope",
        1137,
        "Select at least one integration operation. "
        "A credential with no scope cannot authorize anything.",
    ),
    ("credential_revoked", 1118, "Revoked credentials cannot be rotated."),
    ("product_already_disabled", 1331, "This product is already disabled."),
    (
        "sync_id_required",
        1611,
        "A synchronization identifier is required so a repeated submission is not applied twice.",
    ),
    ("event_id_required", 1621, "An event identifier is required — it is the idempotency key."),
    ("batch_id_required", 1626, "A batch identifier is required."),
    ("event_identifiers_required", 1623, "Customer and product identifiers are required."),
    (
        "training_request_ref_required",
        1681,
        "A request identifier is required so a repeated request is not applied twice.",
    ),
    ("job_not_cancellable", 1706, "Only a job in an active state can be cancelled."),
    ("version_already_active", 1768, "This version is already active."),
    ("version_not_eligible", 1733, "Only an eligible version can be activated."),
    (
        "rollback_requires_target",
        1769,
        "Roll back applies to the active version, and requires a retained target.",
    ),
    ("rollback_no_target", 1791, "No retained version is available as a roll-back target."),
    ("archive_active_version", 1749, "An active version cannot be archived."),
    ("archive_already_archived", 1749, "Already archived."),
    ("archive_rollback_target", 1749, "Retained as the rollback target for the active version."),
    (
        "negative_limit",
        1635,
        "A negative limit conflicts with the quota model. "
        "Enter zero to withhold a usage type entirely.",
    ),
    ("plan_already_closed", 1496, "This plan is already closed."),
    ("plan_code_required", 1485, "A plan code is required."),
    ("reason_required", 1342, "A reason is required for this action."),
    ("reason_required_audited", 1420, "A reason is required and is written to the audit history."),
    ("user_already_disabled", 1249, "A disabled user is already unable to authenticate."),
    (
        "insufficient_role",
        1063,
        "Your role or named permission does not include this operation. "
        "There is nothing to retry here.",
    ),
    (
        "not_found",
        1064,
        "A resource belonging to another tenant is indistinguishable "
        "from one that does not exist.",
    ),
    (
        "internal_error",
        1065,
        "The request could not be completed. "
        "Quote the reference below if you contact platform support.",
    ),
    (
        "product_concurrent_change",
        1335,
        "A concurrent change to the same product is reported as a state conflict; "
        "your entries are kept so you can reconcile them.",
    ),
    (
        "invalid_platform_credentials",
        1577,
        "The credentials supplied are not valid, or the operator account cannot sign in.",
    ),
    (
        "recovery_token_invalid",
        1592,
        "It has expired or is not valid. Request a new one and try again.",
    ),
    (
        "password_confirmation_mismatch",
        1597,
        "The new authentication material and its confirmation do not match.",
    ),
    (
        "tenant_not_active",
        1059,
        "The transition is controlled by a Platform Administrator; "
        "there is no tenant-side action that changes it.",
    ),
]


@pytest.mark.parametrize(
    ("code", "line_number", "expected"),
    VERBATIM_AT_LINE,
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_copy_is_verbatim_and_still_at_the_cited_line(
    prototype_lines: list[str], code: str, line_number: int, expected: str
) -> None:
    assert ERROR_COPY[code] == expected, f"catalogue text for {code!r} drifted from the prototype"

    line = prototype_lines[line_number - 1]
    assert expected in line, (
        f"{code!r} is documented as appearing at dc.html L{line_number}, "
        f"but that line no longer contains the string. The prototype is the "
        f"specification: reconcile the catalogue with it."
    )


#: Copy that interpolates a bound. The template is checked against the
#: prototype's rendered form with the seeded values substituted.
TEMPLATED_AT_LINE: list[tuple[str, int, dict[str, object], str]] = [
    (
        "tenant_name_already_registered",
        1582,
        {"business_name": "Kelder Tools"},
        "A tenant account named “Kelder Tools” already exists. "
        "Sign in with the existing administrator account, "
        "or register under a different business name.",
    ),
    (
        "product_quota_exhausted",
        1603,
        {"used": "50,000", "limit": "50,000", "plan_code": "GROWTH"},
        "This tenant holds 50,000 of 50,000 products on plan GROWTH. "
        "Disable products you no longer sell, "
        "or ask your platform contact about a quota override.",
    ),
    (
        "product_sync_oversize",
        1612,
        {"limit": 5000},
        "A synchronization is bounded to 5,000 products. "
        "Split the collection and submit it in parts.",
    ),
    (
        "event_batch_oversize",
        1627,
        {"limit": 5000},
        "A batch is bounded to 5,000 events. Split the collection and submit it in parts.",
    ),
    (
        "training_already_running",
        1646,
        {"job_id": "job-2292", "concurrency": 1},
        "Job job-2292 is already running. Global training concurrency is 1.",
    ),
    (
        "training_insufficient_data",
        697,
        {"minimum": 1000},
        "Dataset snapshot held fewer than 1,000 eligible interaction sequences.",
    ),
    (
        "plan_closed",
        1454,
        {"plan_code": "SCALE"},
        "Plan SCALE is closed to new assignments. Reopen the plan or choose another.",
    ),
]


@pytest.mark.parametrize(("code", "line_number", "args", "expected"), TEMPLATED_AT_LINE)
def test_templated_copy_renders_what_the_prototype_shows(
    prototype_lines: list[str], code: str, line_number: int, args: dict[str, object], expected: str
) -> None:
    """A bound is interpolated from settings, and must still read identically.

    `training_already_running` is the case that matters most: the concurrency in
    the sentence comes from TRAINING_GLOBAL_CONCURRENCY, so a change to the
    setting changes the message rather than leaving it stating a stale number.
    """
    assert resolve_copy(code, **args) == expected

    # The prototype concatenates around its own values ('Plan '+pl.id+' is
    # closed...'), so the rendered sentence never appears there literally.
    # Compare the template's fixed segments instead: those are the words that
    # must not drift, and they survive interpolation on both sides.
    import string

    line = prototype_lines[line_number - 1]
    segments = [
        literal.strip()
        for literal, _, _, _ in string.Formatter().parse(ERROR_COPY[code])
        if literal and len(literal.strip()) > 12
    ]
    assert segments, f"{code!r} has no fixed segment long enough to verify"
    missing = [segment for segment in segments if segment not in line]
    assert (
        not missing
    ), f"{code!r} cites dc.html L{line_number}, which no longer contains {missing!r}"


def test_every_code_resolves() -> None:
    """No entry is an unformattable template with no arguments supplied."""
    import string

    for code, template in ERROR_COPY.items():
        fields = {f for _, f, _, _ in string.Formatter().parse(template) if f}
        if fields:
            continue  # covered by the templated cases above
        assert resolve_copy(code) == template, f"{code} did not resolve cleanly"


def test_missing_copy_is_fatal_rather_than_a_generic_fallback() -> None:
    """An unreviewed sentence must never reach a tenant."""
    from graphrec.common.error_copy import MissingErrorCopy

    with pytest.raises(MissingErrorCopy):
        resolve_copy("a_code_that_was_never_given_approved_copy")


def test_not_found_copy_never_names_a_resource_type() -> None:
    """Gate 4 — a foreign resource and a missing one are indistinguishable."""
    reason = ERROR_COPY["not_found"].lower()
    for noun in (
        "product",
        "model",
        "version",
        "job",
        "credential",
        "user",
        "submission",
        "plan",
        "tenant account",
    ):
        assert noun not in reason, f"the 404 reason names {noun!r}, which confirms existence"


def test_sign_in_failure_does_not_reveal_whether_an_account_exists() -> None:
    """L1022 — invalid, inactive and rate-limited attempts return one message."""
    reason = ERROR_COPY["invalid_credentials"].lower()
    for leak in ("no such", "not found", "unknown email", "incorrect password", "does not exist"):
        assert leak not in reason


def test_field_copy_is_verbatim(prototype_lines: list[str]) -> None:
    expected = {
        "product_already_exists": (1604, "Already exists in this tenant."),
        "tenant_name_already_registered": (1582, "Business name already registered."),
        "negative_limit": (1635, "Must be zero or greater."),
        "business_name_required": (1581, "A business name is required."),
        "external_id_required": (1602, "An external product identifier is required."),
        "title_required": (1605, "A title is required."),
        "email_required": (1234, "An email is required — it is the account identifier."),
        "confirmation_mismatch": (1593, "The two entries do not match."),
        "current_material_required": (1598, "Required to make this change."),
    }
    for code, (line_number, text) in expected.items():
        assert FIELD_ERROR_COPY[code] == text
        assert (
            text in prototype_lines[line_number - 1]
        ), f"field copy {code!r} cites L{line_number}, which no longer contains it"
