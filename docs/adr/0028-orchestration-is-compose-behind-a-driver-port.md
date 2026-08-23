# ADR 0028 — Serving capacity is Docker Compose behind a `ServingDriver` port

**Status:** Accepted — confirmed by instruction to proceed
**Phase:** 11
**Date:** 2026-08-23

## Context

D3 asks what runs the per-tenant inference processes. Two documents disagree,
and unlike D4 this one is not a disagreement about a product name — it is a
disagreement about what the console is allowed to show.

**`SYSTEM_DESIGN.md` D-9 rejects Kubernetes** on arithmetic: a control plane
costs 1–2 GB and roughly a core on each of three nodes, which on this
installation is a third of the hardware spent on scheduling four processes.

**`GraphRec_Ultimate_Architecture.md` §4 and §30 require k3s**, one Deployment
and one HorizontalPodAutoscaler per tenant, because XR-F-08 demands
demand-driven capacity adjustment and the console renders it: `/service-status`
draws *"Desired capacity"* and *"Ready capacity"* as separate stats and colours
the second amber when it is below the first (dc.html L1834-1835), and
`/admin/status` renders *"Serving replicas 7 / 7"*.

The console is the thing that cannot be compromised. It does not ask *how*
capacity is produced; it asks for two numbers and the per-replica rows behind
them. That is the shape of a port.

## Decision

**A `ServingDriver` port, with the Compose adapter shipped and a k3s adapter
deferred.** The port is four operations: `apply` a desired state for a tenant,
`observe` what is actually running, `stop` a tenant's serving, and `describe`
the driver for the console's autoscaling panel.

**Compose is the shipped adapter**, driven from the reconciler over the Docker
socket on N3, with systemd owning the reconciler itself. `desired_replicas` for
a tenant becomes a scaled Compose service; each container reports itself into
`serving_replicas` with a `replica_ref`, a `version_id`, a status and a `ready`
flag.

**Both adapters report the same three things** — desired, ready, and one row per
replica — so the console is identical either way and XR-F-08 is demonstrable
without making Kubernetes a prerequisite for `docker compose up`. This is the
reconciliation BACKEND_PLAN Q3 proposes and neither source document offered.

**Autoscaling is bounded and recorded, not continuous.** The Compose adapter
adjusts `desired_replicas` within a tenant's plan-derived minimum and maximum
against a measured demand signal, and every adjustment is a row. An HPA's
control loop is not reproduced; what is reproduced is the *contract* the console
draws — min, max, target, and recent actions (`GET /v1/deployment/autoscaling`).

## Consequences

The reconciler is a singleton holding a leader lock, because two reconcilers
racing to converge the same tenant would fight over the replica count and each
would read the other's half-applied state as drift. The lock is a PostgreSQL
advisory lock, for the same reason the job queue is a table: there is already a
database, and adding a second consensus system to coordinate one process is not
a trade this installation can justify.

Compose gives no scheduling across nodes. Every replica of every tenant runs on
N3, and a tenant that needed more capacity than N3 has is a tenant that needs
the k3s adapter. ASM-02 bounds the platform at four tenants, so this is a
documented ceiling rather than a surprise.

`ready ≥ 1` for every active tenant (NR-NF-08) is therefore a property of the
reconciler's convergence loop rather than of a scheduler. It is enforced as a
floor on `desired_replicas` — the reconciler will not converge a tenant to zero
while the tenant is active — and observed by the replica reporting that the
console reads.

**A failed activation must not cost capacity.** The load-before-swap rule (ER-
F-06) belongs to activation rather than to the driver: a new version is loaded
and verified in a replica *before* `active_version_id` moves, so a driver that
cannot start the new version leaves the old one serving and the deployment in
`degraded` rather than in `stopped`.

## Related

- ADR 0026 — the same shape for D4: a port, the simple adapter shipped, the
  heavyweight one deferred with its contract honoured rather than waived.
- `SYSTEM_DESIGN.md` D-9; `GraphRec_Ultimate_Architecture.md` §4, §30;
  BACKEND_PLAN Q3; XR-F-08; NR-NF-08.
