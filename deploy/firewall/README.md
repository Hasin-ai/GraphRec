# Firewall

nftables, default-deny inbound, one ruleset per node. BACKEND_PLAN §22.1:
"inter-node WireGuard, storage bound to private addresses only; default-deny
firewall; SSH key-only."

```sh
sudo cp deploy/firewall/n1.nft /etc/nftables.conf
sudo nft -c -f /etc/nftables.conf     # check before applying
sudo systemctl enable --now nftables
```

**`nft -c` first, every time.** A ruleset that drops SSH is applied
successfully and locks you out of the machine that would fix it. On a remote
node, apply behind `systemd-run --on-active=5m nft flush ruleset` so a mistake
undoes itself.

## The rule this is really enforcing

Two public ports on the estate: 443 on N1 and 443 on N3. Everything else —
Postgres, Redis, the object store, every metrics listener, Grafana, Prometheus,
the Docker API proxy — is reachable over `wg0` and from nowhere else.

That is stated in three places, and the redundancy is deliberate because each
one fails differently:

1. **The Compose files** bind private addresses, so there is no listener on the
   public interface. This is the strongest of the three and the one a firewall
   mistake cannot undo.
2. **These rulesets** drop what does arrive, which covers a service added later
   by someone who did not read (1).
3. **`tests/deploy/test_topology.py`** fails the build if a Compose
   file publishes to `0.0.0.0` outside the two allowed ports, which covers the
   change that is made and then deployed before anyone reads (2).

## Docker and nftables

Docker inserts its own rules and it does so *below* the `filter` hook these
files use, in `nat` and in `DOCKER-USER`. A published port therefore reaches a
container even when `input` would drop it, which is the single most common way
a "hardened" Docker host turns out to be open.

The `forward` chain here is what closes that. It is not decoration.
