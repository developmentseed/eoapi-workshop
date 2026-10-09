#!/usr/bin/env bash
# Warm every participant's titiler: notebook 04's glad map opens on these six z2
# tiles (North America and Europe), which take one to two minutes cold and about
# a second warm. Run after each deploy or pod restart.
#
#   participant/warm.sh CONTEXT NAMESPACE        # RELEASE=participants, PARALLEL=5
set -euo pipefail
[ $# = 2 ] || { sed -n '2,6p' "$0" >&2; exit 2; }
CTX=$1 NS=$2 REL=${RELEASE:-participants}
TILES='2/0/0 2/1/0 2/2/0 2/0/1 2/1/1 2/2/1'
URL='http://localhost:8082/raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/%s?assets=lossyear&colormap_name=viridis&rescale=0%%2C23'
PY='import sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
t = time.time()
with ThreadPoolExecutor(6) as ex:
    s = list(ex.map(lambda z: urllib.request.urlopen(sys.argv[1] % z, timeout=600).status, sys.argv[3].split()))
print(f"{sys.argv[2]} HTTP {sorted(set(s))} in {time.time() - t:.1f} s", flush=True)'
kubectl --context "$CTX" -n "$NS" get pods -l app.kubernetes.io/instance="$REL" \
  -o jsonpath='{range .items[*]}{.metadata.labels.participant}{"\n"}{end}' \
  | xargs -P "${PARALLEL:-5}" -I{} kubectl --context "$CTX" -n "$NS" exec "deploy/$REL-{}" -c lab -- python -c "$PY" "$URL" {} "$TILES"
