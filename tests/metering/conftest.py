"""Fixtures for the metering suite.

Metering has no seeding of its own. Every one of its numbers is produced by
something else — an accepted event, a merged catalogue, a plan assigned at
registration — so the fixtures it needs are precisely the ingestion suite's, and
they are re-exported rather than rebuilt.

Two things are added here. `plan_limit` rewrites the tenant's plan bound so a
quota can be reached in a test without submitting six million events, and
`grant_override` installs the `quota_overrides` row that has to win against it.
Both write as the migration owner, because a plan is not tenant-owned and an
override is granted by the platform, not by the tenant it applies to.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import NullPool

from graphrec.domain.metering.counters import InMemoryUsageCounters
from tests.ingestion.conftest import (  # noqa: F401
    _app_url,
    _empty_ingestion,
    api,
    bound,
    drain,
    home_admin,
    home_dev,
    ingest_sessionmaker,
    ingest_tenants,
    other_admin,
    realm,
    seed_engine,
    seed_products,
    tenant,
)
from tests.isolation.conftest import (
    _force_lifted,
    app_engine,  # noqa: F401
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from graphrec.common.enums import UsageType
    from graphrec.domain.metering.periods import Period

pytestmark = [pytest.mark.db]

#: Fixed so that a period boundary is a decision in the test rather than a
#: property of the day it runs on.
NOW = dt.datetime(2026, 8, 14, 9, 41, 2, tzinfo=dt.UTC)


@pytest.fixture
def counters() -> InMemoryUsageCounters:
    """Cold counters, per test.

    Cold rather than pre-seeded, because the interesting property is what a miss
    does: `counters.current` must repair from the ledger, and a fixture that
    handed out a warm cache would hide the one path that could silently answer
    zero.
    """
    return InMemoryUsageCounters()


@pytest.fixture
def plan_limit(owner_engine):
    """Move a tenant's plan bound for one or more usage types.

    Writes a private plan and repoints the tenant at it rather than editing
    GROWTH in place: `pricing_plans` is shared, and a test that lowered the
    event limit on the plan every other tenant is on would be a test that
    changes other tests.

    Teardown puts the tenant back on GROWTH before dropping the private plan,
    because `tenants.plan_id` is a foreign key and the tenant outlives this
    fixture.
    """
    created: list[tuple[uuid.UUID, uuid.UUID]] = []

    def _set(tenant_id: uuid.UUID, **limits: int) -> None:
        columns = ", ".join(f"{name} = :{name}" for name in limits)
        plan_id = uuid.uuid4()
        with owner_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO pricing_plans (plan_id, plan_code, plan_name, event_limit, "
                    "  recommendation_limit, training_limit, product_limit, storage_limit_bytes) "
                    "SELECT :new_id, :code, plan_name, event_limit, recommendation_limit, "
                    "       training_limit, product_limit, storage_limit_bytes "
                    "FROM pricing_plans WHERE plan_code = 'GROWTH'"
                ),
                {"new_id": plan_id, "code": f"TEST-{plan_id.hex[:8].upper()}"},
            )
            conn.execute(
                sa.text(f"UPDATE pricing_plans SET {columns} WHERE plan_id = :plan_id"),
                {**limits, "plan_id": plan_id},
            )
            with _force_lifted(conn, "tenants"):
                conn.execute(
                    sa.text("UPDATE tenants SET plan_id = :plan_id WHERE tenant_id = :tid"),
                    {"plan_id": plan_id, "tid": tenant_id},
                )
        created.append((tenant_id, plan_id))

    yield _set

    for tenant_id, plan_id in created:
        with owner_engine.begin() as conn:
            with _force_lifted(conn, "tenants"):
                conn.execute(
                    sa.text(
                        "UPDATE tenants SET plan_id = "
                        "  (SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH') "
                        "WHERE tenant_id = :tid"
                    ),
                    {"tid": tenant_id},
                )
            conn.execute(
                sa.text("DELETE FROM pricing_plans WHERE plan_id = :plan_id"),
                {"plan_id": plan_id},
            )


@pytest.fixture
def grant_override(owner_engine) -> Callable[..., None]:
    """Install an active quota override, the way a platform administrator would."""

    def _grant(
        tenant_id: uuid.UUID,
        usage_type: str,
        limit_value: int,
        *,
        reason: str = "Approved for a seasonal peak.",
        expires_at: dt.datetime | None = None,
        revoked_at: dt.datetime | None = None,
    ) -> None:
        with owner_engine.begin() as conn, _force_lifted(conn, "quota_overrides"):
            conn.execute(
                sa.text(
                    "INSERT INTO quota_overrides (override_id, tenant_id, usage_type, "
                    "  limit_value, reason, granted_by, granted_at, expires_at, revoked_at) "
                    "VALUES (gen_random_uuid(), :tid, :type, :limit, :reason, "
                    "        gen_random_uuid(), :granted_at, :expires_at, :revoked_at)"
                ),
                {
                    "tid": tenant_id,
                    "type": usage_type,
                    "limit": limit_value,
                    "reason": reason,
                    "granted_at": NOW - dt.timedelta(days=1),
                    "expires_at": expires_at,
                    "revoked_at": revoked_at,
                },
            )

    return _grant


@pytest.fixture(scope="session")
def app_reader() -> Iterator[sa.Engine]:
    """A synchronous engine as `graphrec_app`.

    `tests.isolation.conftest.app_engine` is the same thing, and is not
    re-exported here: a fixture whose name is also a parameter of another
    fixture in this module reads as a redefinition, and renaming the parameter
    to dodge that would be worse than owning six lines.
    """
    engine = sa.create_engine(_app_url(), poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def tenant_scalar(app_reader: sa.Engine) -> Callable[..., object]:
    """One scalar query, as `graphrec_app`, inside a tenant's own context.

    Assertions about stored rows have to be made through the tenant's policy
    rather than as the migration owner: `FORCE ROW LEVEL SECURITY` fences the
    owner out of these tables too, so an owner-side `count(*)` answers zero and
    a test asserting "nothing was written" would pass without ever writing
    anything of its own.

    Synchronous on purpose. The tests that need it drive the app through the
    blocking `TestClient`, and spinning up an event loop per assertion inside a
    synchronous test leaves loops and sockets behind for the garbage collector
    to complain about.
    """

    def _scalar(tenant_id: uuid.UUID, sql: str, **params: object) -> object:
        with app_reader.begin() as conn:
            conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            return conn.execute(sa.text(sql), params).scalar()

    return _scalar


@pytest.fixture
def ledger_total(tenant_scalar) -> Callable[..., decimal.Decimal]:
    """The durable sum for one tenant and one usage type, over one period.

    Read as the application role, under the tenant's policy, because a total the
    owner can see and the application cannot is not a total.
    """

    def _total(tenant_id: uuid.UUID, usage_type: UsageType, period: Period) -> decimal.Decimal:
        start, end = period.bounds()
        return decimal.Decimal(
            str(
                tenant_scalar(
                    tenant_id,
                    "SELECT COALESCE(SUM(quantity), 0) FROM usage_events "
                    "WHERE usage_type = :type AND occurred_at >= :start AND occurred_at < :end",
                    type=usage_type.value,
                    start=start,
                    end=end,
                )
            )
        )

    return _total
