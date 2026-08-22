"""The declarative base, and the mixin that marks a table tenant-owned.

`TenantOwned` is not decoration. Phase 2's structural test walks every mapped
class carrying it and asserts the corresponding table has RLS enabled, forced,
and a policy with both `USING` and `WITH CHECK`. Adding a tenant-scoped table
without the mixin is therefore caught by a failing test rather than by a leak.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import DateTime, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Explicit naming, so a constraint added by a model and one added by a
#: migration end up with the same name rather than two spellings of one idea.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        uuid.UUID: UUID(as_uuid=True),
        dict[str, Any]: JSONB,
        dt.datetime: DateTime(timezone=True),
    }


class TenantOwned:
    """Declares `tenant_id`, and asserts the row is reachable only in context.

    Every class mixing this in is subject to a policy of the form
    `tenant_id = current_setting('app.tenant_id', true)::uuid`. Note what happens
    when the setting is absent: `current_setting(..., true)` yields NULL, the
    comparison yields NULL rather than TRUE, and the row is filtered out. Absence
    of context therefore denies by default — no row is visible to a connection
    that forgot to bind, rather than every row being visible.
    """

    @property
    def __tenant_column__(self) -> str:
        return "tenant_id"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def utcnow_column() -> Mapped[dt.datetime]:
    return mapped_column(server_default=func.now(), nullable=False)


def pk_uuid() -> Mapped[uuid.UUID]:
    """A primary key the database can also mint on its own.

    The application supplies UUIDv7 identifiers (`graphrec.common.ids`); the
    server default exists so a hand-written repair INSERT is not obliged to.
    """
    return mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
