# ADR 0044 — The tunnel addresses are literals, in one convention, written down

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

The three nodes talk over WireGuard. Six files need to name those addresses: the
three Compose files (which bind private services to them), the three nftables
rulesets (which allow the tunnel and deny the rest), and `prometheus.yml` (which
scrapes N2 and N3 across it).

Everything else in the deployment is parameterised — image tags, domains,
secrets. The obvious move is to parameterise these too, as `${WG_N1}` and so on.

**Prometheus does not interpolate environment variables.** `prometheus.yml` is
read as literal YAML; `${WG_N2}` in a `targets` list is a hostname containing a
dollar sign, and the failure is a target that never resolves — which shows up as
`TargetDown` for a node that is perfectly healthy, several days later, once
somebody wonders why a panel is empty.

Partial parameterisation is worse than either extreme: the addresses would be
variables in five files and literals in the sixth, and the sixth is the one
nobody edits.

## Decision

**Fixed literals, one convention, stated once.** `10.10.0.0/24`, node *n* at
`10.10.0.n`: N1 `10.10.0.1`, N2 `10.10.0.2`, N3 `10.10.0.3`. Written into
`deploy/README.md` as the convention, and used verbatim in all six files.

Held by `tests/deploy/test_topology.py`:
`test_the_readme_and_prometheus_agree_on_the_tunnel_addresses` compares the
documented convention against what Prometheus actually scrapes, and
`test_every_scrape_target_is_resolvable_from_n1` checks each target is either a
Compose service name on N1 or one of the three tunnel addresses. The second test
was written after finding four scrape targets that resolved to nothing.

## Consequences

An operator on a network that already uses `10.10.0.0/24` has to change the
addresses in six files. That is a real cost, paid once at setup, and it is
visible — a `grep` finds every occurrence, which is not true of a variable whose
value is set somewhere else.

The tests are what make the literals safe. Without them, a fourth node or a
renumbering would leave `prometheus.yml` behind exactly the way it would have
been left behind by parameterisation, and the symptom would be identical.

This decision does not extend to anything else. Domains, tags and secrets remain
parameterised; the argument here is specific to a file format that cannot
interpolate, and to a set of addresses small enough to enumerate.
