"""Request and response bodies.

Field names are snake_case on the wire (D11). Two rules hold throughout:

* A response never contains a credential digest, a token digest, or a
  `tenant_id` belonging to anyone but the caller.
* A request never contains a `tenant_id`. Tenant scope comes from the verified
  credential; a body field would be a second, forgeable source for it.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from graphrec.common.enums import (
    AuditAction,
    AuditActor,
    AuditOutcome,
    Availability,
    CredentialScope,
    CredentialState,
    DeploymentState,
    FailureArea,
    MeasurementStatus,
    Severity,
    SubmissionKind,
    SubmissionStatus,
    TenantRole,
    TenantStatus,
    UsageType,
    UserStatus,
)


class _Body(BaseModel):
    # `extra="forbid"` so a request carrying `tenant_id` is a 422 rather than a
    # silently ignored field that a reader might assume had an effect.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterTenantRequest(_Body):
    tenant_name: str = Field(min_length=1, max_length=200)
    tenant_code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-]*$")
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("tenant_code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class SignInRequest(_Body):
    """Sign-in takes a tenant code as well as an email.

    The prototype's form (dc.html L1017-1019) asks for email and password only,
    but the SRS makes email unique *per tenant* (dc.html L1235: "Email is unique
    per tenant"). Those two cannot both hold: one person consulting for two
    tenants has one email at each, and nothing in an email-and-password pair says
    which they mean.

    Resolving it by silently picking a tenant would be the dangerous answer, so
    the identifier is asked for. This is a reported conflict, not a settled
    decision — see the Phase 2 report.
    """

    tenant_code: str = Field(min_length=2, max_length=32)
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class PlatformSignInRequest(_Body):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(_Body):
    refresh_token: str = Field(min_length=1, max_length=4096)


class SessionResponse(BaseModel):
    """What a sign-in returns.

    The refresh token appears here and is not retrievable afterwards — only its
    SHA-256 digest is stored. The console keeps it in memory, never in
    `localStorage`, which is readable by any injected script.
    """

    access_token: str
    token_type: str = "Bearer"
    expires_at: dt.datetime
    refresh_token: str
    refresh_expires_at: dt.datetime


class TenantResponse(BaseModel):
    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    status: str
    plan_code: str | None = None
    created_at: dt.datetime
    status_reason: str | None = None


class UserResponse(BaseModel):
    """One tenant user, plus the one derived fact the console cannot compute.

    `is_last_active_administrator` is BUILD_PROMPT §10.9's fifth console-only
    field. The prototype worked it out client-side (`isLast`, dc.html L1243)
    because it held the whole user list; a real client holding one page of it
    cannot, and a client holding all of it would still be racing the server. It
    is the server's answer to "would demoting or disabling this person leave the
    tenant with nobody who can administer it", and the console renders it as a
    disabled control with a reason rather than as a request that gets refused.
    """

    tenant_user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    created_at: dt.datetime
    last_authenticated_at: dt.datetime | None = None
    is_last_active_administrator: bool = False


class MeResponse(BaseModel):
    """The caller's own identity, and the tenant it is scoped to.

    `tenant_id` is echoed because the console needs it for display. It is the
    caller's own, taken from the verified token — never a value the caller sent.
    """

    tenant_user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str


class PlatformMeResponse(BaseModel):
    """No `tenant_id` field, because an operator has no tenant to report."""

    platform_user_id: uuid.UUID
    email: str
    display_name: str
    permissions: list[str]


class CreateUserRequest(_Body):
    email: EmailStr
    display_name: str = Field(default="", max_length=200)
    role: TenantRole


class AcceptInvitationRequest(_Body):
    """The invitee's three fields, exactly as the prototype's form asks for them.

    dc.html L1045: an invitation token, authentication material, and a
    confirmation. The confirmation is compared server-side as well as in the
    console — a mismatch that only the browser catches is a mismatch that a
    direct API call does not catch at all, and the account would activate with a
    password its owner mistyped.

    There is no `email` field and no `tenant_code`. Both are properties of the
    invitation, and asking for either would let a caller assert them.
    """

    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=12, max_length=1024)
    password_confirmation: str = Field(min_length=1, max_length=1024)


class InvitationResponse(BaseModel):
    """What the administrator gets back after inviting someone.

    `invitation_token` is present because Phase 2 has no mail transport: the
    token has to reach the invitee somehow, and returning it to the
    administrator who minted it is the honest interim. It is shown once and is
    not retrievable afterwards — only its SHA-256 digest is stored — and it must
    stop being returned as soon as invitations are delivered by mail.
    """

    user: UserResponse
    invitation_id: uuid.UUID
    expires_at: dt.datetime
    invitation_token: str


class RequestRecoveryRequest(_Body):
    """Step 1 of recovery: which account, and nothing else.

    A tenant code as well as an email, for the reason `SignInRequest` gives at
    length — email is unique per tenant, so an email on its own does not name an
    account, and recovery that guessed would reset the wrong person's password.
    """

    tenant_code: str = Field(min_length=2, max_length=32)
    email: EmailStr


class RecoveryRequestedResponse(BaseModel):
    """The one answer step 1 ever gives.

    There is no field here that varies with whether the account exists. That is
    the whole schema: a boolean `sent`, or an `expires_at` that were only
    present on success, would be the disclosure the route is built to avoid
    (dc.html L1035).
    """

    detail: str


class ConfirmRecoveryRequest(_Body):
    """Step 2: the proof and the new material. Mirrors `AcceptInvitationRequest`.

    No `email` and no `tenant_code`, for the same reason — both are properties
    of the proof, and asking for either would let a caller assert them.
    """

    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=12, max_length=1024)
    password_confirmation: str = Field(min_length=1, max_length=1024)


class ChangeRoleRequest(_Body):
    role: TenantRole


# ------------------------------------------------------------- onboarding


class OnboardingStepBody(BaseModel):
    """One step of the §3.5 story, with the state that decides how it renders."""

    key: str
    title: str
    detail: str
    route: str = Field(description="The console route that performs this step.")
    complete: bool
    required_role: str | None = Field(
        default=None,
        description=(
            "The role that may perform this step, or null when any tenant user "
            "may. A caller who does not hold it still sees the step — it is "
            "somebody else's, not missing."
        ),
    )
    permitted: bool = Field(
        description="Whether the *caller* may perform this step, given their role."
    )


class OnboardingResponse(BaseModel):
    """`GET /v1/onboarding` — BUILD_PROMPT §10.9's first console-only endpoint.

    `completed` and `total` are computed here rather than left to the client, so
    that "3 of 8" cannot disagree with the ticks beside it.
    """

    steps: list[OnboardingStepBody]
    completed: int
    total: int


class UpdateProfileRequest(_Body):
    """`PATCH /v1/me`. One field, because one field is all a user may change."""

    display_name: str = Field(min_length=1, max_length=200)


class ChangeOwnPasswordRequest(_Body):
    """`POST /v1/me:change-password`. The current one is required, session or not."""

    current_password: str = Field(min_length=1, max_length=1024)
    password: str = Field(min_length=12, max_length=1024)
    password_confirmation: str = Field(min_length=1, max_length=1024)
    keep_session: str | None = Field(
        default=None,
        # The same bound `RefreshRequest.refresh_token` uses, because it is the
        # same value. 512 was the invitation-token bound copied one field too
        # far, and it made this field unable to hold anything a caller could
        # actually put in it.
        max_length=4096,
        description=(
            "The caller's own refresh token, so the session they are typing in "
            "survives. Every other session for the account is revoked."
        ),
    )


class ChangeStatusRequest(_Body):
    status: UserStatus


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


# ------------------------------------------------------------- credentials


class CreateCredentialRequest(_Body):
    """The create dialog's three fields (dc.html L1134)."""

    # No `min_length` on either field, deliberately. Pydantic would refuse an
    # empty name or an empty scope list with its own generic wording ("List
    # should have at least 1 item"), which would replace the prototype's copy
    # at L1136 and L1137. Those strings are a requirement, so the emptiness
    # checks belong in the service where the catalogue is reachable. The
    # `max_length` bounds stay here: they are abuse limits, not product copy.
    name: str = Field(max_length=100)
    scopes: list[CredentialScope] = Field(max_length=12)
    expires_in_days: Literal[90, 180, 365]


class RotateCredentialRequest(_Body):
    """The rotate dialog offers scopes only; grace is an API-only affordance.

    `grace_seconds` defaults to 0, which is what makes the console's promise
    that the old secret stops working literally true for every rotation the
    console performs (dc.html L1145). ADR 0010.
    """

    scopes: list[CredentialScope] | None = Field(default=None, max_length=12)
    grace_seconds: int = Field(default=0, ge=0, le=86_400)
    reason: str | None = Field(default=None, max_length=500)


class CredentialResponse(BaseModel):
    """One row of the credentials table. Carries no secret and no digest.

    `state` is computed server-side against server time. The prototype derives
    it client-side (L1107); a real client must not, because its clock is not
    the one the expiry is measured against.
    """

    key_id: uuid.UUID
    name: str
    visible_prefix: str
    scopes: list[CredentialScope]
    state: CredentialState
    expires_at: dt.datetime
    revoked_at: dt.datetime | None
    last_used_at: dt.datetime | None
    created_at: dt.datetime
    #: Gate-5 preconditions, so the console disables a control and shows the
    #: server's reason rather than deciding for itself.
    can_rotate: bool
    can_revoke: bool
    blocked_reason: str | None
    #: Present only while a rotation grace window is open.
    grace_expires_at: dt.datetime | None


class IssuedCredentialResponse(BaseModel):
    """The one-time secret payload, returned at creation and at rotation only.

    This is the only response model in the system with a `secret` field. It is
    never returned by a read route, and no other model may carry one — the
    parity test in tests/isolation scans for exactly that.
    """

    credential: CredentialResponse
    secret: str
    #: Reproduced from the prototype's modal so the console does not restate it
    #: (dc.html L561) and the API is self-describing for non-console callers.
    notice: str = (
        "This value is shown once. GraphRec does not retain it — "
        "if it is lost, rotate the credential to obtain a new one."
    )


class CredentialListResponse(BaseModel):
    credentials: list[CredentialResponse]
    total: int


class ScopeDescriptor(BaseModel):
    """One entry of the scope catalogue behind `GET /v1/scopes`."""

    scope: CredentialScope
    label: str
    short_label: str


class ScopeListResponse(BaseModel):
    scopes: list[ScopeDescriptor]


# ----------------------------------------------------------------- catalog
#
# Field names follow the prototype's own catalogue payload (dc.html L1173):
# `external_id`, `title`, `category`, `brand`, `price`, `active`,
# `availability`. Not `external_product_id` / `is_active`, which are the column
# names — the wire vocabulary is the one the integration page publishes, and
# Phase 6's bulk endpoint has to accept the same words as this one.


class ProductBody(_Body):
    """The writable fields. Used by `PUT` and, with everything omitted, `PATCH`.

    No `min_length` on `title`, deliberately, and none on `external_id` below:
    Pydantic would refuse an empty value with its own generic wording, which
    would replace the prototype's copy at L1602 and L1605. Those strings are a
    requirement, so emptiness is checked in the service where the approved
    catalogue is reachable. The `max_length` bounds stay here — they are abuse
    limits, not product copy.

    `price` is a `Decimal`, and is carried on the wire as a string ("8.40",
    L1173). A float price is a price that cannot be represented exactly, and it
    is the number a tenant is eventually billed against.
    """

    title: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=120)
    brand: str | None = Field(default=None, max_length=200)
    price: decimal.Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    active: bool | None = None
    availability: Availability | None = None
    description: str | None = Field(default=None, max_length=8000)
    attributes: dict[str, Any] | None = Field(default=None)


class CreateProductRequest(ProductBody):
    """`POST /v1/products` — the Add product form (L1319-L1324)."""

    external_id: str = Field(default="", max_length=120)


class DisableProductRequest(_Body):
    """The disable dialog's one field (L1341).

    Unbounded below for the same reason as above: the four-character floor is
    enforced in the service so the refusal is L1342's sentence.
    """

    reason: str = Field(default="", max_length=500)


class ProductResponse(BaseModel):
    """One product, as both the table row and the detail page need it.

    `eligible` and `exclusion_reason` are computed by the database, not by the
    console: the prototype derives its `served` / `ineligible` badge client-side
    (L1307) and a real client must not, because the rule that decides it is the
    same one the serving path applies and the two must never disagree.
    """

    external_id: str
    title: str
    category: str | None
    brand: str | None
    price: decimal.Decimal | None
    active: bool
    availability: Availability
    description: str | None
    attributes: dict[str, Any]

    #: L1307's badge: `served` when true, `ineligible` when false.
    eligible: bool
    #: The machine-readable reason — `product_out_of_stock`, `product_inactive`,
    #: `product_removed` — or null when the product serves.
    ineligibility: str | None
    #: L1302's `sub`: the sentence rendered under the title, or null. A client
    #: must not assemble this from `ineligibility`; that would be a second copy
    #: of the wording.
    exclusion_reason: str | None

    #: Gate-5 precondition for the Disable action, with the prototype's own
    #: reason for the disabled control (L1332).
    can_disable: bool
    blocked_reason: str | None

    disabled_reason: str | None
    disabled_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ProductListResponse(BaseModel):
    """D10: limit/offset with a **total**.

    The total is not optional. The catalogue table renders "8 of 12"
    (`count: list.length + ' of ' + s.products.length`, L1316), and a cursor
    cannot produce the second number.
    """

    products: list[ProductResponse]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ ingestion
#
# The request models here are deliberately **permissive about content and
# strict about shape**. `extra="forbid"` still holds, so a body carrying
# `tenant_id` is refused; but every field is optional and loosely typed, and the
# real verdict comes from `graphrec.domain.ingestion.validation`.
#
# That is not laziness. Pydantic's rejection is a framework 422 reading
# "invalid_request", and the prototype approves specific copy for these forms —
# "An event identifier is required — it is the idempotency key." (L1621),
# "Customer and product identifiers are required." (L1623). If Pydantic
# answered first, the tenant would never see either sentence. One validator
# decides for the single event, the batch item and the sync item alike, which is
# also the only way `POST /v1/events` and `POST /v1/events/batches` can honestly
# claim to "share one event shape" (L1175).


class SubmitEventRequest(_Body):
    """One interaction event (L1176).

    `event_id` is the idempotency key, and that is the whole design of this
    route: a repeat is confirmed, not rejected and not applied twice.
    """

    event_id: str | None = None
    customer_id: str | None = None
    external_product_id: str | None = None
    event_type: str | None = None
    occurred_at: str | None = None
    #: A string, never a float. `"129.00"` in the prototype's own snippet, and a
    #: monetary value that cannot be represented exactly is one a tenant will
    #: eventually be billed against.
    value: str | None = None
    context: dict[str, Any] | None = None


class SubmitEventResponse(BaseModel):
    """`{"event_id": ..., "status": "duplicate_confirmed"}` (L1178).

    `status` is `accepted` or `duplicate_confirmed`. Both are 200 and both are
    successes — "This is a success outcome, not an error." (L1622).
    """

    event_id: str
    status: Literal["accepted", "duplicate_confirmed"]
    #: Present only on a duplicate. The prototype shows "First received
    #: 2026-08-14 09:41:02" beside the confirmation (L1622), which is what makes
    #: the answer useful: it tells the caller *when* they already sent it.
    first_received_at: dt.datetime | None = None


class SubmitEventBatchRequest(_Body):
    """`{"batch_id": ..., "events": [...]}` (L1177)."""

    batch_id: str | None = None
    events: list[Any] | None = None


class BulkUpsertProductsRequest(_Body):
    """`{"sync_id": ..., "products": [...]}` (L1173)."""

    sync_id: str | None = None
    products: list[Any] | None = None
    #: L1357's two options, on the wire as the values the API takes. The
    #: prototype's control shows "upsert" and "upsert and disable missing";
    #: the second is `upsert_and_disable_missing` here, because a wire value
    #: with spaces in it is a wire value somebody will quote wrongly.
    mode: Literal["upsert", "upsert_and_disable_missing"] | None = None


class SubmissionCounts(BaseModel):
    """The partition, all five buckets, on every submission read.

    `received = accepted + updated + skipped + failed`, always. The console
    divides their sum by `received` to draw the progress rail (L1380), so a
    count that appears in two buckets renders as a rail past 100%.

    All five are sent for both kinds even though each kind only shows four:
    a product sync labels the third stat "Updated" and an event batch labels it
    "Duplicates" over `skipped` (L1389). Which label to use is the console's
    decision; which numbers are true is this API's.
    """

    received: int
    accepted: int
    updated: int
    skipped: int
    failed: int


class SubmissionErrorItem(BaseModel):
    """One reported failure: "Item reference", "Reason" (L1391).

    Two columns, and nothing else. "Errors identify the offending item and a
    safe reason. Raw payloads are never echoed back." — so `ref` is an
    identifier the tenant sent, truncated, and `reason` is resolved from the
    approved catalogue by code. Neither is assembled from the item.
    """

    ref: str
    reason: str


class SubmissionResponse(BaseModel):
    """One read for both kinds (L1179), and two vocabularies for where it is.

    `status` is the coarse outcome the badge renders — `processing`,
    `succeeded`, `failed`. `stage` is the rail position — `received`,
    `validating`, `applying`, `completed` (L1382). They are not the same
    question: the badge answers "is this finished, and did it work", the rail
    answers "how far along". Deriving one from the other in the console would
    put that mapping in the client, where it would drift.
    """

    submission_id: uuid.UUID
    kind: SubmissionKind
    status: Literal["processing", "succeeded", "failed"]
    stage: SubmissionStatus
    #: The identifier the tenant submitted under — `sync_id` or `batch_id`.
    #: Named once, neutrally, because one read serves both kinds.
    reference: str
    submitted_at: dt.datetime
    completed_at: dt.datetime | None
    counts: SubmissionCounts
    #: `failed_count` is every failure; `errors` is a capped sample of them.
    #: Separate on purpose — a 5,000-item batch can fail 5,000 times, and a
    #: tenant needs the true total alongside the first hundred rows.
    error_count: int
    errors: list[SubmissionErrorItem]
    #: Set only when the submission itself failed, as opposed to individual
    #: items failing within a submission that completed.
    failure_code: str | None = None


# ------------------------------------------------------------------- metering


class UsagePeriodBody(BaseModel):
    """The window the usage table is reporting on (BACKEND_PLAN L1186)."""

    start: dt.date
    end: dt.date
    #: "monthly · resets 2026-09-01" — the same string the accumulated rows
    #: carry in their own `reset` field, hoisted so the page header can say it
    #: once (dc.html L710).
    label: str


class UsageItemBody(BaseModel):
    """One row of the usage table.

    Three fields are nullable and all three are nullable for the same reason.
    `measured` is `null` when we could not measure; `remaining` is `null` when
    either side of the subtraction is unknown; `effective_limit` is `null` when
    the type is not bounded at all. The console renders each as a phrase — "not
    calculable", "unavailable" — never as a zero (L1806, footnote L1824).

    A client that coalesces any of these to `0` has reintroduced exactly the
    defect this contract exists to prevent.
    """

    usage_type: UsageType
    measured: decimal.Decimal | None
    effective_limit: int | None
    remaining: int | None
    #: "monthly · resets 2026-09-01" / "no reset · standing limit" / "continuous".
    reset: str
    #: `measured` | `measurement delayed` | `unavailable` — the label, not the
    #: enum name, because it is rendered directly into a tag (L1818).
    measurement_status: str
    #: `plan` or `override`. The console needs to say which, because a tenant
    #: looking at a number above their plan's figure should see why (L1195).
    limit_source: Literal["plan", "override"]


class UsageResponse(BaseModel):
    period: UsagePeriodBody
    items: list[UsageItemBody]
    #: Present only when some row is not measured. Approved copy (L1824), sent
    #: by the server so the console does not compose its own explanation of a
    #: gap it cannot see the cause of.
    footnote: str | None = None


class UsageTrendRowBody(BaseModel):
    """One period of the trend panel (L1818).

    `quantities` is keyed by usage type rather than being four named columns, so
    a fifth trended type does not become a wire change. Values are nullable for
    the usual reason: a period that was never rolled up has no number, and
    saying so is the point.
    """

    period: str
    #: "2026-08 (current)" for the open period, "2026-07" for a closed one.
    label: str
    quantities: dict[UsageType, decimal.Decimal | None]


class UsageTrendsResponse(BaseModel):
    rows: list[UsageTrendRowBody]


class EntitlementBody(BaseModel):
    """What one usage type is allowed, and what the plan alone would allow.

    Both numbers, because an override is otherwise invisible: a tenant sees a
    limit that does not match the plan they are on and has no way to tell
    whether the plan is wrong or an exception is in force (L1450, L1459).
    """

    usage_type: UsageType
    plan_limit: int | None
    effective_limit: int | None
    limit_source: Literal["plan", "override"]


class SubscriptionResponse(BaseModel):
    """The plan, read-only.

    There is no write counterpart and there will not be one. ROUTES L178: plan
    assignment is UC-28, a platform action; "Plan appears read-only on /usage."
    """

    plan_code: str
    plan_name: str
    description: str | None
    entitlements: list[EntitlementBody]


# ------------------------------------------------------------------ training


class RequestTrainingRequest(_Body):
    """The dialog's four fields (dc.html L1677-1680), and nothing else.

    Each of the three parameters is a `Literal` over the values the dialog
    offers rather than a bounded integer. The dialog is a select, not a slider:
    a client sending `max_epochs: 21` has invented a value rather than chosen
    one, and the migration's `CHECK` constraints say the same thing at the other
    end. Rejecting it here means the run is refused before a job exists.
    """

    request_ref: str = Field(min_length=1, max_length=200)
    model_type: Literal["DGSR"] = "DGSR"
    interaction_window_days: Literal[30, 90, 180] = 90
    max_epochs: Literal[10, 20, 40] = 20


class CancelTrainingRequest(_Body):
    """L1717: the dialog will not submit below four characters.

    Enforced here as well as there, because the console is not the only client
    and "cancelled" with no reason is the record nobody can interpret six months
    later. `min_length` runs after `str_strip_whitespace`, so four spaces is a
    422 rather than a reason.
    """

    reason: str = Field(min_length=4, max_length=500)


class TrainingConcurrencyBody(BaseModel):
    limit: int
    #: `platform` today, and only aspirationally so — see PHASE_9_REPORT §3.
    scope: str


class TrainingDataBody(BaseModel):
    sequences: int
    required: int
    sufficient: bool


class TrainingQuotaBody(BaseModel):
    used: int
    #: `None` is unlimited, which is not the same as zero and must not render as
    #: one. The console shows "6 / 8" or "6 / unlimited" from this pair.
    limit: int | None
    remaining: int | None
    resets_at: dt.date


class TrainingCooldownBody(BaseModel):
    active: bool
    seconds_remaining: int
    window_seconds: int


class TrainingEligibilityResponse(BaseModel):
    """The four stat cards (L1666-1669), each with its own numbers.

    `reason` is `""` when eligible rather than absent, matching the prototype's
    own contract at L1648. A client renders it unconditionally; an optional
    field would invite `reason ?? 'ok'` and a message that is not ours.
    """

    eligible: bool
    reason: str
    concurrency: TrainingConcurrencyBody
    interaction_data: TrainingDataBody
    quota: TrainingQuotaBody
    cooldown: TrainingCooldownBody


class TrainingSnapshotResponse(BaseModel):
    snapshot_id: uuid.UUID
    training_job_id: uuid.UUID
    cutoff_at: dt.datetime
    window_days: int
    #: The store's own URI. Not a download link: there is no signed-URL route in
    #: this phase, and returning something that looks fetchable but is not would
    #: be worse than returning the identifier it is.
    uri: str
    checksum: str
    sequence_count: int
    product_count: int
    event_count: int
    created_at: dt.datetime


class TrainingMetricBody(BaseModel):
    epoch: int
    metric_name: str
    value: float


class TrainingMetricsResponse(BaseModel):
    training_job_id: uuid.UUID
    metrics: list[TrainingMetricBody]


class TrainingJobResponse(BaseModel):
    """One run, with the rail and the two controls the console draws from it.

    `stages` travels with every response rather than being a constant the client
    holds. The rail is nine names in a fixed order and a client that hard-coded
    them would silently disagree with the server the first time one changed —
    which is exactly the class of drift the generated enums exist to prevent.
    """

    training_job_id: uuid.UUID
    job_id: uuid.UUID
    state: str
    stages: list[str]
    stage_index: int
    progress: str
    note: str
    requested_by: uuid.UUID | None
    request_ref: str
    interaction_window_days: int
    max_epochs: int
    requested_at: dt.datetime
    completed_at: dt.datetime | None
    failure_reason: str | None
    cancel_reason: str | None
    error_reference: str | None
    snapshot: TrainingSnapshotResponse | None
    #: Gate 5. Whether the button is enabled, decided here and not by the client
    #: re-deriving it from `state` — and `blocked_reason` is why, in words the
    #: console shows rather than invents.
    can_cancel: bool
    blocked_reason: str | None


class TrainingJobListResponse(BaseModel):
    jobs: list[TrainingJobResponse]
    total: int


# ------------------------------------------------------------- model registry


class ArchiveVersionRequest(_Body):
    """L1798: the archive dialog has no reason field.

    BACKEND_PLAN L1168 specifies `{ reason }`, and the console the specification
    is drawn from does not collect one. Requiring it would make the prototype's
    own dialog fail, so it is optional here and recorded when it is sent — which
    is also what Phase 12's audit entry needs, since an archive with no stated
    reason is still an archive somebody has to account for.
    """

    reason: str | None = Field(default=None, min_length=4, max_length=500)


class VersionActionBody(BaseModel):
    """One control in the `actions` block (BACKEND_PLAN L1155).

    `reason` is populated only when the control is disabled, for the reason
    `blocked_reason` is on a training job: a reason beside an enabled button is
    a reason the console has to remember not to show.
    """

    allowed: bool
    reason: str | None


class VersionActionsBody(BaseModel):
    activate: VersionActionBody
    rollback: VersionActionBody
    archive: VersionActionBody


class VersionMeasuresBody(BaseModel):
    """The four measures the comparison table draws (L1752-1755).

    Every field is nullable. A measure that was not recorded is absent, not
    zero: zero is a score, and a coverage rendered as 0.00 says the model
    recommended one item to everybody.
    """

    recall_at_10: float | None
    hit_rate_at_10: float | None
    ndcg_at_10: float | None
    coverage: float | None


class VersionComparisonBody(VersionMeasuresBody):
    """The active version's column, labelled with its number (L1755)."""

    version_number: int


class VersionArtifactBody(BaseModel):
    digest: str
    #: The store's own URI, not a download link, for the reason the snapshot's
    #: `uri` is not one.
    uri: str
    snapshot_id: uuid.UUID
    #: Rendered — "sequence · product · category" (L1758) — rather than the
    #: stored object. Phase 11 compares contracts field by field; this is the
    #: line the page draws.
    feature_contract: str
    embedding_dim: int


class ModelVersionResponse(BaseModel):
    """The whole `/models/:versionId` page, including its three-way comparison.

    `baseline` is the platform's popularity ranker over the same held-out rows
    (L1752), and `active_comparison` is `null` when nothing is active or when
    this *is* the active version — the prototype renders an em-dash there, which
    is a client's rendering of an absent value rather than a value the server
    should invent.
    """

    version_id: uuid.UUID
    version_number: int
    model_id: uuid.UUID
    model_type: str
    status: str
    created_at: dt.datetime
    archived_at: dt.datetime | None
    training_job_id: uuid.UUID
    metrics: VersionMeasuresBody
    baseline: VersionMeasuresBody
    active_comparison: VersionComparisonBody | None
    artifact: VersionArtifactBody
    eligible: bool
    failure_note: str | None
    actions: VersionActionsBody


class ModelVersionListItem(BaseModel):
    """One row of the `/models` table (L1726-1733).

    Deliberately not the detail response. The table draws a version number, a
    status, a date and three headline numbers; the detail response carries a
    three-way comparison that costs two more reads per row and that no column
    here renders. `metrics` is the denormalised copy on `model_versions`, which
    is what that column exists for.

    `can_activate` and `blocked_reason` are the row's Activate control (L1733),
    resolved server-side like every other gate-5 control.
    """

    version_id: uuid.UUID
    version_number: int
    model_type: str
    status: str
    created_at: dt.datetime
    metrics: VersionMeasuresBody
    eligible: bool
    serving: bool
    can_activate: bool
    blocked_reason: str | None


class ModelVersionListResponse(BaseModel):
    versions: list[ModelVersionListItem]
    total: int


class ModelVersionSummaryResponse(BaseModel):
    """The five stat cards above `/models` (L1737).

    A summary endpoint rather than a client-side count, because counting
    client-side requires the whole list and `/models` is paginated.
    """

    active: int
    desired: int
    eligible: int
    retired: int
    failed_deployment: int


# ------------------------------------------------------------------- serving


class ActivateVersionRequest(_Body):
    """`POST /v1/model-versions/{id}:activate` — `{ reason? }` (L1161).

    Optional, like the archive dialog's: the console's activate dialog (L1779)
    collects a confirmation and not a justification, and requiring a sentence
    the prototype never asks for would make its own dialog fail.
    """

    reason: str | None = Field(default=None, min_length=4, max_length=500)


class RollbackRequest(_Body):
    """`POST /v1/models/{id}:rollback` — `{ target_version_id, reason }` (L1166).

    `reason` is required here and optional on activate, which is not an
    inconsistency: L1792 collects one, because a roll back is a statement that
    something went wrong and the next person to read the history needs to know
    what.

    `target_version_id` confirms rather than selects. There is exactly one
    retained target, the server knows which, and a body naming a different one
    is refused — a dialog that showed "roll back to v7" must not roll back to v6
    because v7 was archived while it was open.
    """

    target_version_id: uuid.UUID | None = None
    reason: str = Field(min_length=4, max_length=500)


class DeploymentVersionBody(BaseModel):
    """A version as the deployment refers to it: id and number, nothing else."""

    version_id: uuid.UUID
    version_number: int


class DeploymentResponse(BaseModel):
    """`GET /v1/deployment` — the six stats and the description list (L1831-1839).

    `serving_previous` is ER-F-06 on the wire. It is `true` exactly when a
    version was asked for and a different one is answering, which is the state a
    failed activation leaves behind and the one the console must be able to
    render without diffing two ids itself.

    The measurement fields repeat `/v1/metrics/summary` deliberately: the plan
    lists them on this response (L1198) because the board draws them beside the
    deployment, and a console that had to join two responses to draw one card
    would draw it from two instants.
    """

    deployment_id: uuid.UUID
    state: DeploymentState
    active_version: DeploymentVersionBody | None
    desired_version: DeploymentVersionBody | None
    serving_previous: bool
    desired_replicas: int
    ready_replicas: int
    last_transition_at: dt.datetime | None
    recent_error_count_24h: int
    fallback_rate: float | None
    latency_p95_ms: int | None
    measurement_status: str
    measurement_freshness_seconds: int | None


class ReplicaBody(BaseModel):
    """One row of the replica table.

    `status` and `ready` are separate because a replica can be `running` and
    still loading a bundle. Collapsing them would make "3 / 3 ready" true the
    moment three containers existed — the exact number L1835 colours amber.
    """

    replica_ref: str
    status: str
    ready: bool
    version_id: uuid.UUID | None
    started_at: dt.datetime
    ended_at: dt.datetime | None
    observed_at: dt.datetime


class DeploymentReplicasResponse(BaseModel):
    desired_replicas: int
    ready_replicas: int
    replicas: list[ReplicaBody]


class DeploymentRevisionBody(BaseModel):
    """One attempt to change what serves — including the ones that failed.

    A failed activation is a row here with a `failure_reason`, which is what a
    tenant asking "why is version 8 not serving?" is asking to read.
    """

    revision: int
    kind: str
    status: str
    from_version_id: uuid.UUID | None
    to_version_id: uuid.UUID | None
    reason: str | None
    failure_reason: str | None
    started_at: dt.datetime
    completed_at: dt.datetime | None


class AutoscalingResponse(BaseModel):
    """`GET /v1/deployment/autoscaling` — bounds and recent actions (XR-F-08).

    "Recent actions" are the deployment revisions. The alternative, a separate
    scaling-event log, would record the same transitions under a second name.
    """

    min_replicas: int
    max_replicas: int
    desired_replicas: int
    ready_replicas: int
    target_rps_per_replica: float
    recent_actions: list[DeploymentRevisionBody]


class MetricsSummaryResponse(BaseModel):
    """`GET /v1/metrics/summary` (L1200).

    Every measurement is nullable and `measurement_status` explains the nulls. A
    window with no traffic reports `measurement delayed`, never zeros — the same
    discipline `/v1/usage` follows, and for the same reason: a zero is a claim
    that something was measured.
    """

    window_hours: int
    requests: int
    errors: int
    availability: float | None
    latency_p95_ms: int | None
    fallback_rate: float | None
    measurement_status: str
    measurement_freshness_seconds: int | None


class ServingErrorBody(BaseModel):
    """One redacted error row (L1842).

    Four fields, and none of them can carry a payload: `error_class` is a closed
    enum, `reason` is approved copy written at insert time, and `reference` is
    four hex characters of the request id. There is no field here a caller's
    input could reach.
    """

    occurred_at: dt.datetime
    error_class: str
    reason: str
    reference: str


class ServingErrorsResponse(BaseModel):
    errors: list[ServingErrorBody]


class AuditLogRow(BaseModel):
    """One line of a tenant's own history (L1288).

    Six fields, and the two that are missing are the interesting ones. There is
    no `actor_id`: a tenant learns that *a* platform administrator suspended
    them, never which one, because the identity of a platform employee is not a
    customer-facing fact. There is no `details`: it is the free-form column, and
    free-form is exactly what a redacted view cannot promise about.
    """

    occurred_at: dt.datetime
    actor_type: AuditActor
    action: AuditAction
    resource_type: str
    resource_ref: str | None
    outcome: AuditOutcome


class AuditLogListResponse(BaseModel):
    entries: list[AuditLogRow]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------- platform realm


class PlatformTenantRow(BaseModel):
    """One tenant, as `/admin/tenants` lists it (L1418)."""

    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    status: TenantStatus
    plan_code: str | None
    created_at: dt.datetime


class PlatformTenantListResponse(BaseModel):
    tenants: list[PlatformTenantRow]
    total: int
    limit: int
    offset: int


class TenantStatusSectionData(BaseModel):
    status: TenantStatus
    status_changed_at: dt.datetime | None
    status_reason: str | None
    created_at: dt.datetime
    #: Gate 2's answer, precomputed. The console disables tenant-affecting
    #: controls from this rather than re-deriving the rule from `status`.
    is_operable: bool


class QuotaOverrideBody(BaseModel):
    override_id: uuid.UUID
    usage_type: UsageType
    limit_value: int
    reason: str
    granted_at: dt.datetime
    #: `null` is open-ended, which the console renders as "no end date" — never
    #: as a blank, because an exception with no visible end becomes permanent.
    expires_at: dt.datetime | None


class TenantPlanSectionData(BaseModel):
    plan_id: uuid.UUID | None
    plan_code: str | None
    plan_name: str | None
    assigned_at: dt.datetime | None
    overrides: list[QuotaOverrideBody]


class PlatformUsageRowBody(BaseModel):
    """One aggregate figure. `quantity` is null whenever it was not measured,
    and `measurement_status` says which kind of not-measured it was."""

    tenant_id: uuid.UUID
    tenant_code: str
    period: str
    usage_type: UsageType
    quantity: decimal.Decimal | None
    measurement_status: MeasurementStatus


class TenantUsageSectionData(BaseModel):
    period: str
    rows: list[PlatformUsageRowBody]


class TenantStatusSection(BaseModel):
    granted: bool
    data: TenantStatusSectionData | None = None
    reason: str | None = None


class TenantPlanSection(BaseModel):
    granted: bool
    data: TenantPlanSectionData | None = None
    reason: str | None = None


class TenantUsageSection(BaseModel):
    granted: bool
    data: TenantUsageSectionData | None = None
    reason: str | None = None


class PlatformTenantSections(BaseModel):
    """Three sections, each independently gated (BACKEND_PLAN §12.10, L1436).

    Modelled as three named fields rather than a map so the generated client is
    typed: a console that reads `sections.plan.data.overrides` should not have
    to cast, and a section that changed shape should break the build.
    """

    status: TenantStatusSection
    plan: TenantPlanSection
    usage: TenantUsageSection


class PlatformTenantDetailResponse(BaseModel):
    tenant: PlatformTenantRow
    sections: PlatformTenantSections


class ChangeTenantStatusRequest(_Body):
    """L1420 — the dialog's two fields, and `reason` is required.

    Required on the wire as well as in the form: the status, the actor and the
    timestamp are all mechanical, and the reason is the only part of the audit
    row a person wrote.
    """

    status: TenantStatus
    reason: str = Field(min_length=1, max_length=500)


class AssignPlanRequest(_Body):
    plan_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)


class GrantOverrideRequest(_Body):
    usage_type: UsageType
    #: Zero is legitimate — it withholds a usage type entirely (L1635). The
    #: floor is enforced here as well as in the domain so that a negative
    #: number is a field error rather than a round trip.
    limit_value: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    expires_at: dt.datetime | None = None


class PlatformTenantUsageResponse(BaseModel):
    tenant_id: uuid.UUID
    tenant_code: str
    period: str
    rows: list[PlatformUsageRowBody]


class PlatformUsageListResponse(BaseModel):
    rows: list[PlatformUsageRowBody]
    total: int
    limit: int
    offset: int


class PlanBody(BaseModel):
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    description: str | None
    event_limit: int
    recommendation_limit: int
    training_limit: int
    product_limit: int
    storage_limit_bytes: int
    service_limits: dict[str, Any]
    #: L1439's "whether new assignments are allowed". Named for what it permits
    #: rather than for the column, because `is_active` reads like a statement
    #: about the plan's tenants and is not one.
    accepts_assignments: bool
    assigned_tenants: int


class PlanListResponse(BaseModel):
    plans: list[PlanBody]


class AssignedTenantBody(BaseModel):
    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    status: TenantStatus


class PlanDetailResponse(BaseModel):
    plan: PlanBody
    tenants: list[AssignedTenantBody]


class PlanLimitsBody(_Body):
    """The five limits, all optional on a PATCH and all required on a POST.

    Kept as one nested object rather than five sibling fields so that "absent"
    and "zero" stay distinguishable: zero is a meaningful limit here, and a form
    that omitted a field must not be read as setting it to nothing.
    """

    event_limit: int = Field(ge=0)
    recommendation_limit: int = Field(ge=0)
    training_limit: int = Field(ge=0)
    product_limit: int = Field(ge=0)
    storage_limit_bytes: int = Field(ge=0)


class CreatePlanRequest(_Body):
    plan_code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
    plan_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    limits: PlanLimitsBody
    service_limits: dict[str, Any] = Field(default_factory=dict)


class UpdatePlanRequest(_Body):
    plan_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    limits: PlanLimitsBody | None = None
    service_limits: dict[str, Any] | None = None


class QueueDepthBody(BaseModel):
    running: int
    waiting: int
    #: The configured ceiling, not an observation. `waiting: 6` means something
    #: different at a concurrency of one than at a concurrency of eight.
    concurrency: int


class ReplicaCountBody(BaseModel):
    #: Null when the reconciler has not reported recently enough for the mirror
    #: to be trustworthy. The accompanying `measurement_gaps` entry says so.
    ready: int | None
    desired: int


class TenantWorkloadBody(BaseModel):
    tenant_id: uuid.UUID
    tenant_code: str
    running_jobs: int
    queued_jobs: int
    desired_replicas: int
    ready_replicas: int


class FailureSummaryBody(BaseModel):
    area: FailureArea
    severity: Severity
    count: int


class MeasurementGapBody(BaseModel):
    """A quantity with no value, and the server's sentence for why.

    UC-30's alternative outcome — "Measurement gaps are identified rather than
    hidden" — is this field. The console renders `gap` in warn colour and this
    sentence beside it; it never composes its own explanation.
    """

    quantity: str
    reason: str


class PlatformStatusResponse(BaseModel):
    window_hours: int
    #: Null with a `measurement_gaps` entry when nothing was served in the
    #: window. Never `0.0`, which would read as a total outage.
    serving_availability: float | None
    training_queue: QueueDepthBody
    replicas: ReplicaCountBody
    ingestion_lag_seconds: int
    failures_24h: int
    active_tenants: int
    workload_by_tenant: list[TenantWorkloadBody]
    failure_summary: list[FailureSummaryBody]
    #: Required, never optional — an empty list is the claim that everything on
    #: this board was measured.
    measurement_gaps: list[MeasurementGapBody]


class FailureRowBody(BaseModel):
    """One terminal failure (L1550).

    `tenant_id` is null unless the caller opened the tab from a tenant context.
    The platform role can read the column; the default view redacts it, because
    a severity ranking that named tenants would be a league table of who is
    struggling.
    """

    occurred_at: dt.datetime
    severity: Severity
    area: FailureArea
    summary: str
    reference: str
    tenant_id: uuid.UUID | None


class FailureListResponse(BaseModel):
    failures: list[FailureRowBody]
    total: int
    limit: int
    offset: int


class PlatformAuditLogRow(BaseModel):
    """The tenant row plus the three columns an operator is entitled to.

    `details` is still absent. `FRONTEND_BUILD_PROMPT` L312 lists six columns
    and none of them is a free-form payload; an audit permission is a licence to
    read the history, not whatever a handler once put in a jsonb column.
    """

    occurred_at: dt.datetime
    tenant_id: uuid.UUID | None
    actor_type: AuditActor
    actor_id: str | None
    action: AuditAction
    resource_type: str
    resource_ref: str | None
    outcome: AuditOutcome
    correlation_ref: str | None


class PlatformAuditListResponse(BaseModel):
    entries: list[PlatformAuditLogRow]
    total: int
    limit: int
    offset: int
