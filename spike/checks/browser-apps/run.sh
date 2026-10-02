#!/usr/bin/env bash
# Browser checks for one participant stack: headless Chromium (Playwright) in a
# container sharing the Lab's network namespace, so http://localhost:18888 is
# the participant's URL and a secure context. Plus HTTP probes behind the
# findings and a validation of the two proposed stac-manager fixes.
# Prereq: the stack is up (spike/README.md). Prints one line per check:
# PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
# Screenshots and the console/network log go to spike/evidence/screens/.
#
# Containers it starts and removes again (never the stack's own):
#   eoapi-spike-ba-rootpath-stac   stac-fastapi --root-path /stac on :18981 (in the Lab netns)
#   eoapi-spike-ba-rootpath-proxy  stac-auth-proxy on :18982 -> :18981, same env as the live one
#   a --rm stac-manager container that only runs the proposed scope sed
set -uo pipefail
cd "$(dirname "$0")"
HERE=$PWD
SPIKE=$(cd ../.. && pwd)
LAB=eoapi-spike-lab-1
PW_IMAGE=eoapi-spike-playwright
SF=eoapi-spike-ba-rootpath-stac
PX=eoapi-spike-ba-rootpath-proxy
# Proposed fix 2 (compose `command` / chart `args` of stac-manager), verbatim:
SCOPE_SED="sed -i 's/scope:\"openid profile email offline_access\"/scope:\"openid profile email offline_access stac:write\"/' packages/client/dist/client.*.js"

if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED docker — daemon not reachable from this shell"; exit 0
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$LAB" 2>/dev/null)" != true ]; then
  echo "BLOCKED stack — $LAB is not running"; exit 0
fi
if ! docker build -q -t "$PW_IMAGE" . >/dev/null; then
  echo "BLOCKED playwright-image — docker build failed"; exit 0
fi
in_pod() {  # run a command in a throwaway container in the Lab's netns
  docker run --rm --network "container:$LAB" --shm-size=1g \
    -v "$HERE:/checks:ro" -v "$SPIKE/.env:/run/spike.env:ro" -v "$SPIKE/evidence/screens:/screens" \
    "$PW_IMAGE" "$@"
}

# ---- proposed fix 1: stac-fastapi --root-path /stac, as a throwaway pair ----
docker rm -f "$SF" "$PX" >/dev/null 2>&1  # leftovers of an interrupted run
tmp=$(mktemp -d)
cleanup() { docker rm -f "$SF" "$PX" >/dev/null 2>&1; rm -rf "$tmp"; }
trap cleanup EXIT
env_of() { docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" | grep -v '^$'; }
env_of eoapi-spike-stac-fastapi-1 >"$tmp/sf.env"   # holds the DB password: temp file, removed on exit
env_of eoapi-spike-stac-auth-proxy-1 | grep -v -e '^PORT=' -e '^UPSTREAM_URL=' >"$tmp/px.env"
fix_up=true
docker run -d --name "$SF" --network "container:$LAB" --env-file "$tmp/sf.env" \
  ghcr.io/stac-utils/stac-fastapi-pgstac:7.0.0 \
  uvicorn stac_fastapi.pgstac.app:create_app --factory --host 127.0.0.1 --port 18981 --workers 1 \
  --root-path /stac >/dev/null || fix_up=false
docker run -d --name "$PX" --network "container:$LAB" --env-file "$tmp/px.env" \
  -e PORT=18982 -e UPSTREAM_URL=http://localhost:18981 \
  -v "$SPIKE/../docs/workshop_filters.py:/app/src/workshop_filters.py:ro" \
  ghcr.io/developmentseed/stac-auth-proxy:v1.2.0 >/dev/null || fix_up=false

if $fix_up; then
  in_pod python /checks/probes.py --fix 18982 2>&1 || echo "FAIL probes.py — exited non-zero"
else
  in_pod python /checks/probes.py 2>&1 || echo "FAIL probes.py — exited non-zero"
  echo "BLOCKED fix.root-path — could not start the throwaway stac-fastapi/stac-auth-proxy pair"
fi
cleanup

# ---- proposed fix 2: the scope sed, on a throwaway container of the same image ----
scopes=$(docker run --rm --network none --platform linux/amd64 ghcr.io/developmentseed/stac-manager:1.0.3 \
  sh -c "$SCOPE_SED && grep -o 'scope:\"[^\"]*\"' packages/client/dist/client.*.js | sort -u | tr '\n' ' '" 2>/dev/null \
  | tail -n 1)
case "$scopes" in
  *'offline_access stac:write"'*) echo "PASS fix.manager-scope-sed — after the entrypoint, the proposed sed leaves: $scopes";;
  *) echo "FAIL fix.manager-scope-sed — bundle scopes after the sed: ${scopes:-<none>}";;
esac

# ---- titiler's own cost for the map.html world view (before the browser warms the cache) ----
in_pod python /checks/tile_timing.py 2>&1 || echo "FAIL tile_timing.py — exited non-zero"

# ---- the browser ----
[ "${SKIP_BROWSER:-}" = 1 ] && exit 0  # probes only
mkdir -p "$SPIKE/evidence/screens"
in_pod python /checks/browser_apps.py 2>&1 || echo "FAIL browser_apps.py — exited non-zero (see output above)"
exit 0
