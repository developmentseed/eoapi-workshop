#!/usr/bin/env bash
# Execute docs/00..08 headless on copies inside the Lab container, then report every
# errored cell (with its class) and check every browser-facing URL through the Lab.
# Prereq: the stack is up (spike/README.md). Prints PASS|FAIL|BLOCKED lines; exits 0.
#
#   spike/checks/notebooks/run.sh                 # all phases (~2 min), see nbrun.py
#   PHASES="docs" spike/checks/notebooks/run.sh
#   PHASES= spike/checks/notebooks/run.sh         # report only, on the last executed copies
#   POINTS=0 spike/checks/notebooks/run.sh        # skip the 100 earth-search counts
#
# Writes only ids under spike-notebooks-* (private-<owner>-spike-notebooks* where the
# row-level filter needs the prefix). `reset` drops those first; 06-08 (`writes`, last)
# delete what they create; 02's spike-notebooks-sentinel-2-c1-l2a stays for 03/04.
set -uo pipefail
cd "$(dirname "$0")"
LAB=eoapi-spike-lab-1
BIN=/tmp/nbrun-notebooks/bin
PHASES=${PHASES-reset docs writes audit}

if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED docker — daemon not reachable from this shell"; exit 0
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$LAB" 2>/dev/null)" != true ]; then
  echo "BLOCKED stack — $LAB is not running (see spike/README.md)"; exit 0
fi

docker exec "$LAB" mkdir -p "$BIN"
for f in nbrun.py fixes.py report.py points.py probes.py compose_env.py ../../../docker-compose.yml; do
  docker cp "$f" "$LAB:$BIN/$(basename "$f")" >/dev/null
done

if [ -n "$PHASES" ]; then
  # shellcheck disable=SC2086
  docker exec "$LAB" /entrypoint.sh python "$BIN/nbrun.py" $PHASES \
    || echo "FAIL nbrun.py — exited non-zero"
fi
# Direct repros of the two pre-existing bugs (needs the docs phase's collection).
docker exec "$LAB" /entrypoint.sh python "$BIN/probes.py" || echo "FAIL probes.py — exited non-zero"
# The notebooks need the repo's compose to set the *_BROWSER_URL contract too.
docker exec "$LAB" /entrypoint.sh python "$BIN/compose_env.py" "$BIN/docker-compose.yml" || echo "FAIL compose_env.py — exited non-zero"
if [ "${POINTS-1}" != 0 ]; then
  docker exec "$LAB" /entrypoint.sh python "$BIN/points.py" || echo "FAIL points.py — exited non-zero"
fi
docker exec "$LAB" /entrypoint.sh python "$BIN/report.py" \
  || echo "FAIL report.py — exited non-zero"

# Executed copies for inspection (gitignored).
rm -rf out && mkdir -p out
for p in docs writes; do
  docker cp "$LAB:/tmp/nbrun-notebooks/$p/out" "out/$p" >/dev/null 2>&1 || true
done
exit 0
