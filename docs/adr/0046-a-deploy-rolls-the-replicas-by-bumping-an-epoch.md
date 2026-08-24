# ADR 0046 — A deploy rolls the replicas by bumping an epoch, not by restarting them

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

A deploy changes `GRAPHREC_IMAGE_TAG` and restarts three Compose stacks. The
inference containers are in none of them: there is one Compose project per
tenant, `graphrec-serve-<tenant hex>`, and the reconciler owns them all.

So the estate ends a deploy with a new control plane, a new training worker, and
a serving fleet still running the previous week's image — and nothing reports
it. Every health check passes. Every replica is ready. `graphrec_serving_replicas`
shows desired equal to ready. The fleet is simply old.

The direct fix is for the deploy to restart the inference containers: enumerate
the projects, `docker compose up -d` each. That works and puts a second
authority over the serving fleet next to the reconciler, which is the thing ADR
0028's driver port exists to avoid. It also skips the load-before-swap that
ER-F-06 requires — a `restart` stops working replicas before their replacements
have loaded a bundle.

## Decision

**`apps/reconciler/roll.py`, run as a deploy step, changes desired state and
nothing else.** For each active tenant with a running deployment it calls
`DeploymentService.set_desired` with **the version already desired** — the same
`desired_version_id`, a new epoch.

That distinction is the whole design: bumping the epoch says *this tenant should
serve the same model out of a different container*, where changing the version
would say *this tenant should serve a different model*. The reconciler then sees
replicas whose `com.graphrec.epoch` label is behind and rolls them the way it
rolls anything else — load before swap, previous version retired only once the
new replicas report ready.

`set_desired` is used rather than an `UPDATE` here, because it is the audited
path that bumps the epoch and leaves `active_version_id` alone, and a second
implementation would be a second place for ER-F-06's invariant to be got wrong.

**One tenant at a time, with `--pause`.** Bumping every epoch in one transaction
is shorter and asks N3 to start a second full set of replicas for every tenant
simultaneously. The risk being managed is memory on N3, not correctness — the
reconciler already refuses to retire a working version.

**It does not wait.** No container is started here, no Docker daemon is
contacted, and the process exits immediately. A deploy step that blocked until
every tenant converged would hold a CI job open for as long as the slowest
bundle takes to download.

## Consequences

**The deploy reports success before the roll has happened.** The workflow's
green tick means "every tenant has been asked to roll", not "every tenant is on
the new image". Watching it is Grafana's job and
`docs/RUNBOOKS.md#force-a-rollback`'s. This is stated in the script's docstring
because it is the thing most likely to be misread.

A tenant whose deployment is `STOPPED` is skipped rather than rolled. A halted
deployment remembers its version so a resumed tenant comes back on it, and
bumping its epoch would leave every replica permanently drifted from a
deployment that is not changing.

`--image` is recorded in the log and not read: the image the replicas start with
comes from the reconciler's own environment. If the reconciler's environment
were not updated, the roll would restart every replica onto the same image and
report success. The N1 step runs before this one, which is what makes that not
happen, and it is an ordering dependency rather than a check.
