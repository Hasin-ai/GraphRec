"""The bucket lifecycle configuration, and the boundary it must not cross.

The rule this applies is small. The rule it must never grow into is not: a
lifecycle rule that expires `tenants/` would take every served bundle with it,
and the failure would be invisible for as long as it takes a replica to restart
— the registry row still says ACTIVE, the console still shows a model, and the
first symptom is a tenant permanently on the popularity lane.

So this asserts what the configuration does *and* what it may not touch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def lifecycle():
    spec = importlib.util.spec_from_file_location(
        "ops_lifecycle", ROOT / "scripts" / "ops" / "lifecycle.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ops_lifecycle"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["ops_lifecycle"]


def test_it_aborts_incomplete_uploads(lifecycle) -> None:
    """§9.4's disk exhaustion, at the one place a rule can reach it.

    Orphaned multipart parts are not objects: they appear in no listing, in no
    `du`, and in no dashboard. The volume fills and nothing says why.
    """
    rules = lifecycle.configuration()["Rules"]
    abort = [rule for rule in rules if "AbortIncompleteMultipartUpload" in rule]
    assert len(abort) == 1
    assert abort[0]["Status"] == "Enabled"
    assert abort[0]["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"] == 1


def test_every_rule_is_enabled_and_named(lifecycle) -> None:
    """A rule with `Status: Disabled` is applied, stored, listed and inert —
    which is the shape a rule takes after somebody debugs an incident with it."""
    for rule in lifecycle.configuration()["Rules"]:
        assert rule["Status"] == "Enabled", rule.get("ID")
        assert rule.get("ID"), "an unnamed rule cannot be discussed in a runbook"


def test_no_rule_expires_anything_under_a_protected_prefix(lifecycle) -> None:
    """The guard rail. `Expiration` on a filter that could match a bundle is the
    change this test exists to refuse, whatever prefix it is spelled with."""
    for rule in lifecycle.configuration()["Rules"]:
        if "Expiration" not in rule and "NoncurrentVersionExpiration" not in rule:
            continue
        prefix = rule.get("Filter", {}).get("Prefix", "")
        assert prefix, f"{rule['ID']} expires objects bucket-wide, which includes bundles"
        for protected in lifecycle.PROTECTED:
            assert protected not in prefix, f"{rule['ID']} would expire {protected}"


def test_the_dry_run_changes_nothing_and_needs_no_bucket(lifecycle, capsys) -> None:
    """Run before the real thing by anyone sensible, so it must not need
    credentials that work — the operator checking the rules is often the one who
    has not yet been given them."""
    assert lifecycle.main(["--dry-run"]) == 0
    assert "abort-incomplete-uploads" in capsys.readouterr().out
