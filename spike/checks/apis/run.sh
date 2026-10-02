#!/usr/bin/env bash
# The three APIs under their prefixes, through the Lab (spike/compose.participant.yml):
# STAC /stac, raster /raster, vector /vector; the same behind a simulated
# TLS-terminating ingress; and the in-pod URLs the notebooks call (8081-8084).
# Prereq: the stack is up:
#   docker compose -p eoapi-spike -f spike/compose.participant.yml up -d --wait
# Needs internet from the containers (Earth Search, S3 COGs, CDNs).
# Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
set -uo pipefail
cd "$(dirname "$0")"
LAB=eoapi-spike-lab-1
FIX=eoapi-spike-apis-sapfix  # throwaway container this script owns

if ! docker info >/dev/null 2>&1; then
  echo "BLOCKED docker — daemon not reachable from this shell"; exit 0
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$LAB" 2>/dev/null)" != true ]; then
  echo "BLOCKED stack — $LAB is not running (see spike/README.md)"; exit 0
fi

docker exec -i "$LAB" /entrypoint.sh python - < apis.py 2>&1 \
  || echo "FAIL apis.py — exited non-zero (see output above)"

# ---- proposed fix for stac.api-docs, tried on a throwaway stac-auth-proxy ----
# Same image, joins the pod netns on port 18094 (nothing published), removed after.
# A non-empty SWAGGER_UI_INIT_OAUTH makes stac-auth-proxy serve its own Swagger UI,
# which prefixes the spec URL with ROOT_PATH (handlers/swagger_ui.py).
docker rm -f "$FIX" >/dev/null 2>&1
if docker run -d --rm --name "$FIX" --network "container:$LAB" \
  -e PORT=18094 -e ROOT_PATH=/stac -e UPSTREAM_URL=http://localhost:8081 \
  -e OIDC_DISCOVERY_URL=http://localhost:18888/oidc/.well-known/openid-configuration \
  -e OIDC_DISCOVERY_INTERNAL_URL=http://localhost:8085/oidc/.well-known/openid-configuration \
  -e DEFAULT_PUBLIC=true -e WAIT_FOR_UPSTREAM=true \
  -e SWAGGER_UI_INIT_OAUTH='{"clientId":"stac-api-docs","usePkceWithAuthorizationCodeGrant":true}' \
  ghcr.io/developmentseed/stac-auth-proxy:v1.2.0 >/dev/null 2>&1; then
  docker exec -i "$LAB" /entrypoint.sh python - <<'EOF' 2>&1
import re, time, httpx
url = "http://localhost:18094/stac/api.html"
for _ in range(60):
    try:
        r = httpx.get(url, timeout=5)
        if r.status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    print("FAIL fix.stac-api-docs — throwaway proxy never answered on :18094"); raise SystemExit
spec = re.findall(r"url: *'([^']*)'", r.text)
s = httpx.get(f"http://localhost:18094{spec[0]}", timeout=30) if spec else None
ok = spec == ["/stac/api"] and s is not None and s.status_code == 200 and s.json().get("openapi")
print(f"{'PASS' if ok else 'FAIL'} fix.stac-api-docs — with SWAGGER_UI_INIT_OAUTH set, api.html loads its spec from {spec} -> {s.status_code if s else '-'} openapi={s.json().get('openapi') if s else '-'}")
EOF
  docker rm -f "$FIX" >/dev/null 2>&1
else
  echo "BLOCKED fix.stac-api-docs — could not start the throwaway stac-auth-proxy"
fi
exit 0
