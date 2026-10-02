#!/usr/bin/env bash
# More chart tests on the local kind cluster (release and namespace `participants`):
# cookie isolation, an image bump restarting every pod (render), persistence across
# pod replacement. Run after frontdoor-own/run.sh.
# Prints PASS|FAIL|BLOCKED <name> — <detail>; never prints a secret; exits 0.
# Mutates kind only: replaces u01's pod (rollout restart) to test persistence.
set -uo pipefail
cd "$(dirname "$0")"
ROOT=$(cd ../.. && pwd)
KC="$ROOT/.kind-kubeconfig"
K=(kubectl --kubeconfig "$KC" --context kind-eoapi-participant -n participants)
say() { echo "$1 $2 — $3"; }
ok() { if eval "$1"; then say PASS "$2" "$3"; else say FAIL "$2" "$3"; fi; }
if ! "${K[@]}" get deploy participants-u01 >/dev/null 2>&1; then say BLOCKED cluster "release participants not found"; exit 0; fi

sec() { "${K[@]}" get secret participants-credentials -o jsonpath="{.data.$1}" | base64 -d; }
export U01_PASSWORD="$(sec u01-password)" U02_PASSWORD="$(sec u02-password)"
py() { docker run --rm -i --network kind -e U01_PASSWORD -e U02_PASSWORD eoapi-participant-lab python - "$@" < own_extra.py 2>&1 | grep -E '^(PASS|FAIL|BLOCKED)' || say FAIL own_extra "$1: no result line"; }

# 1. A u01 login cookie must not open u02's Lab (cookie secrets differ per pod).
py cookie

# 2. A new image tag (a notebook fix mid-event) changes every participant's pod template.
hashes() {
  helm template participants "$ROOT/chart" -n participants "$@" 2>/dev/null | python3 -c '
import sys, yaml, hashlib, json
for d in yaml.safe_load_all(sys.stdin):
    if d and d["kind"] == "Deployment":
        print(d["metadata"]["name"], hashlib.sha256(json.dumps(d["spec"]["template"], sort_keys=True).encode()).hexdigest()[:8])'
}
a=$(hashes); b=$(hashes --set image.tag=bumped)
changed=$(diff <(echo "$a") <(echo "$b") | grep -c '^>')
total=$(echo "$a" | wc -l | tr -d ' ')
ok '[ "$changed" = "$total" ]' upgrade.image-bump-replaces-every-pod \
  "render with image.tag bumped: $changed of $total participant pod templates change (strategy Recreate → every stack restarts; DB and work/ are on PVCs)"

# 3. Pod replacement (eviction, node loss, template change): is participant data kept?
py write
"${K[@]}" rollout restart deploy/participants-u01 >/dev/null && "${K[@]}" rollout status deploy/participants-u01 --timeout=5m >/dev/null
py read
exit 0
