"""Design test 2: the host derivation matches the deploy.

The data-plane hostname is not a convention this SDK invented — it is what
`deploy/n3/Caddyfile` parses to find a tenant's replicas, and what
`graphrec/serving_driver/compose.py` names those replicas. This file reads both
and asserts the SDK agrees, so a change to the label index or the project prefix
fails here rather than as a 404 nobody can explain.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from graphrec_sdk import ConfigurationError, GraphRec, normalise_tenant_id
from tests.sdk.conftest import DOMAIN, KEY, TENANT, TENANT_HEX

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = (ROOT / "deploy" / "n3" / "Caddyfile").read_text()
COMPOSE = (ROOT / "graphrec" / "serving_driver" / "compose.py").read_text()


def _client(**options: str) -> GraphRec:
    return GraphRec(api_key=KEY, tenant_id=TENANT, **options)  # type: ignore[arg-type]


def test_label_index_in_the_caddyfile_is_where_the_sdk_puts_the_tenant() -> None:
    match = re.search(r"\{http\.request\.host\.labels\.(\d+)\}", CADDYFILE)
    assert match, "the N3 Caddyfile no longer routes on a host label"
    index = int(match.group(1))

    host = _client(domain=DOMAIN).hosts["data"].removeprefix("https://")
    labels = host.split(".")
    # Caddy counts labels from the right: for `abc.api.example.com`, label 3 is
    # `abc`.
    assert labels[len(labels) - 1 - index] == TENANT_HEX


def test_the_base_domain_has_as_many_labels_as_the_index_assumes() -> None:
    match = re.search(r"\{http\.request\.host\.labels\.(\d+)\}", CADDYFILE)
    assert match
    # `serve.graphrec.example` is three labels, and the tenant sits at index 3.
    assert len(f"serve.{DOMAIN}".split(".")) == int(match.group(1))


def test_the_upstream_the_edge_resolves_is_the_project_the_driver_creates() -> None:
    prefix = re.search(r'PROJECT_PREFIX\s*=\s*"([^"]+)"', COMPOSE)
    assert prefix
    service = re.search(r'SERVICE_NAME\s*=\s*"([^"]+)"', COMPOSE)
    assert service
    upstream = re.search(r'name "graphrec-serve-\{[^}]+\}-(\w+)"', CADDYFILE)
    assert upstream
    assert f"{prefix.group(1)}{TENANT_HEX}-{service.group(1)}" == (
        f"graphrec-serve-{TENANT_HEX}-{upstream.group(1)}"
    )


def test_domain_shorthand_derives_both_hosts() -> None:
    hosts = _client(domain=DOMAIN).hosts
    assert hosts["control"] == f"https://api.{DOMAIN}"
    assert hosts["data"] == f"https://{TENANT_HEX}.serve.{DOMAIN}"


def test_the_two_domains_are_independent_because_the_deploy_makes_them_so() -> None:
    # `GRAPHREC_CONSOLE_DOMAIN` and `GRAPHREC_API_DOMAIN` are separate variables
    # in the deploy, not one root plus a convention.
    hosts = _client(console_domain="control.internal", api_domain="edge.internal").hosts
    assert hosts["control"] == "https://control.internal"
    assert hosts["data"] == f"https://{TENANT_HEX}.edge.internal"


def test_explicit_urls_win_over_domains() -> None:
    hosts = _client(
        domain=DOMAIN, control_url="http://localhost:8010", data_url="http://localhost:8020"
    ).hosts
    assert hosts == {"control": "http://localhost:8010", "data": "http://localhost:8020"}


def test_plaintext_is_refused_except_on_the_loopback() -> None:
    with pytest.raises(ConfigurationError, match="bearer token"):
        _client(control_url="http://api.example.com", data_url="https://x.example.com")


def test_a_dashed_and_a_bare_tenant_id_are_the_same_host() -> None:
    assert normalise_tenant_id(TENANT) == TENANT_HEX
    assert normalise_tenant_id(TENANT_HEX) == TENANT_HEX
    assert normalise_tenant_id(TENANT.upper()) == TENANT_HEX


def test_a_tenant_id_that_is_not_a_uuid_is_refused_before_dns_sees_it() -> None:
    with pytest.raises(ConfigurationError, match="Tenant page"):
        GraphRec(api_key=KEY, tenant_id="acme-corp", domain=DOMAIN)


def test_one_host_alone_is_not_enough() -> None:
    with pytest.raises(ConfigurationError, match="two public hosts"):
        GraphRec(api_key=KEY, tenant_id=TENANT, control_url="https://api.example.com")
