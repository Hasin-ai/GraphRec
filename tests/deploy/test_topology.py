"""The deployment topology, asserted against the files that implement it.

BACKEND_PLAN §9.1 makes a claim with a number in it: **two public ports on the
whole estate**, 443 on N1 and 443 on N3. A claim like that decays one
`ports:` entry at a time, and every one of those entries looks reasonable in
isolation — a database published so a colleague can connect, an exporter
published because the scrape was failing, a Grafana published because the VPN
was down that afternoon.

None of them is caught by a code review of the application. So they are caught
here.

The checks are structural rather than clever: parse the Compose files, look at
what each one binds, and compare against what §9.1 permits. `docker compose
config` is not used, because it requires the variables to be set and a test that
needs `WG_N1` in the environment is a test that gets skipped in CI.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"

#: The whole public surface, per §9.1. 80 accompanies each 443 because ACME's
#: HTTP-01 challenge and the redirect to HTTPS need it and it serves nothing
#: else — the Caddyfiles are what make that true, and they are checked below.
PUBLIC_PORTS = {"80", "443"}

#: Which node runs what. Written out rather than derived, so that moving a
#: service between nodes fails here and has to be justified, rather than
#: quietly changing the capacity model the sizing in §9.1 is based on.
EXPECTED_SERVICES = {
    "n1": {
        "postgres",
        "redis",
        "migrate",
        "control_api",
        "job_worker",
        "reconciler",
        "caddy",
        "prometheus",
        "alertmanager",
        "grafana",
        "node_exporter",
        "postgres_exporter",
        "redis_exporter",
    },
    "n2": {"training_worker", "node_exporter"},
    "n3": {"minio", "docker_proxy", "caddy", "node_exporter"},
}

NODES = ("n1", "n2", "n3")


def compose(node: str) -> dict:
    return yaml.safe_load((DEPLOY / node / "docker-compose.yml").read_text())


#: `${WG_N1}` and `${WG_N1:?message}` alike, reduced to the variable name. The
#: required-variable form carries a message containing colons, which is why the
#: mapping below is split from the right rather than from the left.
VARIABLE = re.compile(r"^\$\{(WG_N[123])(:[?-][^}]*)?\}$")


def bindings(service: dict) -> list[tuple[str, str]]:
    """(host address, host port) for every published port.

    Compose accepts `"443:443"` and `"10.0.0.1:5432:5432"`. Only the short form
    is used in this repository, and an unrecognised shape raises rather than
    being skipped — a mapping this parser cannot read is exactly the one
    somebody would use to slip a port past it.
    """
    published: list[tuple[str, str]] = []
    for entry in service.get("ports", []):
        assert isinstance(entry, str), f"long-form port mapping not parsed here: {entry}"
        parts = entry.rsplit(":", 2)
        if len(parts) == 3:
            published.append((parts[0], parts[1]))
        elif len(parts) == 2:
            published.append(("0.0.0.0", parts[0]))
        else:  # pragma: no cover - a shape this file does not use
            raise AssertionError(f"unparsed port mapping: {entry}")
    return published


def address_variable(address: str) -> str | None:
    """The WireGuard variable an address names, or `None` if it names none."""
    match = VARIABLE.match(address)
    return match.group(1) if match else None


@pytest.mark.parametrize("node", NODES)
def test_the_compose_file_parses(node: str) -> None:
    """The floor. Every test below iterates over services, and a file that
    failed to parse into an empty dict would pass all of them."""
    document = compose(node)
    assert document["name"] == f"graphrec-{node}"
    assert document["services"], node


@pytest.mark.parametrize("node", NODES)
def test_each_node_runs_what_section_9_1_says_it_runs(node: str) -> None:
    assert set(compose(node)["services"]) == EXPECTED_SERVICES[node]


@pytest.mark.parametrize("node", NODES)
def test_nothing_but_the_edge_binds_a_public_address(node: str) -> None:
    """The two-public-ports claim, enforced.

    A published port with no address binds `0.0.0.0`, which on these nodes is a
    public interface. Only Caddy may do it, and only on 80 and 443.
    """
    offenders: list[str] = []
    for name, service in compose(node)["services"].items():
        for address, port in bindings(service):
            if address in {"0.0.0.0", "::"}:
                if name == "caddy" and port in PUBLIC_PORTS:
                    continue
                offenders.append(f"{node}/{name} publishes {port} on {address}")
    assert not offenders, offenders


def test_n2_has_no_public_port_at_all() -> None:
    """§9.1: "No state, no public port". The node that may disappear.

    Stricter than the rule above rather than a special case of it: N2 has no
    Caddy and no reason ever to acquire one, so the assertion is that *nothing*
    on it publishes without an address.
    """
    for name, service in compose("n2")["services"].items():
        for address, port in bindings(service):
            assert address_variable(address), f"n2/{name} publishes {port} on {address}"


@pytest.mark.parametrize("node", NODES)
def test_every_private_binding_is_a_wireguard_address(node: str) -> None:
    """`${WG_N1}:5432:5432`, never `127.0.0.1:5432:5432`.

    Loopback would be safe and also useless: Prometheus scrapes from N1 and the
    workers connect from N2, so a service bound to loopback is one nothing can
    reach. The failure mode is that somebody "fixes" it by removing the address.
    """
    for name, service in compose(node)["services"].items():
        for address, _ in bindings(service):
            if name == "caddy":
                continue
            assert address_variable(address), f"{node}/{name}: {address}"


@pytest.mark.parametrize("node", NODES)
def test_no_image_is_floating(node: str) -> None:
    """§22.2: "Images tagged by commit SHA; rollback = pin previous tag".

    `latest` makes a rollback a rebuild from a tree that has since moved, and it
    makes two nodes deployed an hour apart run different code with no way to
    tell. The application image is pinned by variable; the third-party images
    are pinned by an explicit version tag.
    """
    for name, service in compose(node)["services"].items():
        image = service.get("image", "")
        if not image:
            continue
        assert not image.endswith(":latest"), f"{node}/{name}"
        assert ":" in image.rsplit("/", 1)[-1], f"{node}/{name} has no tag: {image}"


@pytest.mark.parametrize("node", NODES)
def test_secrets_are_mounted_not_passed_as_environment(node: str) -> None:
    """Every secret is a file. §22.2, and `Settings.model_config.secrets_dir`.

    The check is on the environment rather than on the mounts: a service may
    legitimately mount nothing, but no service may name a secret in its
    environment. `*_FILE` variables are the third-party images' own convention
    for reading a mount and are the point, not an exception.
    """
    forbidden = re.compile(r"(PASSWORD|SECRET|PEPPER|ACCESS_KEY|TOKEN)$")
    for name, service in compose(node)["services"].items():
        for key in service.get("environment", {}):
            assert not forbidden.search(key), f"{node}/{name} passes {key} in the environment"


@pytest.mark.parametrize("node", NODES)
def test_every_long_running_service_restarts_itself(node: str) -> None:
    """Except `migrate`, which must not.

    A one-shot that restarts is a migration that runs again on every failure,
    and `restart: unless-stopped` on it would turn a migration that fails
    halfway into a loop against a database it is already changing.
    """
    for name, service in compose(node)["services"].items():
        expected = "no" if name == "migrate" else "unless-stopped"
        assert service.get("restart") == expected, f"{node}/{name}"


def test_the_workers_outlast_their_leases() -> None:
    """A `stop_grace_period` shorter than a lease turns every deploy into
    retries: SIGKILL leaves a `running` row for the sweeper to requeue, and the
    job restarts work it had already done."""
    n1 = compose("n1")["services"]
    # job_lease_seconds is 120; the grace must be longer than a job mid-stage.
    assert n1["job_worker"]["stop_grace_period"] == "150s"
    # An epoch's worth, so a checkpoint is not wasted.
    assert compose("n2")["services"]["training_worker"]["stop_grace_period"] == "300s"


def test_migrations_run_before_anything_reads_the_schema() -> None:
    """§22.2: "One-shot `migrate` service runs `alembic upgrade head` **before**
    the API starts". Every service on N1 that touches the database waits on it
    completing, not merely on it starting."""
    n1 = compose("n1")["services"]
    for name in ("control_api", "job_worker", "reconciler"):
        depends = n1[name]["depends_on"]
        assert depends["migrate"]["condition"] == "service_completed_successfully", name


def test_the_serving_template_joins_the_network_n3_creates() -> None:
    """The reconciler starts each tenant's replicas as their own project, which
    joins N3's network by name. A mismatch here does not fail loudly: the
    replicas come up on an island, cannot reach the object store, never bind a
    bundle, and report as unready forever."""
    n3 = compose("n3")
    template = yaml.safe_load((DEPLOY / "single" / "docker-compose.serving.yml").read_text())
    assert n3["networks"]["graphrec"]["name"] == "graphrec"
    assert template["networks"]["graphrec"]["external"] is True
    # The template defaults to the local stack's name and is overridden on N3.
    assert "GRAPHREC_NETWORK" in template["networks"]["graphrec"]["name"]


@pytest.mark.parametrize("node", ["n1", "n3"])
def test_the_edge_sets_transport_security(node: str) -> None:
    caddyfile = (DEPLOY / node / "Caddyfile").read_text()
    assert "Strict-Transport-Security" in caddyfile
    assert "X-Content-Type-Options" in caddyfile
    assert "-Server" in caddyfile


@pytest.mark.parametrize("node", ["n1", "n3"])
def test_the_edge_pins_tls_1_3_on_both_public_surfaces(node: str) -> None:
    """§24, and the one item on that list a comment cannot satisfy.

    Caddy's default floor is TLS 1.2, which is a defensible default and is not
    what was asked for. Left implicit, the two files read exactly the same
    whether the floor is 1.2 or 1.3 — so this asserts the directive is present
    *and* that it names 1.3, because `protocols tls1.2` would also be a `tls`
    block and would also look deliberate.
    """
    caddyfile = (DEPLOY / node / "Caddyfile").read_text()
    protocols = re.search(r"tls\s*\{[^}]*?protocols\s+(\S+)", caddyfile, re.DOTALL)
    assert protocols is not None, f"{node}'s edge does not pin a TLS floor"
    assert protocols.group(1) == "tls1.3"


def test_only_the_console_edge_carries_browser_headers() -> None:
    """A CSP on the data plane would be a header nobody reads: those requests
    carry an HMAC credential, not a session, and there is no browser on the
    path. Stating it as a test rather than as a comment because the tempting
    change is to copy the header block from one file to the other."""
    assert "Content-Security-Policy" in (DEPLOY / "n1" / "Caddyfile").read_text()
    assert "Content-Security-Policy" not in (DEPLOY / "n3" / "Caddyfile").read_text()


@pytest.mark.parametrize("node", NODES)
def test_the_systemd_unit_waits_for_the_stack_to_be_healthy(node: str) -> None:
    """`--wait` is what makes the ordered deploy mean anything.

    Without it `systemctl start` returns as soon as the containers are created,
    the workflow's smoke test runs against an API that is still importing, and
    the deploy proceeds to the next node on the strength of a race.
    """
    unit = (DEPLOY / "systemd" / f"graphrec-{node}.service").read_text()
    assert "--wait" in unit
    assert "Restart=on-failure" in unit


def test_the_firewall_opens_the_public_ports_only_where_there_are_any() -> None:
    """N2's ruleset must not contain 443. It is the node with no public port,
    and a rule that opens one there is a rule copied from a sibling file."""
    n2 = (DEPLOY / "firewall" / "n2.nft").read_text()
    assert "443" not in n2
    for node in ("n1", "n3"):
        assert "tcp dport { 80, 443 } accept" in (DEPLOY / "firewall" / f"{node}.nft").read_text()


@pytest.mark.parametrize("node", NODES)
def test_the_firewall_default_denies_and_filters_forwarding(node: str) -> None:
    """The `forward` chain is the one that matters on a Docker host.

    Docker's rules sit below the input hook, so a published container port is
    reachable even when `input` would drop it. A ruleset with a default-deny
    `input` and no `forward` chain reads as hardened and is not.
    """
    ruleset = (DEPLOY / "firewall" / f"{node}.nft").read_text()
    hooks = re.findall(r"type filter hook (\w+) priority filter; policy (\w+);", ruleset)
    assert dict(hooks)["input"] == "drop"
    assert dict(hooks)["forward"] == "drop"


# --- what one node knows about another -------------------------------------
#
# The three checks below are the ones Phase 16 had to write after finding that
# `deploy/observability/prometheus.yml` named a service that does not exist
# (`api`), and two that exist on nodes Compose DNS cannot see. All three
# mistakes produce a valid configuration file and a Prometheus that scrapes
# nothing, which presents as `TargetDown` firing forever and then being muted.

#: The tunnel, per `deploy/README.md`. Prometheus cannot read `${WG_N2}` — it
#: does not interpolate the environment — so the addresses are literal in its
#: configuration and the convention has to hold.
TUNNEL = {"n1": "10.10.0.1", "n2": "10.10.0.2", "n3": "10.10.0.3"}


def prometheus_config() -> dict:
    return yaml.safe_load((DEPLOY / "observability" / "prometheus.yml").read_text())


def test_the_readme_and_prometheus_agree_on_the_tunnel_addresses() -> None:
    """One table, two files. The address table in `deploy/README.md` is the
    source; this asserts Prometheus was updated with it."""
    readme = (DEPLOY / "README.md").read_text()
    for node, address in TUNNEL.items():
        assert f"`{address}`" in readme, f"{address} is not in the README's address table"
        assert f"{node.upper()}" in readme
    config = (DEPLOY / "observability" / "prometheus.yml").read_text()
    for address in re.findall(r"\b10\.10\.0\.\d+\b", config):
        assert address in TUNNEL.values(), f"{address} is not a node on the tunnel"


def test_every_scrape_target_is_resolvable_from_n1() -> None:
    """Prometheus runs on N1, so a target is either an N1 Compose service or an
    address on the tunnel. A bare name belonging to another node resolves to
    nothing, forever, and looks exactly like a service that is down."""
    resolvable = EXPECTED_SERVICES["n1"] | {"localhost"}
    for job in prometheus_config()["scrape_configs"]:
        for static in job.get("static_configs", []):
            for target in static["targets"]:
                host = target.rsplit(":", 1)[0]
                assert (
                    host in resolvable or host in TUNNEL.values()
                ), f"job {job['job_name']} scrapes {host}, which N1 cannot resolve"
        for discovery in job.get("docker_sd_configs", []):
            # The replicas run on N3, so discovery has to ask N3's daemon. A
            # local socket here discovers N1's containers, of which none is an
            # inference replica, and the job silently finds nothing.
            assert (
                TUNNEL["n3"] in discovery["host"]
            ), f"job {job['job_name']} discovers from {discovery['host']}, not N3"


def test_the_serving_template_publishes_its_metrics_port_and_nothing_else() -> None:
    """Scaled replicas cannot have a fixed host port, and a container address on
    N3's bridge network is not routable from N1. The empty middle field is what
    reconciles those two: Docker assigns an ephemeral host port per replica."""
    template = yaml.safe_load((DEPLOY / "single" / "docker-compose.serving.yml").read_text())
    published = template["services"]["inference"]["ports"]
    assert published == ["${GRAPHREC_METRICS_BIND_ADDR:-127.0.0.1}::9464"], published
    # 8020 travels over the shared network by service name. Publishing it would
    # put the recommendation API on a host port with no edge in front of it.
    assert not any("8020" in entry for entry in published)


def test_the_reconciler_tells_the_replicas_where_the_other_nodes_are() -> None:
    """The serving template's backing services default to Compose service
    names, which are correct on one host and wrong on three. `_environment`
    merges the reconciler's environment into every compose invocation, so this
    is where a replica on N3 learns that its database is on N1."""
    environment = compose("n1")["services"]["reconciler"]["environment"]
    assert environment["POSTGRES_HOST"] == "${WG_N1}"
    assert environment["REDIS_URL"] == "redis://${WG_N1}:6379/0"
    assert environment["S3_ENDPOINT"] == "http://${WG_N3}:9000"
    assert environment["GRAPHREC_METRICS_BIND_ADDR"] == "${WG_N3}"


@pytest.mark.parametrize("node", NODES)
def test_every_mounted_file_exists(node: str) -> None:
    """A bind mount whose source does not exist is not an error on a Docker
    host: the daemon creates a directory there, and the container starts and
    fails on a config file that is a directory.

    `deploy/observability/alertmanager.yml` was mounted by N1 and had never been
    written. Nothing said so, because nothing here had run.
    """
    for name, service in compose(node)["services"].items():
        for entry in service.get("volumes", []):
            source = entry.split(":", 1)[0]
            if not source.startswith("."):
                # A named volume, or a host path that belongs to the host
                # (`/var/run/docker.sock`, `/proc`, `/sys`) and exists there
                # rather than in this repository.
                continue
            resolved = (DEPLOY / node / source).resolve()
            assert resolved.exists(), f"{node}/{name} mounts {source}, which does not exist"
