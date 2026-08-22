"""The models and the migrations must describe the same database.

Alembic is the only thing that changes the schema — `metadata.create_all` is
never called — so the models can drift without anything failing until a query
does. These tests compare the mapped classes against the live catalogue.

The second half is the one that matters for isolation: every class carrying
`TenantOwned` must map to a table with RLS enabled, forced, and a policy holding
both `USING` and `WITH CHECK`. Adding a tenant-scoped table and forgetting the
policy is then a failing test rather than a silent leak.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from pydantic import BaseModel

from apps.control_api import schemas
from graphrec.db.models.base import Base, TenantOwned

pytestmark = [pytest.mark.isolation, pytest.mark.db]


def _mapped_tables() -> dict[str, type]:
    return {
        mapper.class_.__tablename__: mapper.class_
        for mapper in Base.registry.mappers
        if hasattr(mapper.class_, "__tablename__")
    }


def test_every_mapped_table_exists(owner_engine) -> None:
    with owner_engine.connect() as conn:
        actual = set(sa.inspect(conn).get_table_names(schema="public"))
    missing = set(_mapped_tables()) - actual
    assert not missing, f"mapped but not migrated: {sorted(missing)}"


def test_every_mapped_column_exists_with_the_same_nullability(owner_engine) -> None:
    """A model that thinks a column is optional will write NULL into a NOT NULL."""
    problems: list[str] = []
    with owner_engine.connect() as conn:
        inspector = sa.inspect(conn)
        for table_name, cls in _mapped_tables().items():
            actual = {col["name"]: col for col in inspector.get_columns(table_name)}
            for column in cls.__table__.columns:
                if column.name not in actual:
                    problems.append(f"{table_name}.{column.name} is mapped but not migrated")
                    continue
                if column.nullable != actual[column.name]["nullable"]:
                    problems.append(
                        f"{table_name}.{column.name}: model nullable={column.nullable}, "
                        f"database nullable={actual[column.name]['nullable']}"
                    )
    assert not problems, "\n".join(problems)


def test_every_tenant_owned_model_is_protected(owner_engine) -> None:
    """The structural gate. `TenantOwned` is a claim; this is the check.

    `tenants` is deliberately absent from the mixin — it is scoped by its own
    primary key, not a foreign one — and is asserted separately below.
    """
    owned = [name for name, cls in _mapped_tables().items() if issubclass(cls, TenantOwned)]
    assert owned, "no tenant-owned models were discovered; the mixin check is vacuous"

    with owner_engine.connect() as conn:
        for table_name in owned:
            row = conn.execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = to_regclass(:t)"
                ),
                {"t": f"public.{table_name}"},
            ).one()
            assert row.relrowsecurity, f"{table_name} carries TenantOwned but RLS is not enabled"
            assert row.relforcerowsecurity, f"{table_name} has RLS but not FORCE"

            policies = conn.execute(
                sa.text(
                    "SELECT policyname, qual, with_check FROM pg_policies "
                    "WHERE tablename = :t AND 'graphrec_app' = ANY(roles)"
                ),
                {"t": table_name},
            ).all()
            assert policies, f"{table_name} has no policy for the runtime role"
            for policy in policies:
                assert policy.qual, f"{policy.policyname} on {table_name} has no USING clause"
                assert (
                    policy.with_check
                ), f"{policy.policyname} on {table_name} has no WITH CHECK clause"


def test_the_tenants_table_is_protected_by_its_own_key(owner_engine) -> None:
    with owner_engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = to_regclass('public.tenants')"
            )
        ).one()
        assert row.relrowsecurity
        assert row.relforcerowsecurity

        qual = conn.execute(
            sa.text(
                "SELECT qual FROM pg_policies WHERE tablename = 'tenants' "
                "AND 'graphrec_app' = ANY(roles)"
            )
        ).scalar_one()
    assert "tenant_id" in qual
    assert "app.tenant_id" in qual


def test_no_model_exposes_a_credential_digest_to_a_response(owner_engine) -> None:
    """A digest is not a secret one may publish, and there is no reason to.

    Checked against the response schemas rather than the models: the column has
    to exist, and what must never happen is a schema field of the same name.
    """
    banned = {"credential_digest", "token_digest", "password", "credential_secret"}
    for name in dir(schemas):
        candidate = getattr(schemas, name)
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            if name.endswith("Request"):
                continue  # a request may legitimately carry a password
            leaked = banned & set(candidate.model_fields)
            assert not leaked, f"{name} would publish {sorted(leaked)}"
