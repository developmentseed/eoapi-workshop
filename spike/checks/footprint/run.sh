#!/usr/bin/env bash
# Footprint of one participant's stack: memory and CPU per container, idle and
# under self-generated load, then requests/limits and pods-per-node.
#
# Prereq: the stack is up (docker compose -p eoapi-spike -f spike/compose.participant.yml up -d --wait).
# Does not restart or reconfigure any service. It installs rioxarray/xarray/pandas
# into /tmp/spike-footprint-pylib INSIDE the Lab container (the conda env other
# kernels use is untouched) and removes it at the end.
#
# Timeline (docker stats every 2 s throughout; cgroup snapshot before/after each load):
#   idle 7 s | titiler 200 tiles | tipg 100 tiles | stac 50 searches | kernel ~500 MB
#   rioxarray load | all four at once (fresh tile set) | post 10 s
# Load runs in throwaway containers sharing the Lab's netns (not charged to the stack).
# Then, outside the stack: image sizes (registry, linux/amd64), disk, GDAL's default
# cache with/without a cgroup limit, and the raster job again under --memory 3g.
# Takes ~6 min; the host must stay awake (a stalled sampler fails sampler.cadence).
# FOOTPRINT_SEED=<n> replays a previous run's exact requests.
#
# Usage: run.sh [label]   (label: results dir name, default "latest"; e.g. cold, then warm)
# Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
# Tables: results/<label>/analysis.txt. Raw data: results/<label>/*.
# Re-analyse saved data: python3 analyze.py results/<label>
set -uo pipefail
cd "$(dirname "$0")"
R=results/${1:-latest}
LAB=eoapi-spike-lab-1
IMG=eoapi-spike-lab
SAMPLER=""

# Also on interruption: a killed run once left a load container and the pip dir behind.
cleanup() {
  [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null
  for c in $(docker ps -aq --filter name=spike-footprint-); do docker rm -f "$c" >/dev/null; done
  docker exec "$LAB" rm -rf /tmp/spike-footprint-pylib 2>/dev/null
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED docker — daemon not reachable from this shell"; exit 0
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$LAB" 2>/dev/null)" != true ]; then
  echo "BLOCKED stack — $LAB is not running"; exit 0
fi
LAB_TOKEN=$(grep '^LAB_TOKEN=' ../../.env | cut -d= -f2-)
# New seed per run = fresh tile set = cold titiler caches; pass one to replay a run.
FOOTPRINT_SEED=${FOOTPRINT_SEED:-$(date +%s)}
export LAB_TOKEN FOOTPRINT_SEED

rm -rf "$R"; mkdir -p "$R"
now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }
phase() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$R/phases.tsv"; }

python3 probe.py sample "$R/samples.csv" "$R/.stop" &
SAMPLER=$!

python3 probe.py snap pre-idle "$R/snaps.jsonl"
t=$(now); sleep 7; phase idle "$t" "$(now)"

# After the idle window: the install's page cache would otherwise count as Lab idle memory.
docker exec "$LAB" /entrypoint.sh pip install --quiet --no-cache-dir --no-deps \
  --target /tmp/spike-footprint-pylib rioxarray==0.23.0 xarray==2026.9.0 pandas==3.0.6 \
  >/dev/null 2>"$R/pip.err" || echo "FAIL setup.rioxarray — pip install into the Lab's /tmp failed (results/pip.err)"

load() { # <mode> <tile set>
  python3 probe.py snap "pre-$1" "$R/snaps.jsonl"
  local t; t=$(now)
  docker run --rm -i --init --name "spike-footprint-load-$1" --network "container:$LAB" -e LAB_TOKEN -e FOOTPRINT_SEED \
    "$IMG" /entrypoint.sh python - "$1" "$2" < load.py >> "$R/load.jsonl" 2>> "$R/load.err"
  phase "$1" "$t" "$(now)"
  python3 probe.py snap "post-$1" "$R/snaps.jsonl"
  t=$(now); sleep 6; phase "settle-$1" "$t" "$(now)"
}
load titiler a
load tipg a
load stac a
load kernel a
load all b
t=$(now); sleep 10; phase post "$t" "$(now)"

touch "$R/.stop"; wait "$SAMPLER"; rm -f "$R/.stop"
docker exec "$LAB" rm -rf /tmp/spike-footprint-pylib

python3 probe.py images "$R/images.json"

# Disk: container writable layers (ephemeral storage on k8s) and the Postgres data dir.
docker ps -s --filter label=com.docker.compose.project=eoapi-spike --format '{{.Names}}\t{{.Size}}' > "$R/disk.tsv"
printf 'pgdata MiB\t%s\n' "$(docker exec eoapi-spike-database-1 sh -c 'du -sm "$PGDATA" | cut -f1')" >> "$R/disk.tsv"

# Default GDAL block cache in the Lab image, with and without a cgroup memory limit.
q='from osgeo import gdal; print(gdal.GetCacheMax() // 2**20)'
printf 'nolimit\t%s\n' "$(docker run --rm "$IMG" /entrypoint.sh python -c "$q" 2>&1 | tail -1)" > "$R/gdal.tsv"
printf 'limit4g\t%s\n' "$(docker run --rm --memory 4g "$IMG" /entrypoint.sh python -c "$q" 2>&1 | tail -1)" >> "$R/gdal.tsv"

# The same raster job under a k8s-like 3 GiB limit (the recommended Lab limit),
# outside the stack: GDAL sizes its default block cache from the cgroup limit.
docker run --rm -i --init --name spike-footprint-kernel-3g --memory 3g --memory-swap 3g "$IMG" sh -c \
  '/entrypoint.sh pip install --quiet --no-cache-dir --no-deps --target /tmp/spike-footprint-pylib \
     rioxarray==0.23.0 xarray==2026.9.0 pandas==3.0.6 >/dev/null 2>&1 && /entrypoint.sh python - inline x' \
  < load.py > "$R/kernel-3g.jsonl" 2>> "$R/load.err"

python3 analyze.py "$R" | tee "$R/run.out"
[ "${PIPESTATUS[0]}" = 0 ] || echo "FAIL analyze — analyze.py exited non-zero"
exit 0
