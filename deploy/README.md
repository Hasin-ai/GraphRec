# Deployment

Three nodes, two public ports, one Compose project per node wrapped in a systemd
unit. The topology is BACKEND_PLAN §9.1 and the runtime is §22.2; this directory
is those two sections made executable.

```
                    :443                                  :443
                      │                                     │
              ┌───────┴────────┐                    ┌───────┴────────┐
              │   N1 Control   │                    │  N3 Serving    │
              │                │                    │  + storage     │
              │ caddy          │                    │ caddy          │
              │ control-api    │                    │ inference ×N   │
              │ job-worker ×2  │◄──── wg0 ─────────►│ minio          │
              │ reconciler     │   10.10.0.0/24     │ node_exporter  │
              │ postgres       │                    └────────────────┘
              │ redis          │                             ▲
              │ prometheus     │                             │
              │ grafana        │                    ┌────────┴───────┐
              │ alertmanager   │◄──── wg0 ─────────►│  N2 Training   │
              └────────────────┘                    │ training-worker│
                                                    │ node_exporter  │
                                                    │ (GPU, no state,│
                                                    │  no public port)│
                                                    └────────────────┘
```

## Addresses on the tunnel

Fixed by convention, not by discovery:

| Node | Role              | wg0 address | `WG_N*` variable |
|------|-------------------|-------------|------------------|
| N1   | control           | `10.10.0.1` | `WG_N1`          |
| N2   | training          | `10.10.0.2` | `WG_N2`          |
| N3   | serving + storage | `10.10.0.3` | `WG_N3`          |

Each node's `/opt/graphrec/.env` sets its own `WG_N1`/`WG_N2`/`WG_N3` — all
three on every node, because the Compose files refer to each other's addresses.

The convention exists because one file cannot use the variables:
`deploy/observability/prometheus.yml` names N2's exporter and N3's Docker socket
proxy as targets, and Prometheus does not interpolate the environment into its
configuration. Those addresses are therefore literal there, and
`tests/deploy/test_topology.py` asserts they match this table — the failure that
guards against is a scrape target that never resolves, which presents as
`TargetDown` firing forever and then being ignored.

## The two public ports

`443` on N1 carries the console, the control API and ingestion. `443` on N3
carries recommendations and feedback. **Nothing else binds a public interface.**

That is a structural claim, not a convention, and it is enforced in three
places rather than one: every other service binds `127.0.0.1` or the WireGuard
address in its Compose file, the firewall default-denies inbound on the public
interface (`firewall/`), and `tests/deploy/test_topology.py` asserts
that no Compose file in this directory publishes a port to `0.0.0.0` except
those two.

The metrics listeners are the case worth being explicit about. Every process
exposes Prometheus metrics on its own port (9464 by default), *never* as a
`/metrics` route on the application port. A route would have to be excluded by a
Caddy rule, and a rule that is one edit from being wrong is not a boundary.
Prometheus reaches these over WireGuard.

## Deploy order

**N1 (migrations) → N3 (inference) → N2 (trainer)**, with a smoke test between
each. `.github/workflows/deploy.yml` does exactly this and will not proceed past
a failed smoke test.

The order is forced by what depends on what:

* **N1 first** because it runs the migrations, and every other node's code
  expects the schema they produce. Migrations must be safe for one release back
  (§22.2), so N1 briefly runs new schema against old workers — which is the
  situation that constraint exists for.
* **N3 second** because serving is the user-visible half. If it fails, N2 has
  not been touched, and the rollback surface is one node.
* **N2 last** because it is the only node that can disappear without
  user-visible breakage beyond "training unavailable" (§9.4, C-5). It is the
  cheapest thing to have broken while you find out.

## Secrets

Root-owned `0400` files, mounted as Docker secrets, read by
`Settings.model_config.secrets_dir` — one file per setting, named for the
setting. Not environment variables: an environment variable shows up in
`docker inspect`, in `/proc/<pid>/environ`, and in any traceback from a library
that prints the environment.

`settings_customise_sources` puts secret files *above* `.env`, which is not
pydantic-settings' default order. A `.env` left on a node after a manual test
would otherwise override every mounted secret silently.

Rotation is file replace plus restart. `docs/RUNBOOKS.md#rotate-a-secret` covers
which secrets can be rotated in place, which need a two-key overlap, and which
(the pepper) have no rotation procedure at all by design.

## Images

Tagged by commit SHA, never `latest`. Rollback is pinning the previous tag,
which means the image that was running yesterday still exists and does not have
to be rebuilt from a tree that has moved.

`GRAPHREC_IMAGE_TAG` is the single variable that selects one, and every node's
Compose file reads it.

## Per-node files

| | |
|---|---|
| `n1/docker-compose.yml` | control plane, database, cache, observability |
| `n1/Caddyfile` | the public edge for console, control API and ingestion |
| `n2/docker-compose.yml` | the training worker and its exporter |
| `n3/docker-compose.yml` | object store, the serving edge, the exporter |
| `n3/Caddyfile` | the public edge for recommendations and feedback |
| `single/docker-compose.serving.yml` | the per-tenant serving template the reconciler applies on N3 |
| `systemd/` | one unit per node, plus the backup and drill timers |
| `firewall/` | nftables rulesets, default-deny inbound |
| `observability/` | Prometheus config, alert rules, Grafana provisioning and dashboards |

## Bringing a node up by hand

```sh
sudo systemctl start graphrec-n1        # or -n2, -n3
sudo systemctl status graphrec-n1
docker compose -f /opt/graphrec/deploy/n1/docker-compose.yml ps
```

The systemd unit is what runs at boot and what an operator uses. Running
`docker compose up` directly works and is how you debug, but it leaves systemd's
view of the world wrong until the next `systemctl restart`.
