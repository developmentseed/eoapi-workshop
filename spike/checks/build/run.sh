#!/usr/bin/env bash
# Build/smoke checks for the one-participant stack (spike/compose.participant.yml).
# Prereq: the stack is up:
#   docker compose -p eoapi-spike -f spike/compose.participant.yml up -d --wait
# Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
set -uo pipefail
cd "$(dirname "$0")"
P=(docker compose -p eoapi-spike -f ../../compose.participant.yml)
LAB=eoapi-spike-lab-1

if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED docker — daemon not reachable from this shell"; exit 0
fi

# ---- host-side: containers, published ports, worker counts ----
running=$("${P[@]}" ps --status running --services 2>/dev/null | sort | tr '\n' ' ')
want="database lab mock-oidc stac-auth-proxy stac-browser stac-fastapi stac-manager tipg titiler-pgstac "
[ "$running" = "$want" ] && echo "PASS compose.all-running — $running" \
  || { echo "FAIL compose.all-running — running: $running"; }

ports=$(docker ps --filter label=com.docker.compose.project=eoapi-spike --format '{{.Names}} {{.Ports}}' | awk 'NF>1')
[ "$ports" = "$LAB 127.0.0.1:18888->18888/tcp" ] && echo "PASS compose.only-lab-published — $ports" \
  || echo "FAIL compose.only-lab-published — $ports"

for s in stac-fastapi titiler-pgstac tipg mock-oidc; do
  n=$(docker top "eoapi-spike-$s-1" -o pid,args | grep -c '[u]vicorn')
  [ "$n" = 1 ] && echo "PASS workers.$s — 1 uvicorn process" || echo "FAIL workers.$s — $n uvicorn processes"
done

native=$(docker version -f '{{.Server.Arch}}')
for s in lab database stac-fastapi titiler-pgstac tipg stac-auth-proxy mock-oidc stac-browser stac-manager; do
  a=$(docker image inspect "$(docker inspect -f '{{.Image}}' "eoapi-spike-$s-1")" -f '{{.Architecture}}')
  case $s in stac-browser|stac-manager) want=amd64 ;; *) want=$native ;; esac  # amd64 only, emulated elsewhere
  [ "$a" = "$want" ] && echo "PASS arch.$s — $a" || echo "FAIL arch.$s — $a, want $want"
done

# ---- inside the pod netns: every service directly and through the Lab proxy ----
docker exec -i "$LAB" /entrypoint.sh python - < smoke.py 2>&1 \
  || echo "FAIL smoke.py — exited non-zero (see output above)"
docker exec -i "$LAB" /entrypoint.sh python - < contract.py 2>&1 \
  || echo "FAIL contract.py — exited non-zero (see output above)"

# ---- another netns on the same network: what a neighbouring pod would see ----
pgpw=$(grep '^POSTGRES_PASSWORD=' ../../.env | cut -d= -f2)
docker run --rm -i --network eoapi-spike_default -e PGPASSWORD="$pgpw" \
  eoapi-spike-lab /entrypoint.sh python - < offpod.py 2>&1 \
  || echo "FAIL offpod.py — exited non-zero (see output above)"
exit 0
