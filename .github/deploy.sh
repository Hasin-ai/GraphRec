#!/usr/bin/env bash
#
# The one place that knows how to reach a node.
#
# `deploy.yml` calls this and does nothing else. That split is the point: the
# workflow file describes the *order*, and this file describes the *mechanism*,
# so changing how a node is reached does not mean editing five nearly-identical
# `ssh` invocations in YAML — which is how one of them ends up missing
# `set -o pipefail` and reporting success for a failed deploy.
#
# Everything runs over SSH with a deploy key that has no shell of its own. The
# remote commands are the ones an operator would type by hand and are listed in
# `deploy/README.md#bringing-a-node-up-by-hand`, deliberately: a deploy path
# that only a CI runner can execute is a deploy path that cannot be used during
# the incident where CI is the thing that is broken.
#
# Usage:
#   .github/deploy.sh n1|n2|n3 <image-tag>
#   .github/deploy.sh reconcile <image-tag>
#   .github/deploy.sh smoke n1|n2|n3
#
set -euo pipefail

ACTION="${1:?usage: deploy.sh <n1|n2|n3|reconcile|smoke> <argument>}"
ARGUMENT="${2:-}"

: "${SSH_HOST:?set SSH_HOST}"
: "${SSH_KEY:?set SSH_KEY}"

KEYFILE="$(mktemp)"
trap 'rm -f "$KEYFILE"' EXIT
printf '%s\n' "$SSH_KEY" > "$KEYFILE"
chmod 600 "$KEYFILE"

remote() {
  # `-o BatchMode=yes` so a missing key fails instead of waiting at a password
  # prompt until the job times out twenty minutes later.
  ssh -i "$KEYFILE" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=15 \
      "deploy@${SSH_HOST}" \
      "set -euo pipefail; $1"
}

case "$ACTION" in
  n1 | n2 | n3)
    TAG="${ARGUMENT:?an image tag is required}"
    echo "--- ${ACTION}: pulling ${TAG}"
    # The tag is written to the node's `.env` before the pull, so that a
    # `systemctl restart` by hand afterwards brings up the same image the deploy
    # did rather than whatever the file said last week.
    remote "
      cd /opt/graphrec/${ACTION}
      sed -i 's|^GRAPHREC_IMAGE_TAG=.*|GRAPHREC_IMAGE_TAG=${TAG}|' /opt/graphrec/.env
      grep -q '^GRAPHREC_IMAGE_TAG=' /opt/graphrec/.env
      docker compose pull --quiet
    "
    echo "--- ${ACTION}: restarting"
    # `restart`, not `stop` then `start`: the unit is `RemainAfterExit=yes` and
    # a stop/start pair leaves a window where the node is down for no reason.
    # The unit's `--wait` is what makes this block until the stack is healthy.
    remote "sudo systemctl restart graphrec-${ACTION}.service"
    remote "systemctl is-active --quiet graphrec-${ACTION}.service"
    ;;

  reconcile)
    TAG="${ARGUMENT:?an image tag is required}"
    echo "--- telling the reconciler about ${TAG}"
    # The serving replicas are not in any Compose file this script restarts.
    # Bumping the epoch is what makes the reconciler notice: it compares the
    # running containers' `com.graphrec.epoch` label against desired state and
    # rolls each tenant load-before-swap.
    remote "
      cd /opt/graphrec/n1
      docker compose exec -T control_api python -m apps.reconciler.roll --image ${TAG}
    "
    ;;

  smoke)
    NODE="${ARGUMENT:?a node is required}"
    echo "--- smoke: ${NODE}"
    # Run on the node rather than from the runner. The N2 check reads
    # Prometheus on the tunnel, and the runner is not on the tunnel — a smoke
    # test that only works from GitHub's network is one that cannot be re-run
    # by the person holding the incident.
    remote "
      cd /opt/graphrec
      SMOKE_CONSOLE_URL='${SMOKE_CONSOLE_URL:-}' \
      SMOKE_API_URL='${SMOKE_API_URL:-}' \
      SMOKE_PROMETHEUS_URL='${SMOKE_PROMETHEUS_URL:-}' \
      SMOKE_MINIO_URL='${SMOKE_MINIO_URL:-}' \
      ./scripts/ops/smoke.sh ${NODE}
    "
    ;;

  *)
    echo "unknown action '${ACTION}'" >&2
    exit 2
    ;;
esac
