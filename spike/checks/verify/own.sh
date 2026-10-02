#!/usr/bin/env bash
# Verify stage: extra refutation probes against the own chart on the LOCAL kind
# cluster (release spike, namespace spike-own). Run after frontdoor-own/run.sh.
# Prints PASS|FAIL|BLOCKED <name> — <detail>; never prints a secret; exits 0.
# Mutates kind only: replaces u01's pod (rollout restart) to test persistence.
set -uo pipefail
cd "$(dirname "$0")"
SPIKE=$(cd ../.. && pwd)
KC="$SPIKE/.kind-kubeconfig"
K=(kubectl --kubeconfig "$KC" --context kind-eoapi-spike -n spike-own)
say() { echo "$1 $2 — $3"; }
ok() { if eval "$1"; then say PASS "$2" "$3"; else say FAIL "$2" "$3"; fi; }
if ! "${K[@]}" get deploy spike-u01 >/dev/null 2>&1; then say BLOCKED cluster "release spike not found"; exit 0; fi

sec() { "${K[@]}" get secret spike-credentials -o jsonpath="{.data.$1}" | base64 -d; }
export U01_PASSWORD="$(sec u01-password)" U02_PASSWORD="$(sec u02-password)"
py() { docker run --rm -i --network kind -e U01_PASSWORD -e U02_PASSWORD eoapi-spike-lab /entrypoint.sh python - "$@" < own_extra.py 2>&1 | grep -E '^(PASS|FAIL|BLOCKED)' || say FAIL own_extra "$1: no result line"; }

# 1. A u01 login cookie must not open u02's Lab (cookie secrets differ per pod).
py cookie

# 2. Does a template change in a shared value restart every participant? (render-level)
a=$(helm template spike "$SPIKE/chart" -n spike-own 2>/dev/null | python3 -c '
import sys, yaml, hashlib, json
for d in yaml.safe_load_all(sys.stdin):
    if d and d["kind"] == "Deployment":
        print(d["metadata"]["name"], hashlib.sha256(json.dumps(d["spec"]["template"], sort_keys=True).encode()).hexdigest()[:8])')
b=$(sed 's#ghcr.io/stac-utils/titiler-pgstac:3.2.0#ghcr.io/stac-utils/titiler-pgstac:3.2.1#' "$SPIKE/chart/values.yaml" > "${TMPDIR:-/tmp}/verify-values.yaml" \
  && helm template spike "$SPIKE/chart" -n spike-own -f "${TMPDIR:-/tmp}/verify-values.yaml" 2>/dev/null | python3 -c '
import sys, yaml, hashlib, json
for d in yaml.safe_load_all(sys.stdin):
    if d and d["kind"] == "Deployment":
        print(d["metadata"]["name"], hashlib.sha256(json.dumps(d["spec"]["template"], sort_keys=True).encode()).hexdigest()[:8])')
rm -f "${TMPDIR:-/tmp}/verify-values.yaml"
changed=$(diff <(echo "$a") <(echo "$b") | grep -c '^>')
total=$(echo "$a" | wc -l | tr -d ' ')
ok '[ "$changed" = "$total" ]' upgrade.image-bump-replaces-every-pod \
  "render with one shared image tag bumped: $changed of $total participant pod templates change (strategy Recreate → every stack restarts; DB and work/ are on PVCs)"

# 3. Pod replacement (eviction, node loss, template change): is participant data kept?
py write
"${K[@]}" rollout restart deploy/spike-u01 >/dev/null && "${K[@]}" rollout status deploy/spike-u01 --timeout=5m >/dev/null
py read
exit 0
