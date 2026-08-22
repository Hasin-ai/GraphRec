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
    # L1581. The prototype separates the two halves of a field failure: the
    # banner carries the sentence and the input carries a short marker. These
    # entries are the banner half; `FIELD_ERROR_COPY` holds the other.
    "business_name_required": "A business name is required.",
    # L1234. This form renders one string and no banner, so the same sentence
    # serves both slots.
    "email_required": "An email is required — it is the account identifier.",
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
    # L1604. This entry previously carried `API.md`'s shorter phrasing — "a
    # product with identifier … already exists" — which is a paraphrase of the
    # console's, and `API.md` is not binding (BUILD_PROMPT §0). Corrected to what
    # the prototype actually renders, second sentence included: it is the half
    # that tells the tenant what to do next.
    "product_already_exists": (
        "A product with identifier {external_product_id} already exists. "
        "Use a different identifier or update the existing product."
    ),
    # L1602
    "external_id_required": "An external product identifier is required.",
    # L1605
    "title_required": "A title is required.",
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
    # (derived) — the batch and sync forms both carry a collection field with no
    # message of its own in the prototype, because pasting nothing there is not
    # one of the paths it demonstrates. The register follows its neighbours.
    "event_collection_required": "A collection of events is required.",
    "product_collection_required": "A collection of products is required.",
    # (derived) — the single-event path has no batch to report a per-item
    # failure through, so an unknown product has to be said in the banner.
    # Identical whether the identifier belongs to another tenant or to nobody,
    # so it discloses nothing (NR-NF-02).
    "event_unknown_product": (
        "No product in this catalog has that external identifier. "
        "Add the product before submitting events against it."
    ),
    # (derived) — the submission page is reached from the submission that
    # produced it (L1393), so a submission still being written has nothing to
    # show yet. Distinct from `not_found`, which would be wrong: this one is
    # the tenant's own.
    "submission_not_ready": "This submission has been received and is not yet reportable.",
    # ---------------------------------------------------------- training
    # L1646. The job id is interpolated; concurrency is a setting.
    "training_already_running": (
        "Job {job_id} is already running. Global training concurrency is {concurrency}."
    ),
    # L1647
    "training_quota_exhausted": (
        "The training quota for this period is exhausted. It resets on {resets_on}."
    ),
    # ---------------------------------------------------------- usage quotas
    # (derived) — the prototype's integration reference names this failure but
    # renders no sentence for it: "limit / 429 / A plan or quota limit is
    # exhausted / event quota exhausted for the period" (L1637). The wording
    # follows `training_quota_exhausted` above, which is the verbatim member of
    # this family, and adds the counts `product_quota_exhausted` sets the
    # precedent for (L1603) — BACKEND_PLAN L1840 requires a rejection to name
    # limit, usage and reset.
    "event_quota_exhausted": (
        "This tenant has used {used} of {limit} events on plan {plan_code}. "
        "The quota resets on {resets_on}, "
        "or ask your platform contact about a quota override."
    ),
    # (derived) — the same sentence for the serving side. Phase 11 is the first
    # caller; the copy lives here so both halves of metering refuse alike.
    "recommendation_quota_exhausted": (
        "This tenant has used {used} of {limit} recommendations on plan {plan_code}. "
        "The quota resets on {resets_on}, "
        "or ask your platform contact about a quota override."
    ),
    # (derived) — the fallback for a bounded usage type with no sentence of its
    # own. Reaching it means a new type was given a plan limit without being
    # given copy, which is a gap worth reading as one.
    "usage_quota_exhausted": (
        "This tenant has used {used} of {limit} on plan {plan_code}. "
        "The quota resets on {resets_on}, "
        "or ask your platform contact about a quota override."
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
    # L1706. One code for every realm: the training route and the ingestion
    # queue refuse cancellation for the same reason and must say so
    # identically, and two codes carrying one string is how they drift apart.
    "job_not_cancellable": "Only a job in an active state can be cancelled.",
    # ---------------------------------------------------------------- jobs
    # A job's terminal failure reason is rendered in the console (dc.html L1696,
    # "Failure reason"). It is therefore approved copy, never an exception
    # message: a traceback out of an ingestion worker can carry a row of a
    # tenant's data in it, and NR-NF-06 forbids that reaching a body or a log.
    "job_attempts_exhausted": (  # (derived)
        "The job did not complete after {attempts} attempts and will not be retried."
    ),
    "job_interrupted": (  # (derived) — the last attempt was lost with its worker
        "The worker running this job stopped responding, and no attempts remain."
    ),
    "job_failed": (  # (derived) — an unclassified handler failure
        "The job stopped before completing. No partial result was kept."
    ),
    # L1714, the confirmation the console shows before requesting cancellation.
    "job_cancelled": "Work already done is discarded.",
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
#: rather than in the banner, and they are a **different string** from the
#: banner's: `err({body:'An external product identifier is required.'},
#: {id:'Required.'})` at L1602 puts the sentence in the banner and the marker in
#: the input. Three entries here previously held the banner half, which would
#: have rendered the whole sentence twice on one screen.
FIELD_ERROR_COPY: dict[str, str] = {
    "product_already_exists": "Already exists in this tenant.",  # L1604
    "tenant_name_already_registered": "Business name already registered.",  # L1582
    "negative_limit": "Must be zero or greater.",  # L1635
    "business_name_required": "Enter the registered business name.",  # L1581
    "external_id_required": "Required.",  # L1602
    "sync_id_required": "Required.",  # L1611
    "event_id_required": "Required.",  # L1621
    "batch_id_required": "Required.",  # L1626
    "event_identifiers_required": "Required.",  # L1623
    "event_unknown_product": "Not found in this catalog.",  # (derived)
    "title_required": "Required.",  # L1605
    "email_required": "An email is required — it is the account identifier.",  # L1234
    "confirmation_mismatch": "The two entries do not match.",  # L1593
    "current_material_required": "Required to make this change.",  # L1598
    "override_limit_non_negative": (  # L1462
        "The override limit must be a non-negative number."
    ),
}


#: code -> the reason a *single item* in a submission failed.
#:
#: A separate catalogue, because these are a different kind of sentence. An
#: `ERROR_COPY` entry is a banner: it addresses the caller, it is capitalised and
#: punctuated, and it says what to do next. An item reason is a table cell —
#: lower case, no full stop, and it appears beside the identifier of the item it
#: describes (dc.html L1391). Putting them in one dictionary would produce a
#: submission page whose Reason column reads like a series of alerts.
#:
#: Every entry is short by construction, and `submission_errors.reason` is
#: bounded at 300 characters in the database. Neither the submitted item nor any
#: part of it is ever interpolated into one of these: "Raw payloads are never
#: echoed back" (L1391) is a promise about this exact column.
ITEM_ERROR_COPY: dict[str, str] = {
    # --------------------------------------------------- verbatim, product sync
    "item_price_not_positive_decimal": "price is not a positive decimal",  # L1614
    "item_category_too_long": "category exceeds 120 characters",  # L1614
    "item_product_disabled": "external identifier already disabled",  # L689
    # ---------------------------------------------------- verbatim, event batch
    "item_occurred_at_in_future": "occurred_at is in the future",  # L1180
    "item_unknown_product": "unknown external product identifier",  # L1629
    "item_batch_oversize": "batch exceeded the accepted payload size",  # L691
    # ------------------------------------------------------------- (derived)
    # The prototype demonstrates six item failures. A validator that only
    # reported those six would have to accept everything else, so the rest are
    # written here in the same register rather than invented at the call site.
    "item_not_an_object": "item is not a JSON object",
    "item_external_id_missing": "external identifier is missing",
    "item_external_id_too_long": "external identifier exceeds 120 characters",
    "item_title_missing": "title is missing",
    "item_title_too_long": "title exceeds 500 characters",
    "item_availability_unknown": "availability is not a recognised value",
    "item_attributes_not_object": "attributes is not a JSON object",
    "item_event_id_missing": "event identifier is missing",
    "item_event_id_too_long": "event identifier exceeds 120 characters",
    "item_customer_id_missing": "customer identifier is missing",
    "item_customer_id_too_long": "customer identifier exceeds 120 characters",
    # Distinct from `item_unknown_product` above, and the distinction is the
    # point: these two say the item carried no usable product identifier,
    # while that one says the identifier it carried names nothing in this
    # catalog. A tenant fixes the first in their exporter and the second in
    # their catalog, so telling them apart is the whole value of the row.
    "item_product_id_missing": "product identifier is missing",
    "item_product_id_too_long": "product identifier exceeds 120 characters",
    "item_event_type_unknown": "event type is not a recognised value",
    "item_occurred_at_missing": "occurred_at is missing",
    "item_occurred_at_invalid": "occurred_at is not a valid timestamp",
    "item_value_not_decimal": "value is not a non-negative decimal",
    "item_context_not_an_object": "context is not a JSON object",
    "item_repeated_in_submission": "the same identifier appears earlier in this submission",
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


def resolve_item_copy(code: str) -> str:
    """Resolve a per-item reason. Fatal on a miss, exactly like `resolve_copy`.

    A submission error whose reason fell back to a generic string would be
    indistinguishable from one whose reason was never written, and the tenant
    reading the page would have no way to tell which item they need to fix.
    """
    try:
        return ITEM_ERROR_COPY[code]
    except KeyError as exc:
        raise MissingErrorCopy(
            f"no approved item reason for {code!r}; add it to ITEM_ERROR_COPY"
        ) from exc
