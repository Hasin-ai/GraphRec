"""Fixtures for the isolation suite.

Every test here connects as a **real runtime role** — `graphrec_app` or
`graphrec_platform` — never as the migration owner. That is the entire point. An
isolation test run as the owner tests nothing: the owner is exempt from its own
policies unless they are `FORCE`d, and even then it holds grants no request ever
should.

Seed data is written **as `graphrec_app`, one tenant at a time**, using exactly
the manoeuvre production uses to register a tenant: mint the identifier, bind
`app.tenant_id` to it, then insert. It is worth being clear about why, because
the obvious alternative — seed as the owner — does not work and should not.

`tenants` carries `FORCE ROW LEVEL SECURITY`, so the owner is subject to the
policies too, and no policy names the owner. That is the point of `FORCE`; the
inconvenience here is the feature working. Seeding through the runtime path
instead means the fixture proves something on its way to the tests: that a
tenant can be created at all under RLS, and that creating one grants no sight of
any other.

Teardown is the one place the escape hatch appears, and it is deliberately loud.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Iterator

TENANT_GUC = "app.tenant_id"


def _url_for(role: str, password: str) -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    return f"postgresql+psycopg://{role}:{password}@{tail}"


@pytest.fixture(scope="session")
def app_engine(owner_engine):
    """A connection as `graphrec_app` — the role that serves tenant traffic."""
    engine = sa.create_engine(
        _url_for(
            "graphrec_app", os.environ.get("POSTGRES_APP_PASSWORD", "graphrec_app_local_only")
        ),
        poolclass=sa.pool.NullPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def platform_engine(owner_engine):
    """A connection as `graphrec_platform` — the role that serves /v1/platform/*."""
    engine = sa.create_engine(
        _url_for(
            "graphrec_platform",
            os.environ.get("POSTGRES_PLATFORM_PASSWORD", "graphrec_platform_local_only"),
        ),
        poolclass=sa.pool.NullPool,
    )
    yield engine
    engine.dispose()


@contextlib.contextmanager
def _force_lifted(conn, table: str) -> Iterator[None]:
    """Briefly lift `FORCE ROW LEVEL SECURITY` so the owner can clean up.

    No role holds `DELETE` on `tenants` — SRS §5.2.2 makes tenant removal a
    lifecycle transition, not a row disappearing — and the owner is fenced out by
    `FORCE`. Test teardown is the legitimate exception, and this is the procedure
    migration 0002 documents for it: lift, act, restore, in one transaction.

    It lives in a `finally` and nowhere else. If this ever appears outside a
    fixture teardown, something has gone wrong.
    """
    conn.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    try:
        yield
    finally:
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


@pytest.fixture(scope="session")
def two_tenants(app_engine, owner_engine) -> Iterator[dict[str, uuid.UUID]]:
    """Two tenants, each with one administrator.

    Named after the question every test below asks: given two, can either see the
    other? The identifiers are random per run so a leak cannot be masked by a row
    left behind from a previous one.
    """
    ids = {
        "alpha": uuid.uuid4(),
        "beta": uuid.uuid4(),
        "alpha_user": uuid.uuid4(),
        "beta_user": uuid.uuid4(),
    }
    suffix = uuid.uuid4().hex[:8]

    for name in ("alpha", "beta"):
        # One transaction per tenant, each bound to that tenant only. Two tenants
        # cannot be seeded in a single bound transaction, which is the constraint
        # working rather than an awkwardness to route around.
        with app_engine.connect() as conn, conn.begin():
            conn.execute(
                sa.text(f"SELECT set_config('{TENANT_GUC}', :tid, true)"),
                {"tid": str(ids[name])},
            )
            plan_id = conn.execute(
                sa.text("SELECT plan_id FROM pricing_plans WHERE plan_code = 'GROWTH'")
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO tenants (tenant_id, plan_id, tenant_code, tenant_name, status) "
                    "VALUES (:tid, :plan, :code, :name, 'active')"
                ),
                {
                    "tid": ids[name],
                    "plan": plan_id,
                    "code": f"{name[:3].upper()}-{suffix}",
                    "name": f"{name.title()} Supply {suffix}",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO tenant_users (tenant_user_id, tenant_id, email, display_name, "
                    "credential_digest, role, status) VALUES (:uid, :tid, :email, :dn, "
                    "'$argon2id$not-a-real-digest', 'tenant_administrator', 'active')"
                ),
                {
                    "uid": ids[f"{name}_user"],
                    "tid": ids[name],
                    "email": f"admin@{name}-{suffix}.example",
                    "dn": f"{name.title()} Administrator",
                },
            )

    yield ids

    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        # Children go with them: every tenant-owned table references
        # `tenants.tenant_id` with ON DELETE CASCADE, and referential integrity
        # is exempt from row security, so one statement is enough.
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id IN (:a, :b)"),
            {"a": ids["alpha"], "b": ids["beta"]},
        )


@pytest.fixture
def as_tenant(app_engine):
    """Run a statement as `graphrec_app`, bound to one tenant, in a transaction.

    Mirrors production exactly: `SET LOCAL` inside the transaction, from a UUID,
    never a string taken from a request.
    """

    def _run(tenant_id: uuid.UUID | None, statement: str, **params: object) -> list[sa.Row]:
        with app_engine.connect() as conn, conn.begin():
            if tenant_id is not None:
                conn.execute(
                    sa.text(f"SELECT set_config('{TENANT_GUC}', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
            return list(conn.execute(sa.text(statement), params))

    return _run
