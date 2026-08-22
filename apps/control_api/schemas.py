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
    Availability,
    CredentialScope,
    CredentialState,
    SubmissionKind,
    SubmissionStatus,
    TenantRole,
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
    tenant_user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    created_at: dt.datetime
    last_authenticated_at: dt.datetime | None = None


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


class ChangeRoleRequest(_Body):
    role: TenantRole


class ChangeStatusRequest(_Body):
    status: UserStatus


class UserListResponse(BaseModel):
    users: list[UserResponse]


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
