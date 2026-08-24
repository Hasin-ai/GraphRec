"""The Grafana dashboards, checked against the metrics that exist.

Same failure as an alert rule referencing a metric nobody publishes, one step
further from anyone noticing: a panel querying `graphrec_job_failures_total`
does not error, it draws an empty graph, and an empty graph on a jobs dashboard
reads as "no jobs are failing".

So: every `graphrec_*` name a panel queries must be published, every panel must
name the provisioned datasource by its fixed UID, and every panel must say what
it is for. The last one is a real check rather than a style rule — a panel
titled "p95" with no description is one an operator has to reverse-engineer at
03:00 to find out which p95 it is.

PromQL syntax is not checked here; `promtool check rules` covers the alert
expressions and there is no equivalent for dashboard panels. What is checked is
the part that is silently wrong rather than loudly broken.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
GRAFANA = ROOT / "deploy" / "observability" / "grafana"
DASHBOARDS = sorted((GRAFANA / "dashboards").glob("*.json"))
DATASOURCES = GRAFANA / "provisioning" / "datasources" / "prometheus.yml"
PROVIDERS = GRAFANA / "provisioning" / "dashboards" / "graphrec.yml"


def _published() -> set[str]:
    from graphrec.observability.metrics import REGISTRY

    names: set[str] = set()
    for metric in REGISTRY.collect():
        names.add(metric.name)
        for suffix in ("_total", "_bucket", "_sum", "_count", "_created"):
            names.add(f"{metric.name}{suffix}")
    return names


def _panels(path: pathlib.Path) -> list[dict]:
    return json.loads(path.read_text())["panels"]


def test_there_are_dashboards_at_all() -> None:
    """The floor: every test below iterates, and an empty glob passes them all."""
    assert DASHBOARDS, "no dashboards found"
    assert {path.name for path in DASHBOARDS} == {"serving.json", "platform.json"}


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_every_metric_a_panel_queries_is_published(path) -> None:
    published = _published()
    referenced: set[str] = set()
    for panel in _panels(path):
        for target in panel.get("targets", []):
            referenced.update(re.findall(r"graphrec_[a-z0-9_]+", target["expr"]))

    assert referenced, f"{path.name} queries no graphrec metric at all"
    missing = sorted(referenced - published)
    assert not missing, f"{path.name} draws panels for metrics nobody publishes: {missing}"


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_every_panel_uses_the_provisioned_datasource(path) -> None:
    """A panel with no datasource inherits Grafana's default, which on a fresh
    install is whatever was created first. The UID is fixed in the provisioning
    file precisely so this can be asserted."""
    uid = yaml.safe_load(DATASOURCES.read_text())["datasources"][0]["uid"]
    for panel in _panels(path):
        assert panel["datasource"]["uid"] == uid, panel["title"]
        for target in panel.get("targets", []):
            assert target["datasource"]["uid"] == uid, panel["title"]


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_every_panel_says_what_it_is_for(path) -> None:
    for panel in _panels(path):
        assert panel.get("title"), panel
        assert len(panel.get("description", "")) > 40, panel["title"]


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_no_panel_labels_a_series_by_something_unbounded(path) -> None:
    """`by (route)` is a template; `by (path)` would be a series per product.

    Grouping by a label the platform does not publish is also caught here,
    because it produces one flat line rather than an error.
    """
    allowed = {
        "le",
        "route",
        "job_type",
        "outcome",
        "strategy",
        "status",
        "state",
        "tenant_id",
        "app",
        "version",
        "instance",
        "method",
        "degraded",
    }
    for panel in _panels(path):
        for target in panel.get("targets", []):
            for group in re.findall(r"\bby\s*\(([^)]*)\)", target["expr"]):
                labels = {label.strip() for label in group.split(",") if label.strip()}
                assert labels <= allowed, f"{panel['title']}: {labels - allowed}"


def test_dashboards_are_not_editable_in_the_ui() -> None:
    """An edit made live is a change nobody reviewed which vanishes on the next
    container recreate — and the person who made it finds out during the next
    incident."""
    provider = yaml.safe_load(PROVIDERS.read_text())["providers"][0]
    assert provider["allowUiUpdates"] is False
    for path in DASHBOARDS:
        assert json.loads(path.read_text())["editable"] is False, path.name


def test_the_alert_thresholds_and_the_panel_thresholds_agree() -> None:
    """A graph whose red line is at 500 ms next to an alert that fires at 300 ms
    teaches an operator the wrong number, and they will remember the graph."""
    rules = yaml.safe_load((ROOT / "deploy" / "observability" / "alerts.yml").read_text())
    by_name = {rule["alert"]: rule for group in rules["groups"] for rule in group["rules"]}
    panels = {panel["title"]: panel for path in DASHBOARDS for panel in _panels(path)}

    def red(title: str) -> float:
        steps = panels[title]["fieldConfig"]["defaults"]["thresholds"]["steps"]
        return next(step["value"] for step in steps if step["value"] is not None)

    assert "> 0.3" in by_name["InferenceLatencyHigh"]["expr"]
    assert red("Inference latency") == 0.3
    assert "> 0.05" in by_name["FallbackRateHigh"]["expr"]
    assert red("Fallback share") == 0.05
    assert "> 1800" in by_name["JobQueueStalled"]["expr"]
    assert red("Oldest queued job") == 1800
    assert "> 50" in by_name["JobQueueDeep"]["expr"]
    assert red("Queue depth") == 50
