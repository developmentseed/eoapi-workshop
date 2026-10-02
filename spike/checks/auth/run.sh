#!/usr/bin/env bash
# Auth checks for the one-participant stack (spike/compose.participant.yml).
# Prereq: the stack is up:
#   docker compose -p eoapi-spike -f spike/compose.participant.yml up -d --wait
# Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
# Never prints the Lab token/password or a JWT (common.py redact()).
#
# Vantage points:
#   inpod   docker exec into the Lab: the notebook kernel's view (localhost = pod)
#   laptop  throwaway container, own netns, via host.docker.internal:18888 (the
#           published port) = a participant's laptop
#   offpod  throwaway container on the compose network, no credentials = another pod
# Data created (then deleted): collections spike-auth-test, spike-auth-test-cookie,
# spike-auth-inpod (+ item), spike-auth-offpod-proxy, spike-auth-offpod-direct.
set -uo pipefail
cd "$(dirname "$0")"
SPIKE=$(cd ../.. && pwd)
ENVF="$SPIKE/.env"
LAB=eoapi-spike-lab-1
NET=eoapi-spike_default
IMG=eoapi-spike-lab

if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED docker — daemon not reachable from this shell"; exit 0
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$LAB" 2>/dev/null)" != true ]; then
  echo "BLOCKED stack — $LAB is not running (docker compose -p eoapi-spike ... up -d --wait)"; exit 0
fi

cat common.py inpod.py | docker exec -i "$LAB" /entrypoint.sh python - 2>&1 \
  || echo "FAIL inpod.py — exited non-zero (see output above)"
# The container's clock, not the host's: `docker logs --since` compares against the
# Docker VM's timestamps, which lagged the host by ~4 min after a sleep (verify stage).
since=$(docker exec eoapi-spike-stac-fastapi-1 date -u +%Y-%m-%dT%H:%M:%SZ)
cat common.py laptop.py | docker run --rm -i -v "$ENVF:/run/spike.env:ro" "$IMG" /entrypoint.sh python - 2>&1 \
  || echo "FAIL laptop.py — exited non-zero (see output above)"
# Cause of laptop.stac.get-with-lab-token, and where the token ends up.
tok=$(grep '^LAB_TOKEN=' "$ENVF" | cut -d= -f2)
n=$(docker logs --since "$since" eoapi-spike-stac-fastapi-1 2>&1 | grep 'Could not find item using token' | grep -cF "$tok")
if [ "$n" -gt 0 ]; then
  echo "FAIL laptop.stac.lab-token-in-error-log — stac-fastapi logged $n x 'asyncpg RaiseError: Could not find item using token: <LAB_TOKEN>' during this run (pgstac took ?token= as its cursor)"
else
  echo "PASS laptop.stac.lab-token-in-error-log — no pgstac cursor error carrying the Lab token since $since"
fi
# offpod gets no credentials at all (no .env mount).
cat common.py offpod.py | docker run --rm -i --network "$NET" -e LAB_TOKEN=unset "$IMG" /entrypoint.sh python - 2>&1 \
  || echo "FAIL offpod.py — exited non-zero (see output above)"

exit 0
