"""Writing the history, inside the transaction that makes it true.

Three rules hold everywhere in this module.

**The write joins the caller's transaction.** Nothing here commits. A handler
that rotates a credential and records the rotation does both or neither, so the
history cannot disagree with the state it describes. The cost is that an audit
failure fails the action — which is the right way round: an action nobody can
account for is worse than an action that did not happen.

**The row is written even when the answer is no.** `outcome` has four values and
three of them are refusals. ER-F-11's history is not a log of successes; a
denied plan assignment and a cancelled training run are precisely what someone
comes to this table to find.

**`details` is filtered, not trusted.** It is the one free-form column in the
schema, it is written by a dozen call sites, and it is the only route by which a
secret could reach durable storage through the audit path. The filter reuses
`graphrec.common.logging.SENSITIVE_KEYS` so that the two places a caller can
hand the system a dict are protected by one list.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from graphrec.common.enums import AuditActor, AuditOutcome, FailureArea, Severity
from graphrec.common.ids import new_request_reference
from graphrec.common.logging import SENSITIVE_KEYS, request_id_var
from graphrec.db.models.audit import AuditLog, SecurityEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.common.enums import AuditAction

logger = logging.getLogger("graphrec.audit")

_REDACTED = "[redacted]"

#: How much of a caller-supplied string reaches the column. Details are
#: breadcrumbs — a plan code, a reason, a count — and a caller that passes an
#: entire payload should waste a row, not a page of storage.
_MAX_DETAIL_LENGTH = 500


@dataclass(frozen=True, slots=True)
class Actor:
    """Who acted, in the four kinds the schema knows.

    Constructed through the classmethods rather than directly, so that the
    mapping from "a principal in a handler" to "one of four enum values" is
    written once. A handler picking `AuditActor` itself is a handler that can
    record a platform administrator's action as a tenant user's.
    """

    actor_type: AuditActor
    actor_id: str | None

    @classmethod
    def user(cls, user_id: uuid.UUID | str) -> Actor:
        """A signed-in tenant user — the actor behind every console action."""
        return cls(AuditActor.TENANT_USER, str(user_id))

    @classmethod
    def application(cls, key_id: uuid.UUID | str) -> Actor:
        """A tenant's server calling with an API credential.

        The *credential* id, never the secret and never its prefix: the id is
        stable across a rotation's grace period and identifies which key was
        used without being usable itself.
        """
        return cls(AuditActor.TENANT_APPLICATION, str(key_id))

    @classmethod
    def platform(cls, user_id: uuid.UUID | str) -> Actor:
        """A platform operator. Their id is never shown to a tenant — the
        tenant-facing projection drops `actor_id` entirely."""
        return cls(AuditActor.PLATFORM_ADMINISTRATOR, str(user_id))

    @classmethod
    def system(cls, name: str) -> Actor:
        """A worker, the reconciler, or a scheduled sweep.

        Named rather than identified: "reconciler" is what a person reading the
        history needs, and a process id would be noise by the time they read it.
        """
        return cls(AuditActor.SYSTEM_PROCESS, name)

    @classmethod
    def unauthenticated(cls) -> Actor:
        """Someone who failed gate 1.

        Recorded as an application rather than as a user, because at the point
        of refusal we know a request arrived and nothing else. `actor_id` is
        `None` — inventing one from an unverified email would put a caller's
        input into a column that is read as an identifier.
        """
        return cls(AuditActor.TENANT_APPLICATION, None)


async def record(
    session: AsyncSession,
    *,
    actor: Actor,
    action: AuditAction,
    resource_type: str,
    resource_ref: str | uuid.UUID | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
    tenant_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    occurred_at: dt.datetime | None = None,
) -> AuditLog:
    """Append one row. Returns it, unflushed, in the caller's transaction.

    `tenant_id` is explicit and defaults to `None`, which reads oddly for a
    system whose every other write is tenant-scoped. It is deliberate: this is
    the one table written from both realms, and a platform handler acting on a
    tenant must name that tenant while the row itself belongs to neither. RLS
    then decides who can read it back — a `NULL` row is invisible to every
    tenant, which is how a platform action stays out of a tenant's history
    without any query having to remember to exclude it.

    `correlation_ref` is not a parameter. It is the ambient request id, which
    means a handler cannot forget it and cannot supply a different one; two rows
    written by one request are joinable because they were written by one
    request, not because someone passed the same string twice.
    """
    row = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        action=action.value,
        resource_type=resource_type,
        resource_ref=str(resource_ref) if resource_ref is not None else None,
        outcome=outcome.value,
        correlation_ref=request_id_var.get(),
        details=safe_details(details),
        occurred_at=occurred_at or dt.datetime.now(dt.UTC),
    )
    session.add(row)
    return row


async def security_event(
    session: AsyncSession,
    *,
    severity: Severity,
    area: FailureArea,
    summary: str,
    tenant_id: uuid.UUID | None = None,
    reference: str | None = None,
    occurred_at: dt.datetime | None = None,
) -> SecurityEvent:
    """Append one failure to the Failures tab's table.

    `summary` is system-written prose. Nothing here interpolates a caller's
    input into it, and callers must not either: the Failures tab renders the
    string to a platform operator, and a tenant-supplied fragment would be a
    path from one tenant's data onto that screen.

    `reference` defaults to a freshly minted handle in the console's own
    `err-3f81-7a20c` shape. A caller with a better one — the request reference
    already shown to the tenant — passes it, and the two screens then agree on
    which failure they are discussing.
    """
    row = SecurityEvent(
        tenant_id=tenant_id,
        severity=severity.value,
        area=area.value,
        summary=summary[:500],
        reference=reference or new_request_reference(),
        occurred_at=occurred_at or dt.datetime.now(dt.UTC),
    )
    session.add(row)
    return row


def safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Everything a caller offered, minus what must never be stored.

    A sensitive key is **redacted rather than rejected**. Raising would be the
    louder choice and the wrong one: the exception would surface inside the
    transaction performing a credential rotation, so a mistyped detail key would
    turn a working action into a 500 in production. Redacting keeps the action
    working, keeps the secret out of the table, and leaves a `WARNING` naming
    the key — never the value — for whoever fixes the call site.

    Values are coerced to strings unless they are already JSON scalars, because
    `jsonb` will accept a nested structure and a nested structure is how an
    entire request body ends up in an audit row by accident.
    """
    if not details:
        return {}

    safe: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in SENSITIVE_KEYS:
            logger.warning("audit_detail_redacted", extra={"detail_key": key})
            safe[key] = _REDACTED
            continue
        safe[key] = _scalar(value)
    return safe


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:_MAX_DETAIL_LENGTH]
    if isinstance(value, uuid.UUID | dt.datetime | dt.date):
        return str(value)
    # A list, a dict, a model — flattened to its repr and truncated. The column
    # stays queryable and a careless caller cannot smuggle a payload through a
    # structure `jsonb` would happily have taken.
    return repr(value)[:_MAX_DETAIL_LENGTH]


__all__ = ["Actor", "record", "safe_details", "security_event"]
