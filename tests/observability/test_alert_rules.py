"""The alert rules, checked against the metrics that exist.

An alert rule is the only code in this repository that runs in another process,
against a query language nothing here compiles, and produces no output when it
is wrong. `JobFailureRateHigh` referring to `graphrec_job_failures_total` — a
name that was never published — is a rule that evaluates to nothing forever and
looks, on every dashboard, exactly like a platform with no failing jobs.

So the checks here are:

* every `graphrec_*` metric a rule mentions is one this platform publishes;
* every alert §24 requires is present;
* every rule has a `for`, a severity and a runbook link.

What this cannot check is PromQL syntax. `promtool check rules` does, and it
runs in CI (`.github/workflows/ci.yml`, job `observability`) where the
Prometheus image is available.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from graphrec.observability.metrics import REGISTRY

RULES = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "observability" / "alerts.yml"
SCRAPE = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "observability" / "prometheus.yml"

#: The six §24 names, mapped onto the rule that implements each. The mapping is
#: written out rather than inferred so that deleting a rule fails here with the
#: checklist line it belonged to, not with a count that is one lower.
REQUIRED_BY_SECTION_24 = {
    "inference P95 > 300 ms": "InferenceLatencyHigh",
    "fallback > 5%": "FallbackRateHigh",
    "queue depth": "JobQueueDeep",
    "job failure rate": "JobFailureRateHigh",
    "disk > 80%": "DiskFillingUp",
    "ready < 1 for an active tenant": "TenantHasNoReadyReplica",
}

#: Metric families that come from exporters this platform does not write.
FOREIGN_PREFIXES = ("node_", "pg_", "redis_", "up")


@pytest.fixture(scope="module")
def rules() -> list[dict]:
    document = yaml.safe_load(RULES.read_text())
    return [rule for group in document["groups"] for rule in group["rules"]]


def _published() -> set[str]:
    """Every series name the registry can emit, suffixes included.

    A counter named `graphrec_jobs_finished_total` collects as
    `graphrec_jobs_finished` and emits `_total`; a histogram emits `_bucket`,
    `_sum` and `_count`. A rule references the emitted name, so that is what
    this compares against.
    """
    names: set[str] = set()
    for metric in REGISTRY.collect():
        names.add(metric.name)
        for suffix in ("_total", "_bucket", "_sum", "_count", "_created"):
            names.add(f"{metric.name}{suffix}")
    return names


def test_every_graphrec_metric_a_rule_mentions_is_published(rules) -> None:
    """The failure this exists for: a rule that queries a name nobody emits.

    It does not error. It evaluates to an empty vector, forever, and reads as
    good news.
    """
    published = _published()
    referenced: set[str] = set()
    for rule in rules:
        referenced.update(re.findall(r"graphrec_[a-z0-9_]+", rule["expr"]))

    assert referenced, "the rules mention no graphrec metric at all"
    missing = sorted(referenced - published)
    assert not missing, f"alert rules reference metrics that are never published: {missing}"


def test_every_alert_section_24_requires_exists(rules) -> None:
    defined = {rule["alert"] for rule in rules}
    missing = {
        requirement: name
        for requirement, name in REQUIRED_BY_SECTION_24.items()
        if name not in defined
    }
    assert not missing, f"BACKEND_PLAN §24 requires alerts that are not defined: {missing}"


def test_the_labels_a_rule_joins_on_are_labels_we_publish(rules) -> None:
    """`TenantHasNoReadyReplica` joins two series on `tenant_id`.

    A join on a label only one side carries matches nothing and the alert never
    fires — the same silent failure as a misspelt metric, one level down.
    """
    tenant_labels = {
        label
        for metric in REGISTRY.collect()
        if metric.name == "graphrec_serving_replicas"
        for sample in metric.samples
        for label in sample.labels
    }
    rule = next(r for r in rules if r["alert"] == "TenantHasNoReadyReplica")
    assert "on (tenant_id)" in rule["expr"]
    # The gauge has no samples until something sets one, so the label set is
    # asserted from the declaration rather than from a collected sample.
    from graphrec.observability.metrics import SERVING_REPLICAS

    assert set(SERVING_REPLICAS._labelnames) == {"tenant_id", "state"}
    assert tenant_labels <= {"tenant_id", "state"}


def test_no_rule_fires_on_a_single_scrape(rules) -> None:
    """Every rule has a `for`.

    A P95 alert with no `for` fires on one slow request during a deploy. An
    alert that has cried wolf once is an alert with a silence on it, and a
    silenced alert is worse than none because it looks configured.
    """
    instant = [rule["alert"] for rule in rules if not rule.get("for")]
    assert not instant, f"these alerts fire on a single evaluation: {instant}"


def test_every_alert_says_what_to_do_about_it(rules) -> None:
    """A notification without a next action is a notification that gets read
    twice and then filtered."""
    for rule in rules:
        annotations = rule.get("annotations", {})
        assert annotations.get("summary"), rule["alert"]
        assert annotations.get("runbook", "").startswith("docs/RUNBOOKS.md#"), rule["alert"]
        assert rule.get("labels", {}).get("severity") in {"warning", "critical"}, rule["alert"]


def test_every_runbook_anchor_a_rule_points_at_exists(rules) -> None:
    """A runbook link into a heading nobody wrote is a dead end at 03:00."""
    runbooks = pathlib.Path(__file__).resolve().parents[2] / "docs" / "RUNBOOKS.md"
    headings = {
        re.sub(r"[^a-z0-9]+", "-", line.lstrip("#").strip().lower()).strip("-")
        for line in runbooks.read_text().splitlines()
        if line.startswith("#")
    }
    missing = sorted(
        {
            rule["annotations"]["runbook"].split("#", 1)[1]
            for rule in rules
            if rule["annotations"]["runbook"].split("#", 1)[1] not in headings
        }
    )
    assert not missing, f"alerts link to runbook sections that do not exist: {missing}"


def test_the_scrape_config_covers_every_process_that_publishes() -> None:
    """A process instrumented but never scraped publishes to nobody."""
    document = yaml.safe_load(SCRAPE.read_text())
    jobs = {entry["job_name"] for entry in document["scrape_configs"]}
    assert {
        "control_api",
        "job_worker",
        "training_worker",
        "reconciler",
        "inference",
    } <= jobs


def test_the_rules_file_is_the_one_prometheus_loads() -> None:
    """A rules file in the repository that the scrape config does not reference
    is a file that is tested here and loaded nowhere."""
    document = yaml.safe_load(SCRAPE.read_text())
    assert any(path.endswith("alerts.yml") for path in document["rule_files"])


def test_foreign_metrics_are_only_the_exporters_we_deploy(rules) -> None:
    """A rule may read node_exporter, but not invent an exporter nobody runs."""
    document = yaml.safe_load(SCRAPE.read_text())
    jobs = {entry["job_name"] for entry in document["scrape_configs"]}
    for rule in rules:
        for name in re.findall(r"\b(node|pg|redis)_[a-z0-9_]+", rule["expr"]):
            assert name in jobs, f"{rule['alert']} reads {name}_* but nothing scrapes it"
    assert FOREIGN_PREFIXES  # documented above; the loop uses the three concrete ones
