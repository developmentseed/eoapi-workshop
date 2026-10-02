#!/usr/bin/env bash
# Verify stage: re-run every compose topic's run.sh against the running
# eoapi-spike stack, one after the other, raw output to spike/evidence/.verify-<topic>.log
# (gitignored) and one summary line per topic on stdout.
set -uo pipefail
cd "$(dirname "$0")/.."
EV=../evidence
for t in build apis auth browser-apps notebooks footprint; do
  s=$(date -u +%FT%TZ)
  if [ $t = footprint ]; then ./$t/run.sh verify; else ./$t/run.sh; fi > "$EV/.verify-$t.log" 2>&1
  e=$(date -u +%FT%TZ)
  echo "$t $s..$e PASS=$(grep -c '^PASS' "$EV/.verify-$t.log") FAIL=$(grep -c '^FAIL' "$EV/.verify-$t.log") BLOCKED=$(grep -c '^BLOCKED' "$EV/.verify-$t.log")"
done
