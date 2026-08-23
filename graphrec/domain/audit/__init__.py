"""The durable history: who did what, and what went wrong.

Two responsibilities, deliberately kept apart from every module that calls them.

`record` is the **writer**. It is called from inside the transaction that
performs the thing being recorded, which is what makes "the action happened and
the audit row exists" a single fact rather than two facts that usually agree. A
credential rotation that commits without its audit row, or an audit row that
survives a rolled-back rotation, would both be lies of the kind an investigation
cannot recover from.

`query` is the **reader**, and it exists as a module because the same table is
read by two audiences with different rights. A tenant sees five columns of its
own history. A platform operator sees more columns across every tenant. Writing
those two projections in the routers would put the redaction rule next to the
serialisation instead of next to the query, and the redaction rule is the part
that must never be got wrong.
"""

from graphrec.domain.audit.query import (
    AuditPage,
    AuditRow,
    FailurePage,
    FailureRow,
    PlatformAuditRow,
    failures,
    platform_page,
    tenant_page,
)
from graphrec.domain.audit.record import Actor, record, security_event
from graphrec.domain.audit.trail import AuditTrail, Entry

__all__ = [
    "Actor",
    "AuditPage",
    "AuditRow",
    "AuditTrail",
    "Entry",
    "FailurePage",
    "FailureRow",
    "PlatformAuditRow",
    "failures",
    "platform_page",
    "record",
    "security_event",
    "tenant_page",
]
