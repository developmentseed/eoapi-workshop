#!/usr/bin/env bash
#
# Render-level tests for the eoapi-workshop chart (the "unit tests" for Helm:
# assert what `helm template` produces). Run after `helm dependency build`.
#
#   ./tests/render-checks.sh
#
# Exits non-zero on any failed assertion.
set -uo pipefail

CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REL=eoapi
NS=eoapi
fail=0

# Render a single template file in isolation (keeps assertions unambiguous).
show() { helm template "$REL" "$CHART_DIR" -n "$NS" --show-only "$1" "${@:2}" 2>/dev/null; }

check_count() { # <rendered> <pattern> <expected> <desc>
  local n; n=$(printf '%s\n' "$1" | grep -cE "$2")
  if [[ "$n" == "$3" ]]; then printf '  ok   %-52s %s\n' "$4" "$n"
  else printf '  FAIL %-52s expected %s got %s\n' "$4" "$3" "$n"; fail=1; fi
}
check_has() { # <rendered> <pattern> <desc>
  if printf '%s\n' "$1" | grep -qE "$2"; then printf '  ok   %s\n' "$3"
  else printf '  FAIL %s (pattern: %s)\n' "$3" "$2"; fail=1; fi
}
check_absent() { # <rendered> <pattern> <desc>
  if printf '%s\n' "$1" | grep -qE "$2"; then printf '  FAIL %s (should be absent: %s)\n' "$3" "$2"; fail=1
  else printf '  ok   %s\n' "$3"; fi
}

echo "== Jupyter (templates/jupyter.yaml) =="
J="$(show templates/jupyter.yaml)"
check_count "$J" '^kind: Deployment'            5 "5 Lab Deployments"
check_count "$J" '^kind: Service'               5 "5 Lab Services"
check_count "$J" '^kind: PersistentVolumeClaim' 5 "5 Lab PVCs"
check_has   "$J" 'type: Recreate'                 "Deployment strategy Recreate (RWO PVC safe)"
check_has   "$J" 'tcpSocket:'                      "TCP probe (no auth endpoint)"
check_has   "$J" 'ServerApp.base_url=/lab/lab-01' "base_url set per participant"
check_has   "$J" 'name: eoapi-pguser-eoapi'       "PG creds from PGO secret"
check_has   "$J" 'key: host'                       "PG direct-primary host key"
check_absent "$J" 'key: pgbouncer'                 "does NOT use pgbouncer secret keys (DDL/COPY safe)"
check_has   "$J" 'eoapi-stac-auth-proxy:8080'      "STAC endpoint injected"
J_OFF="$(show templates/jupyter.yaml --set jupyter.enabled=false)"
check_count "$J_OFF" '^kind: Deployment' 0 "jupyter.enabled=false renders nothing"

echo "== Passthrough ingress (templates/passthrough-ingress.yaml) =="
I="$(show templates/passthrough-ingress.yaml)"
check_count "$I" 'path: /lab/lab-0[1-5]' 5 "5 /lab/<name> ingress paths"

if [[ "$fail" == 0 ]]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit "$fail"
