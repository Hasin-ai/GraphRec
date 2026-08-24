"""The §9.4 failure table, held to the drills that rehearse it.

§24 asks that "every failure mode in §9.4 has a documented, rehearsed recovery".
The documentation is `docs/RUNBOOKS.md`, already checked by
`tests/observability/test_runbooks.py`. The rehearsal is this file's business.

**A drill is a test that causes the failure, not a test that asserts near it.**
That distinction is why the ledger below names test node ids instead of a
checkbox: a node id can be run, and a node id that has been renamed away fails
here rather than quietly leaving a row of the table unrehearsed.

The other half is `UNDRILLED`. Three of the nine rows describe a whole host
disappearing, which no in-process suite can cause, and one of them —  `N1 down`
— is a row where the plan currently claims *more than the implementation does*.
Recording those as an explicit list, with the reason, is the point: a failure
mode that is neither drilled nor written down as undrilled is one somebody
believes is covered. `docs/PRODUCTION_READINESS.md` repeats these verbatim.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "BACKEND_PLAN.md"
READINESS = ROOT / "docs" / "PRODUCTION_READINESS.md"

pytestmark = pytest.mark.contract

#: §9.4 failure → the drills that cause it. Paths are relative to the repository
#: root; the names are test functions that must exist in them.
DRILLS: dict[str, tuple[tuple[str, str], ...]] = {
    "Postgres crash": (
        # The recovery half — `restart: always` and WAL replay — is Postgres's
        # own and is not rehearsed here. What is: the platform reports the
        # database as unreachable rather than hanging on it or leaking the DSN
        # into an unauthenticated body.
        ("tests/api/test_health.py", "test_a_failed_probe_does_not_leak_connection_details"),
        ("tests/api/test_health.py", "test_the_probes_run_concurrently"),
    ),
    "Redis crash": (
        ("tests/metering/test_counters.py", "test_an_unreachable_cache_degrades_to_the_ledger"),
        ("tests/api/test_health.py", "test_a_hanging_dependency_is_reported_not_waited_on"),
    ),
    "Object store failure": (
        (
            "tests/api/test_health.py",
            "test_an_unreachable_object_store_is_a_failure_not_a_degradation",
        ),
        (
            "tests/serving/test_drills.py",
            "test_the_fallback_lane_carries_traffic_with_the_model_store_unreachable",
        ),
        (
            "tests/serving/test_drills.py",
            "test_the_replica_says_it_is_unready_while_it_serves_the_fallback",
        ),
        (
            "tests/serving/test_drills.py",
            "test_a_caller_who_declines_the_fallback_is_refused_rather_than_served_stale",
        ),
        ("tests/serving/test_binding.py", "test_a_missing_artifact_is_a_refusal_and_not_a_crash"),
    ),
    "Training crash": (
        ("tests/jobs/test_lease.py", "test_a_killed_workers_job_requeues_automatically"),
        ("tests/jobs/test_lease.py", "test_a_requeued_job_is_claimable_by_another_worker"),
        ("tests/jobs/test_lease.py", "test_the_replaced_worker_cannot_write_its_result"),
        ("tests/jobs/test_lease.py", "test_repeated_expiry_eventually_gives_up"),
    ),
    "Activation failure": (
        (
            "tests/serving/test_activation.py",
            "test_a_failed_activation_leaves_the_previous_version_serving",
        ),
    ),
    "N2 down": (("tests/jobs/test_lease.py", "test_a_killed_workers_job_requeues_automatically"),),
}

#: §9.4 failure → why no automated drill causes it.
UNDRILLED: dict[str, str] = {
    "N1 down": (
        "Requires three hosts, and the row overstates what this implementation "
        "does: every recommendation lane reads Postgres, which runs on N1, so "
        "with N1 gone N3 returns errors rather than degrading to the popularity "
        "lane. Recorded as a deviation rather than drilled into a pass."
    ),
    "N3 down": (
        "Requires three hosts. The recovery ('restart; inference reloads "
        "bundles') is the same code path the object-store drills above cause "
        "at start-up, which is the part a single process can rehearse."
    ),
    "Disk exhaustion": (
        "Filling a disk to prove an alert threshold is a drill that damages the "
        "machine it runs on. The alert rule is asserted in "
        "tests/observability/test_alert_rules.py and the lifecycle rules that are the "
        "primary defence are asserted in the storage suite."
    ),
}


def _table_rows() -> list[str]:
    """The first column of §9.4's table, which is the list of failure modes."""
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("### 9.4 Failure posture")
    section = text[start : text.index("\n## ", start)]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cell = line.strip("|").split("|")[0].strip()
        if cell in {"Failure", ""} or set(cell) <= set("-: "):
            continue
        rows.append(cell)
    return rows


@pytest.fixture(scope="module")
def failures() -> list[str]:
    return _table_rows()


def test_it_found_the_table_it_is_supposed_to_be_checking(failures) -> None:
    """The floor. An empty parse passes every test below."""
    assert len(failures) >= 9, f"§9.4 parsed to {failures}"
    assert "Object store failure" in failures


def test_every_failure_mode_is_either_drilled_or_declared_undrilled(failures) -> None:
    accounted = set(DRILLS) | set(UNDRILLED)
    missing = [failure for failure in failures if failure not in accounted]
    assert not missing, (
        f"§9.4 lists failure modes with neither a drill nor a recorded reason: {missing}. "
        "Add a drill to DRILLS or an honest sentence to UNDRILLED — a row in neither "
        "is a failure mode somebody believes is covered."
    )


def test_the_ledger_names_no_failure_mode_the_plan_dropped(failures) -> None:
    """The other direction. A drill for a failure that no longer exists is a
    drill nobody will re-read, and it makes the count look better than it is."""
    stale = sorted((set(DRILLS) | set(UNDRILLED)) - set(failures))
    assert not stale, f"drills for failure modes §9.4 no longer lists: {stale}"


def test_nothing_is_both_drilled_and_excused() -> None:
    overlap = sorted(set(DRILLS) & set(UNDRILLED))
    assert not overlap, f"both drilled and declared undrilled: {overlap}"


@pytest.mark.parametrize(
    ("path", "name"),
    sorted({drill for drills in DRILLS.values() for drill in drills}),
)
def test_every_named_drill_exists(path: str, name: str) -> None:
    """Names, checked against the source rather than against a memory of it.

    Parsed rather than imported: importing the serving suite pulls in fixtures
    that want a database, and this file is a bookkeeping check that should run
    without one.
    """
    source = ROOT / path
    assert source.exists(), f"{path} does not exist"
    pattern = rf"^(?:async )?def {re.escape(name)}\("
    assert re.search(
        pattern, source.read_text(encoding="utf-8"), re.MULTILINE
    ), f"{path} does not define {name} — a renamed drill leaves a §9.4 row unrehearsed"


def test_the_readiness_document_repeats_every_excuse() -> None:
    """The undrilled rows have to be readable by someone who is not reading tests.

    §24 is walked in `docs/PRODUCTION_READINESS.md`, and the boxes this file
    cannot tick are exactly the boxes that document must not tick either.
    """
    text = READINESS.read_text(encoding="utf-8")
    for failure in UNDRILLED:
        assert (
            failure in text
        ), f"{failure!r} is undrilled but PRODUCTION_READINESS.md does not mention it"
