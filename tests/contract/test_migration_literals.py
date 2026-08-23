"""Migrations spell their enums out; this is what keeps the spellings honest.

A migration cannot import `graphrec.common.enums`. It runs against whatever
version of the schema is in front of it, and a check constraint that changed
meaning because someone edited a Python enum three releases later would rewrite
history rather than extend it. So the literals are copied into each migration
and deliberately frozen there.

Copying has a cost, and this file is the payment. A value added to an enum
without a migration reaches the database as a constraint violation — at runtime,
in production, on the one tenant who used the new option first. Here it is a
failing test with both lists printed side by side.

The direction is one-way on purpose. The migration is the older statement and
the application must match *it*: if this fails, the fix is almost always a new
migration, not an edit to the constants below. Where a value is genuinely
retired, the migration that retires it is the place that says so.

Migration 0009's docstring names this file. It exists because that citation was
made — and because 0007 and 0008 made the same claim earlier with no file behind
it, which is exactly the kind of debt a comment can carry indefinitely.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

from graphrec.catalog.eligibility import Ineligibility
from graphrec.common.enums import (
    EventType,
    MeasurementStatus,
    SubmissionKind,
    SubmissionStatus,
    UsageType,
)

#: `(migration module, constant, the enum it must equal)`.
#: Order within the tuple matters as much as membership: a check constraint
#: lists its values, and a reordering here is a signal that the enum was edited
#: rather than extended.
PINNED = [
    ("0007_catalog", "AVAILABILITY", "Availability"),
    ("0007_catalog", "INELIGIBILITY_CODES", Ineligibility),
    ("0008_ingestion", "EVENT_TYPES", EventType),
    ("0008_ingestion", "SUBMISSION_KINDS", SubmissionKind),
    ("0008_ingestion", "SUBMISSION_STATUSES", SubmissionStatus),
    ("0009_metering", "USAGE_TYPES", UsageType),
    ("0009_metering", "MEASUREMENT_STATUSES", MeasurementStatus),
    ("0010_training", "TRAINING_STATES", "JobState"),
    ("0011_registry", "VERSION_STATUSES", "ModelVersionStatus"),
]


def _enum(spec):
    if isinstance(spec, str):
        from graphrec.common import enums

        return getattr(enums, spec)
    return spec


@pytest.mark.parametrize(("module", "constant", "enum"), PINNED)
def test_a_migration_s_literals_match_the_application_s_enum(module, constant, enum) -> None:
    """The one assertion this file exists for.

    Failing here means the database will refuse a value the application is
    already willing to produce (or the reverse, which is quieter and worse: an
    option the database accepts that no code path can ever write).
    """
    migration = importlib.import_module(f"migrations.versions.{module}")
    literals = getattr(migration, constant)
    expected = tuple(member.value for member in _enum(enum))

    assert literals == expected, (
        f"{module}.{constant} is {literals!r}; "
        f"{_enum(enum).__name__} is {expected!r}. "
        "Add a migration rather than editing the constant."
    )


@pytest.mark.parametrize(("module", "constant", "enum"), PINNED)
def test_a_pinned_constant_is_wired_into_the_ddl(module, constant, enum) -> None:
    """A constant nothing uses would satisfy the test above while constraining
    nothing at all.

    Two shapes count as wired in, because the migrations use both. Most build
    an `IN` list from the constant, so its *name* appears in `upgrade`. 0007's
    `product_ineligibility` spells its codes into a function body instead, so
    its *values* appear and its name does not. Either is the database
    constraining the value; a constant doing neither is a comment.

    Read from source rather than executed: the claim is about what the DDL says,
    and that is visible without a database.
    """
    migration = importlib.import_module(f"migrations.versions.{module}")
    source = pathlib.Path(migration.__file__).read_text(encoding="utf-8")
    body = source.split("def upgrade", 1)[1]
    values = getattr(migration, constant)

    by_name = constant in body
    by_value = all(f"'{value}'" in body for value in values)

    assert by_name or by_value, (
        f"{module}.{constant} is declared but neither named in upgrade() "
        "nor spelled into its SQL"
    )
