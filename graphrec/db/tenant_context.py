"""Binding a transaction to one tenant.

The rule this module exists to enforce (NR-NF-02): **tenant identity comes only
from the verified credential**. Never from a path, a query parameter or a body
field. This module is therefore the only place that writes `app.tenant_id`, and
it takes a `UUID` rather than a string so that a caller cannot hand it something
that arrived as text from a request.

Everything below is `SET LOCAL`. That is not a style preference:

* `SET LOCAL` is reverted when the transaction ends, so a pooled connection
  cannot carry one tenant's context into the next request.
* A plain `SET` persists for the life of the *connection*, which in a pooled
  application means "until some unrelated request picks it up". That failure
  mode returns another tenant's rows with no error and no log line.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from graphrec.db.engine import TENANT_GUC

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


class TenantContextError(RuntimeError):
    """Raised when a tenant-scoped operation is attempted without a context.

    Deliberately not a `GraphRecError`: it never reaches a tenant, because it can
    only be caused by a programming mistake on our side. It surfaces as a 500
    with a reference, which is the correct outcome — the alternative is a query
    that quietly returns nothing and looks like an empty account.
    """


async def bind_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Bind the current transaction to `tenant_id`.

    Must be called inside a transaction. `SET LOCAL` outside one is silently
    discarded by PostgreSQL with only a warning, which would leave the policies
    resolving `NULL` and every query returning nothing — a confusing outage that
    looks like data loss. So the transaction is asserted rather than assumed.
    """
    if not isinstance(tenant_id, UUID):  # pragma: no cover - defensive
        raise TypeError("tenant_id must be a UUID, never a value taken from a request")
    if not session.in_transaction():
        raise TenantContextError(
            "bind_tenant requires an open transaction; SET LOCAL outside one is discarded"
        )
    # Parameterised through set_config rather than interpolated into SET LOCAL,
    # which takes no parameters.
    await session.execute(
        text(f"SELECT set_config('{TENANT_GUC}', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def current_tenant(session: AsyncSession) -> UUID | None:
    """What the database believes the current tenant to be.

    Reads the GUC back rather than returning what the application thinks it set,
    so a test asserting isolation is asserting the server's view.
    """
    raw = await session.scalar(text(f"SELECT current_setting('{TENANT_GUC}', true)"))
    return UUID(raw) if raw else None


@asynccontextmanager
async def tenant_transaction(session: AsyncSession, tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Open a transaction already bound to a tenant.

    This is the intended entry point for request handling: acquiring a session
    and binding it are one step, so there is no window in which a session is
    usable but unbound.
    """
    async with session.begin():
        await bind_tenant(session, tenant_id)
        yield session
