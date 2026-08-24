#!/usr/bin/env bash
# Regenerate the console's view of the API contract.
#
# Two artefacts, one source of truth:
#
#   frontend/openapi.json      the document FastAPI produces from the routers
#   frontend/src/api/types.gen.ts   the TypeScript types produced from that
#
# Both are checked in rather than fetched at build time, so that a type
# definition does not change depending on which branch happens to be deployed
# when someone runs `npm run build`.
#
#   scripts/gen-client.sh            regenerate in place
#   scripts/gen-client.sh --check    fail if the checked-in files are stale
#
# The `--check` form is what CI runs. Drift here means a router changed and the
# console was not told, which is exactly the failure that otherwise shows up
# much later as a runtime `undefined`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="${ROOT}/frontend"
SPEC="${FRONTEND}/openapi.json"
TYPES="${FRONTEND}/src/api/types.gen.ts"

PYTHON="${PYTHON:-${ROOT}/.venv/bin/python}"
OPENAPI_TS="${FRONTEND}/node_modules/.bin/openapi-typescript"

check=0
if [[ "${1:-}" == "--check" ]]; then
  check=1
elif [[ $# -gt 0 ]]; then
  echo "usage: $(basename "$0") [--check]" >&2
  exit 64
fi

if [[ ! -x "${PYTHON}" ]]; then
  echo "no interpreter at ${PYTHON}; set PYTHON= to override" >&2
  exit 1
fi
if [[ ! -x "${OPENAPI_TS}" ]]; then
  echo "openapi-typescript is not installed; run 'npm install' in ${FRONTEND}" >&2
  exit 1
fi

if [[ ${check} -eq 1 ]]; then
  # Generate into a scratch copy and compare, so a --check run never leaves the
  # working tree different from how it found it.
  scratch="$(mktemp -d)"
  trap 'rm -rf "${scratch}"' EXIT
  cp "${SPEC}" "${scratch}/openapi.json"
  cp "${TYPES}" "${scratch}/types.gen.ts"
fi

"${PYTHON}" "${ROOT}/scripts/gen_openapi.py"
"${OPENAPI_TS}" "${SPEC}" -o "${TYPES}"

if [[ ${check} -eq 1 ]]; then
  status=0
  diff -u "${scratch}/openapi.json" "${SPEC}" || status=1
  diff -u "${scratch}/types.gen.ts" "${TYPES}" || status=1
  if [[ ${status} -ne 0 ]]; then
    # Put the tree back the way CI found it before failing.
    cp "${scratch}/openapi.json" "${SPEC}"
    cp "${scratch}/types.gen.ts" "${TYPES}"
    echo >&2
    echo "The API contract has drifted from the generated client." >&2
    echo "Run scripts/gen-client.sh and commit the result." >&2
    exit 1
  fi
  echo "generated client is up to date"
fi
