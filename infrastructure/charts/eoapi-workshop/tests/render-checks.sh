#!/usr/bin/env bash
#
# Render-level tests for the eoapi-workshop chart (the "unit tests" for Helm:
# assert what `helm template` produces). Run after `helm dependency build`.
#
#   ./tests/render-checks.sh
#
# Exits non-zero on any failed assertion.
set -uo pipefail

CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REL=eoapi
NS=eoapi
fail=0

# Render a single template file in isolation (keeps assertions unambiguous).
show() { helm template "$REL" "$CHART_DIR" -n "$NS" --show-only "$1" "${@:2}" 2>/dev/null; }

# NOTE: use here-strings (<<<), not `printf | grep`. Under `set -o pipefail`,
# `grep -q` short-circuits on a match and closes the pipe, so printf dies with
# SIGPIPE and pipefail reports the pipeline as failed → false negatives on large
# inputs. Here-strings have no pipe, so no SIGPIPE.
check_count() { # <rendered> <pattern> <expected> <desc>
  local n; n=$(grep -cE "$2" <<<"$1") || true
  if [[ "$n" == "$3" ]]; then printf '  ok   %-52s %s\n' "$4" "$n"
  else printf '  FAIL %-52s expected %s got %s\n' "$4" "$3" "$n"; fail=1; fi
}
check_has() { # <rendered> <pattern> <desc>
  if grep -qE "$2" <<<"$1"; then printf '  ok   %s\n' "$3"
  else printf '  FAIL %s (pattern: %s)\n' "$3" "$2"; fail=1; fi
}
check_absent() { # <rendered> <pattern> <desc>
  if grep -qE "$2" <<<"$1"; then printf '  FAIL %s (should be absent: %s)\n' "$3" "$2"; fail=1
  else printf '  ok   %s\n' "$3"; fi
}

echo "== Jupyter (templates/jupyter.yaml) =="
J="$(show templates/jupyter.yaml)"
check_count "$J" '^kind: Deployment'            5 "5 Lab Deployments"
check_count "$J" '^kind: Service'               5 "5 Lab Services"
check_count "$J" '^kind: PersistentVolumeClaim' 5 "5 Lab PVCs"
check_has   "$J" 'type: Recreate'                 "Deployment strategy Recreate (RWO PVC safe)"
check_has   "$J" 'tcpSocket:'                      "TCP probe (no auth endpoint)"
check_absent "$J" 'ServerApp.base_url'            "no base_url (each Lab served at its subdomain root)"
check_has   "$J" 'name: eoapi-pguser-eoapi'       "PG creds from PGO secret"
check_has   "$J" 'key: host'                       "PG direct-primary host key"
check_absent "$J" 'key: pgbouncer'                 "does NOT use pgbouncer secret keys (DDL/COPY safe)"
check_has   "$J" 'eoapi-stac-auth-proxy:8080'      "STAC endpoint injected"
check_has   "$J" 'browser\.eoapi-workshop\.ds\.io' "browser endpoint → subdomain"
check_has   "$J" 'STAC_API_BROWSER_URL.*stac\.eoapi-workshop\.ds\.io'   "browser-facing STAC API URL injected"
check_has   "$J" 'TITILER_BROWSER_URL.*raster\.eoapi-workshop\.ds\.io'  "browser-facing titiler URL injected"
check_has   "$J" 'TIPG_BROWSER_URL.*vector\.eoapi-workshop\.ds\.io'     "browser-facing tipg URL injected"
J_OFF="$(show templates/jupyter.yaml --set jupyter.enabled=false)"
check_count "$J_OFF" '^kind: Deployment' 0 "jupyter.enabled=false renders nothing"

echo "== stac-manager (subchart) =="
ALL="$(helm template "$REL" "$CHART_DIR" -n "$NS" 2>/dev/null)"
check_has "$ALL" 'name: eoapi-stac-manager'    "Service/Deployment named eoapi-stac-manager (fullnameOverride)"
check_has "$ALL" 'REACT_APP_STAC_API'          "STAC API env wired"
check_has "$ALL" 'REACT_APP_OIDC_AUTHORITY'    "OIDC authority env wired"
ALL_OFF="$(helm template "$REL" "$CHART_DIR" -n "$NS" --set 'stac-manager.enabled=false' 2>/dev/null)"
check_absent "$ALL_OFF" 'name: eoapi-stac-manager' "stac-manager.enabled=false renders nothing"

echo "== compose/chart version lockstep =="
# The notebooks bake in service routes, which change between releases
# (e.g. /map → /map.html in titiler-pgstac 3.x). Both environments must run the
# SAME versions or the notebooks can only be correct in one of them. Assert the
# rendered chart uses the exact image:tag pinned in docker-compose.yml.
COMPOSE="${CHART_DIR}/../../../docker-compose.yml"
for svc in titiler-pgstac tipg stac-fastapi-pgstac; do
  img=$(grep -oE "image: \S*/${svc}:\S+" "$COMPOSE" | head -1 | awk '{print $2}')
  check_has "$ALL" "$(sed 's/[.[]/\\&/g' <<<"$img")" "chart runs compose's ${img##*/}"
done
check_has "$ALL" 'TITILER_PGSTAC_API_ENABLE_EXTERNAL_DATASET_ENDPOINTS' "raster external-dataset endpoints enabled (notebook 04 §4.4)"

echo "== auth wiring =="
# The proxy fetches JWKS from OIDC_DISCOVERY_URL's origin, so it MUST be the
# in-cluster URL — an external LB URL hairpins from the pod (401). If someone
# sets it external, this in-cluster value line disappears and the check fails.
check_has "$ALL" 'value: "http://eoapi-mock-oidc-server\.eoapi\.svc\.cluster\.local:8080/\.well-known/openid-configuration"' "proxy OIDC_DISCOVERY_URL is in-cluster (JWKS reachable)"

echo "== Subdomain ingress (templates/subdomain-ingress.yaml) =="
I="$(show templates/subdomain-ingress.yaml)"
check_count "$I" 'host: (stac|raster|vector|browser|manager|mock-oidc)\.eoapi-workshop\.ds\.io' 6 "6 core-service subdomains"
check_count "$I" 'host: lab-0[1-5]\.eoapi-workshop\.ds\.io' 5 "5 lab subdomains"
check_has   "$I" 'name: eoapi-stac-auth-proxy' "stac subdomain → auth-proxy backend"
check_has   "$I" 'name: eoapi-stac-manager'    "manager subdomain → stac-manager backend"
check_absent "$I" 'rewrite-target'             "no path rewrite (root serving)"

echo "== features loader + tipg schema =="
FA="$(helm template "$REL" "$CHART_DIR" -n "$NS" 2>/dev/null)"
check_has    "$FA" 'name: eoapi-features-loader'   "features-loader Job renders"
check_has    "$FA" 'features\.ecoregions'          "loader targets features.ecoregions"
check_has    "$FA" 'name: eoapi-pguser-postgres'   "loader uses the superuser secret"
check_has    "$FA" 'TIPG_DB_SCHEMAS'               "tipg exposes the features schema"
FA_OFF="$(helm template "$REL" "$CHART_DIR" -n "$NS" --set featuresLoader.enabled=false 2>/dev/null)"
check_absent "$FA_OFF" 'name: eoapi-features-loader' "featuresLoader.enabled=false renders nothing"

if [[ "$fail" == 0 ]]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit "$fail"
