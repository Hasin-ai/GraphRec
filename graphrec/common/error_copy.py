"""Approved user-facing copy, keyed by `error.code`.

Every string here is transcribed **verbatim** from the console prototype
(`Design system decision pending/GraphRec Console.dc.html`), which BUILD_PROMPT
§0 designates an executable specification. The cited line number is where the
string appears. Curly quotation marks are deliberate and must be preserved —
tests compare these strings against the prototype byte for byte.

Do not paraphrase an entry. Do not "fix" its punctuation. If a string needs to
change, it changes in the prototype first.

Placeholders use `str.format` fields, so a message that quotes a bound draws the
bound from settings rather than repeating a literal (BUILD_PROMPT §13.22).
"""

from __future__ import annotations

from typing import Any

#: code -> approved copy. Entries marked "(derived)" have no verbatim source in
#: the prototype: the prototype renders no message for that path, so the wording
#: follows the register of its neighbours. They are the only entries a reviewer
#: may rewrite freely.
ERROR_COPY: dict[str, str] = {
    # ---------------------------------------------------------- authentication
    # L1572. Identical whether or not the email exists — the response must never
    # reveal that an account is present.
    "invalid_credentials": (
        "The credentials supplied are not valid, or the account cannot sign in. "
        "If the problem continues, contact your tenant administrator."
    ),
    # L1577
    "invalid_platform_credentials": (
        "The credentials supplied are not valid, or the operator account cannot sign in."
    ),
    "unauthenticated": "Authentication is required for this operation.",  # (derived)
    "token_expired": "The session has expired. Sign in again.",  # (derived)
    "token_revoked": (  # (derived) — refresh reuse revokes the whole chain
        "This session is no longer valid. Sign in again."
    ),
    # L1592
    "recovery_token_invalid": "It has expired or is not valid. Request a new one and try again.",
    "invitation_invalid": "It has expired or is not valid. Request a new one and try again.",
    # L1597
    "password_confirmation_mismatch": (
        "The new authentication material and its confirmation do not match."
    ),
    # ---------------------------------------------------------- authorization
    # L1063
    "insufficient_role": (
        "Your role or named permission does not include this operation. "
        "There is nothing to retry here."
    ),
    "insufficient_permission": (
        "Your role or named permission does not include this operation. "
        "There is nothing to retry here."
    ),
    "insufficient_scope": (  # L1170
        "Only the operations granted to a credential may be performed with it. "
        "Anything else is rejected before the operation is accepted."
    ),
    # L1059
    "tenant_not_active": (
        "The transition is controlled by a Platform Administrator; "
        "there is no tenant-side action that changes it."
    ),
    "wrong_realm": (  # (derived) — a tenant token on /v1/platform/*, or the reverse
        "This credential belongs to a different authentication realm."
    ),
    # ---------------------------------------------------------- not found
    # L1064. Never names the resource type.
    "not_found": (
        "A resource belonging to another tenant is indistinguishable "
        "from one that does not exist."
    ),
    # ---------------------------------------------------------- tenant / users
    # L1582
    "tenant_name_already_registered": (
        "A tenant account named “{business_name}” already exists. "
        "Sign in with the existing administrator account, "
        "or register under a different business name."
    ),
    # L1235 — a conflict, deliberately, not a validation error
    "user_already_exists": (
        "A user with this email already exists in this tenant. "
        "Email is unique per tenant, so this is a conflict rather than a validation error."
    ),
    # L1244 / L1226
    "last_active_administrator": "The last active administrator cannot be demoted or disabled.",
    # L1249
    "user_already_disabled": "A disabled user is already unable to authenticate.",
    # ---------------------------------------------------------- credentials
    # L1137
    # L1136
    "credential_name_required": (
        "Give the credential a name so it can be told apart in this list."
    ),
    "credential_requires_scope": (
        "Select at least one integration operation. "
        "A credential with no scope cannot authorize anything."
    ),
    # L1118
    "credential_revoked": "Revoked credentials cannot be rotated.",
    "credential_cap_reached": (  # (derived) — .env MAX_ACTIVE_API_KEYS_PER_TENANT
        "This tenant holds {used} of {limit} active credentials. "
        "Revoke a credential you no longer use before issuing another."
    ),
    # ---------------------------------------------------------- catalog
    # L1604 (field) / the banner form
    "product_already_exists": "a product with identifier {external_product_id} already exists",
    # L1603
    "product_quota_exhausted": (
        "This tenant holds {used} of {limit} products on plan {plan_code}. "
        "Disable products you no longer sell, "
        "or ask your platform contact about a quota override."
    ),
    # L1331
    "product_already_disabled": "This product is already disabled.",
    # L1335
    "product_concurrent_change": (
        "A concurrent change to the same product is reported as a state conflict; "
        "your entries are kept so you can reconcile them."
    ),
    # ---------------------------------------------------------- ingestion
    # L1612
    "product_sync_oversize": (
        "A synchronization is bounded to {limit:,} products. "
        "Split the collection and submit it in parts."
    ),
    # L1627
    "event_batch_oversize": (
        "A batch is bounded to {limit:,} events. Split the collection and submit it in parts."
    ),
    # L1611
    "sync_id_required": (
        "A synchronization identifier is required so a repeated submission is not applied twice."
    ),
    # L1621
    "event_id_required": "An event identifier is required — it is the idempotency key.",
    # L1626
    "batch_id_required": "A batch identifier is required.",
    # L1623
    "event_identifiers_required": "Customer and product identifiers are required.",
    # ---------------------------------------------------------- training
    # L1646. The job id is interpolated; concurrency is a setting.
    "training_already_running": (
        "Job {job_id} is already running. Global training concurrency is {concurrency}."
    ),
    # L1647
    "training_quota_exhausted": (
        "The training quota for this period is exhausted. It resets on {resets_on}."
    ),
    # L697 — the terminal reason a failed job carries
    "training_insufficient_data": (
        "Dataset snapshot held fewer than {minimum:,} eligible interaction sequences."
    ),
    # L1681
    "training_request_ref_required": (
        "A request identifier is required so a repeated request is not applied twice."
    ),
    "training_cooldown": (  # (derived) — the cooldown is provisional, see config
        "A training request was made recently. The next request may be made in {seconds} seconds."
    ),
    # L1706
    "training_not_cancellable": "Only a job in an active state can be cancelled.",
    # ---------------------------------------------------------- model versions
    # L1768
    "version_already_active": "This version is already active.",
    # L1733 / L1768
    "version_not_eligible": "Only an eligible version can be activated.",
    # L1769
    "rollback_requires_target": (
        "Roll back applies to the active version, and requires a retained target."
    ),
    # L1791
    "rollback_no_target": "No retained version is available as a roll-back target.",
    # L1749
    "archive_active_version": "An active version cannot be archived.",
    # L1749
    "archive_already_archived": "Already archived.",
    # L1749 — the retired version immediately preceding the active one is protected
    "archive_rollback_target": "Retained as the rollback target for the active version.",
    # ---------------------------------------------------------- plans / quotas
    # L1454
    "plan_closed": (
        "Plan {plan_code} is closed to new assignments. Reopen the plan or choose another."
    ),
    # L1496
    "plan_already_closed": "This plan is already closed.",
    # L1635
    "negative_limit": (
        "A negative limit conflicts with the quota model. "
        "Enter zero to withhold a usage type entirely."
    ),
    # L1485
    "plan_code_required": "A plan code is required.",
    # ---------------------------------------------------------- generic
    # L1342 / L1717 / L1792
    "reason_required": "A reason is required for this action.",
    # L1420 / L1340
    "reason_required_audited": "A reason is required and is written to the audit history.",
    # L1583
    "invalid_request": "Correct the highlighted field and submit again.",
    "unknown_field": (  # (derived) — silent acceptance hides client bugs
        "The request contains a field this operation does not accept."
    ),
    "request_too_large": (  # (derived) — non-bulk endpoints
        "The request body is larger than this operation accepts."
    ),
    "rate_limited": (  # (derived)
        "Too many requests. Retry in {retry_after_seconds} seconds."
    ),
    # L1065
    "internal_error": (
        "The request could not be completed. "
        "Quote the reference below if you contact platform support."
    ),
    # L1779 — serving degraded
    "service_unavailable": (
        "If activation fails, no version serves and the fallback strategy applies."
    ),
}


#: Field-level copy, keyed by `code`. The console renders these beside the input
#: rather than in the banner.
FIELD_ERROR_COPY: dict[str, str] = {
    "product_already_exists": "Already exists in this tenant.",  # L1604
    "tenant_name_already_registered": "Business name already registered.",  # L1582
    "negative_limit": "Must be zero or greater.",  # L1635
    "business_name_required": "A business name is required.",  # L1581
    "external_id_required": "An external product identifier is required.",  # L1602
    "title_required": "A title is required.",  # L1605
    "email_required": "An email is required — it is the account identifier.",  # L1234
    "confirmation_mismatch": "The two entries do not match.",  # L1593
    "current_material_required": "Required to make this change.",  # L1598
    "override_limit_non_negative": (  # L1462
        "The override limit must be a non-negative number."
    ),
}


class MissingErrorCopy(KeyError):  # noqa: N818 - raised as a lookup failure, not an API error
    """Raised when a code has no approved copy.

    Deliberately fatal rather than falling back to a generic string: an
    unreviewed sentence reaching a tenant is the failure this catalogue exists to
    prevent, and a missing entry is caught by the contract test.
    """


def resolve_copy(code: str, **kwargs: Any) -> str:
    try:
        template = ERROR_COPY[code]
    except KeyError as exc:
        raise MissingErrorCopy(
            f"no approved copy for error code {code!r}; add it to ERROR_COPY"
        ) from exc
    if not kwargs:
        return template
    return template.format(**kwargs)


def resolve_field_copy(code: str) -> str | None:
    return FIELD_ERROR_COPY.get(code)
