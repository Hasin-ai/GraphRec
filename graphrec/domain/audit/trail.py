"""One handler-facing object, and the transaction problem it exists to solve.

An audit row for a *successful* action belongs in that action's transaction:
both or neither, no window in which the credential exists and its record does
not. An audit row for a *refused* action cannot be, and the reason is
mechanical rather than philosophical. A refusal raises, the raise unwinds the
request's `session.begin()`, and the rollback takes every statement in that
transaction with it — including the row explaining why the request was refused.
Writing the refusal into the doomed transaction produces no row at all.

So refusals are written on a second connection, in their own short transaction,
and committed immediately. Two consequences, both accepted deliberately:

* A refusal row can survive a request that later fails for an unrelated reason.
  A history that records an attempt that was refused twice, once spuriously, is
  strictly better than one that silently drops refusals — and the refusals are
  the rows an investigation is looking for.
* The write costs a connection from the pool on a path that has already
  decided to fail. That is the cheap direction: refusals are rare, and the
  alternative is a security-relevant blind spot on every denied request.

**An audit write never converts a refusal into a fault.** `denied` swallows its
own exceptions after logging them. If the audit table is unreachable the tenant
still receives their 409 with the approved copy; what they must never receive is
a 500 caused by the machinery that was supposed to be watching.

Usage, in a handler that already has a principal:

    async with audit.action(AuditAction.CREDENTIAL, resource_type="api_key") as entry:
        issued = await service.create(...)
        entry.resource_ref = issued.api_key.key_id
        entry.details = {"name": body.name}

The success row is staged on the request's session; a `GraphRecError` raised
inside the block writes a `denied` (or `failed`) row elsewhere and re-raises
untouched.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from graphrec.common.enums import AuditOutcome
from graphrec.common.errors import (
    AuthError,
    ConflictError,
    ForbiddenError,
    GraphRecError,
    LimitError,
    NotFoundError,
    ValidationError,
)
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.audit.record import Actor, record

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from graphrec.common.enums import AuditAction

logger = logging.getLogger("graphrec.audit")


@dataclass
class Entry:
    """The mutable part of an audit row, filled in as the handler learns it.

    A handler rarely knows the resource reference before it has done the work —
    a credential's id exists only once it is issued — so the reference and the
    details are set on the way out rather than passed on the way in.
    """

    resource_ref: str | uuid.UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)
    outcome: AuditOutcome = AuditOutcome.SUCCEEDED


@dataclass(slots=True)
class AuditTrail:
    """A principal's audit writer, bound to their session and their realm.

    `tenant_id` is `None` for a platform operator acting on nothing in
    particular, and set for a platform operator acting on a tenant — the column
    means "the tenant this concerns", so a suspension names its subject while
    remaining invisible to that subject's own audit page.

    Mutable, unlike almost everything else in the domain, because one caller
    genuinely learns who it is talking about part-way through: sign-in resolves
    the tenant from a code and the actor from a password check, and both facts
    arrive after the trail has to exist. A handler that knows its subject up
    front should use `concerning()` and leave the instance alone.
    """

    session: AsyncSession
    sessionmaker: async_sessionmaker[AsyncSession]
    actor: Actor
    tenant_id: uuid.UUID | None = None

    def concerning(self, tenant_id: uuid.UUID | None) -> AuditTrail:
        """The same trail, pointed at a tenant. For platform handlers, which
        learn their subject from the path rather than from their token."""
        return AuditTrail(
            session=self.session,
            sessionmaker=self.sessionmaker,
            actor=self.actor,
            tenant_id=tenant_id,
        )

    @contextlib.asynccontextmanager
    async def action(
        self,
        action: AuditAction,
        *,
        resource_type: str,
        resource_ref: str | uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> AsyncIterator[Entry]:
        """Record what happens in this block, whichever way it goes."""
        entry = Entry(resource_ref=resource_ref, details=dict(details or {}))
        try:
            yield entry
        except GraphRecError as exc:
            await self.refused(
                action,
                resource_type=resource_type,
                resource_ref=entry.resource_ref,
                error=exc,
                details=entry.details,
            )
            raise
        await record(
            self.session,
            actor=self.actor,
            action=action,
            resource_type=resource_type,
            resource_ref=entry.resource_ref,
            outcome=entry.outcome,
            tenant_id=self.tenant_id,
            details=entry.details,
        )

    async def refused(
        self,
        action: AuditAction,
        *,
        resource_type: str,
        resource_ref: str | uuid.UUID | None = None,
        error: GraphRecError,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Write the refusal on a connection that is not about to roll back.

        The machine code goes into `details`, never the resolved copy. The copy
        is product wording that changes; the code is the stable thing a support
        query filters on, and it is already what the response carries.
        """
        payload = dict(details or {})
        payload["code"] = error.code
        try:
            async with self.sessionmaker() as session, session.begin():
                if self.tenant_id is not None:
                    await bind_tenant(session, self.tenant_id)
                await record(
                    session,
                    actor=self.actor,
                    action=action,
                    resource_type=resource_type,
                    resource_ref=resource_ref,
                    outcome=_outcome_for(error),
                    tenant_id=self.tenant_id,
                    details=payload,
                )
        except Exception:  # pragma: no cover - defensive
            # Deliberately broad, and deliberately silent to the caller. The
            # request is already failing with a message the tenant is meant to
            # see; replacing it with a 500 from the audit path would hide the
            # real refusal behind a fault nobody can act on.
            logger.exception("audit_refusal_write_failed", extra={"action": action.value})


def _outcome_for(error: GraphRecError) -> AuditOutcome:
    """Three refusal outcomes, and the difference between them matters.

    `denied` is "you were not allowed to" — gate 3, gate 1, and gate 4's
    deliberately-indistinguishable 404, which is a permission answer wearing a
    404's clothes. `cancelled` is "the state said no": a conflict, a validation
    refusal or a quota, all of which are the system declining a request it
    understood. Everything else is `failed`, which is the honest label for a
    fault — we did not refuse, we broke.
    """
    if isinstance(error, ForbiddenError | AuthError | NotFoundError):
        return AuditOutcome.DENIED
    if isinstance(error, ConflictError | ValidationError | LimitError):
        return AuditOutcome.CANCELLED
    return AuditOutcome.FAILED


__all__ = ["Actor", "AuditTrail", "Entry"]
