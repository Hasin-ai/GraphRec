"""Request and response bodies.

Field names are snake_case on the wire (D11). Two rules hold throughout:

* A response never contains a credential digest, a token digest, or a
  `tenant_id` belonging to anyone but the caller.
* A request never contains a `tenant_id`. Tenant scope comes from the verified
  credential; a body field would be a second, forgeable source for it.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from graphrec.common.enums import TenantRole, UserStatus


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
