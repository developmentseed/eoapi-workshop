#!/usr/bin/env bash
# Warm every participant's titiler: notebook 04's world-view glad tile takes about
# 2 minutes cold and about a second warm. Run after each deploy or pod restart.
#
#   spike/warm.sh CONTEXT NAMESPACE        # RELEASE=participants, PARALLEL=5
set -euo pipefail
[ $# = 2 ] || { sed -n '2,5p' "$0" >&2; exit 2; }
CTX=$1 NS=$2 REL=${RELEASE:-participants}
URL='http://localhost:8082/raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/0/0/0?assets=lossyear&colormap_name=viridis&rescale=0%2C23'
PY='import sys, time, urllib.request
t = time.time(); s = urllib.request.urlopen(sys.argv[1], timeout=600).status
print(f"{sys.argv[2]} HTTP {s} in {time.time() - t:.1f} s", flush=True)'
kubectl --context "$CTX" -n "$NS" get pods -l app.kubernetes.io/instance="$REL" \
  -o jsonpath='{range .items[*]}{.metadata.labels.participant}{"\n"}{end}' \
  | xargs -P "${PARALLEL:-5}" -I{} kubectl --context "$CTX" -n "$NS" exec "deploy/$REL-{}" -c lab -- python -c "$PY" "$URL" {}
