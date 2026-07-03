#!/usr/bin/env bash
#
# Reproducible deploy for the eoapi-workshop chart (subdomain-per-service).
#
# Every service is served at the root of its own subdomain under a wildcard
# domain: stac. raster. vector. browser. manager. mock-oidc. lab-01..NN. of
# ${BASE_DOMAIN}. A wildcard DNS record `*.${BASE_DOMAIN}` must point at the
# ingress LoadBalancer.
#
# Usage:
#   ./deploy.sh deploy            # prerequisites + chart + verify (idempotent)
#   ./deploy.sh verify            # re-run endpoint/auth checks + print Lab URLs
#   ./deploy.sh urls              # print the participant Lab URLs (with tokens)
#   ./deploy.sh overrides         # (re)generate + print .deploy/overrides.yaml, no deploy
#   ./deploy.sh teardown          # remove the release, PVCs and namespace
#   ./deploy.sh teardown --all    # also remove PGO (ingress-nginx + cert-manager
#                                 # are Terraform-owned and left in place)
#
# Env:
#   RELEASE       Helm release name   (default: eoapi)   -- see OIDC contract below
#   NAMESPACE     target namespace    (default: eoapi)   -- see OIDC contract below
#   BASE_DOMAIN   wildcard base domain (default: eoapi-workshop.ds.io)
#   HELM_TIMEOUT  helm --timeout for the release install (default: 15m). The
#                 pgstac post-install hooks wait for the PGO-provisioned DB,
#                 which on a cold first install can exceed helm's default 5m.
#   TLS=1         serve over HTTPS: render a Let's Encrypt ClusterIssuer
#                 (HTTP-01), annotate the ingress, and switch every browser-facing
#                 URL to https. Requires TLS_EMAIL. cert-manager is normally
#                 installed by Terraform; if absent it's installed here.
#   TLS_EMAIL     Let's Encrypt contact email (required when TLS=1).
#   CLUSTER_ISSUER  ClusterIssuer name (default: letsencrypt).
#   ACME_SERVER   ACME directory (default: LE prod; use the staging URL to avoid
#                 prod rate limits while testing — staging certs are untrusted).
#   SKIP_PREREQS=1  skip the ingress-nginx + PGO (+ cert-manager) install
#   GHCR_TOKEN     token with read:packages → create an imagePullSecret so the
#                  cluster can pull a PRIVATE workshop image (with GHCR_USER).
#                  Omit if the GHCR package is public.
#
# !!! OIDC CONTRACT !!! The proxy's OIDC_DISCOVERY_INTERNAL_URL is pinned to the
# Service DNS name eoapi-mock-oidc-server.eoapi.svc.cluster.local, derived from
# RELEASE + NAMESPACE. Both MUST stay "eoapi" or in-cluster OIDC discovery breaks.
set -euo pipefail

RELEASE="${RELEASE:-eoapi}"
NAMESPACE="${NAMESPACE:-eoapi}"
BASE_DOMAIN="${BASE_DOMAIN:-eoapi-workshop.ds.io}"
HELM_TIMEOUT="${HELM_TIMEOUT:-15m}"
# TLS=1 serves everything over HTTPS via cert-manager + Let's Encrypt (HTTP-01).
# Requires TLS_EMAIL (Let's Encrypt contact). The scheme derived here drives
# every browser-facing URL below, so http/https stay consistent end to end.
TLS="${TLS:-0}"
TLS_EMAIL="${TLS_EMAIL:-}"
CLUSTER_ISSUER="${CLUSTER_ISSUER:-letsencrypt}"
ACME_SERVER="${ACME_SERVER:-https://acme-v02.api.letsencrypt.org/directory}"
if [[ "$TLS" == "1" ]]; then SCHEME="https"; else SCHEME="http"; fi
CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERRIDES="${CHART_DIR}/.deploy/overrides.yaml"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*" >&2; }

install_prereqs() {
  if [[ "${SKIP_PREREQS:-0}" == "1" ]]; then log "Skipping prerequisites (SKIP_PREREQS=1)"; return; fi
  if kubectl get ingressclass nginx >/dev/null 2>&1; then
    log "An 'nginx' ingressclass already exists — leaving ingress-nginx untouched"
  else
    log "Installing NGINX ingress controller"
    helm upgrade --install ingress-nginx ingress-nginx \
      --repo https://kubernetes.github.io/ingress-nginx \
      --namespace ingress-nginx --create-namespace --wait --timeout 5m
  fi
  log "Installing Crunchy Postgres Operator (PGO)"
  helm upgrade --install pgo oci://registry.developers.crunchydata.com/crunchydata/pgo \
    --namespace postgres-operator --create-namespace --wait --timeout 5m
  if [[ "$TLS" == "1" ]]; then
    # cert-manager is normally installed by Terraform (cluster platform). Only
    # install it here if it's absent, so a standalone (non-Terraform) run still
    # works; if it's present we leave it alone — teardown must never remove it.
    if kubectl get crd clusterissuers.cert-manager.io >/dev/null 2>&1; then
      log "cert-manager already present — leaving it untouched"
    else
      log "Installing cert-manager (TLS enabled, not found in cluster)"
      helm upgrade --install cert-manager cert-manager \
        --repo https://charts.jetstack.io \
        --namespace cert-manager --create-namespace \
        --set crds.enabled=true --wait --timeout 5m
    fi
  fi
}

# Fail fast on a TLS misconfig before we touch the cluster.
require_tls_config() {
  [[ "$TLS" == "1" ]] || return 0
  if [[ -z "$TLS_EMAIL" ]]; then
    log "TLS=1 requires TLS_EMAIL=<you@your-org.org> (Let's Encrypt contact email)"
    exit 2
  fi
  # Let's Encrypt rejects the reserved example.* domains with an opaque
  # 'invalidContact' error that leaves the ClusterIssuer stuck (never registers,
  # so no cert ever issues). Catch the placeholder here instead of 15 min later.
  case "$TLS_EMAIL" in
    *@example.com|*@example.net|*@example.org)
      log "TLS_EMAIL='$TLS_EMAIL' uses a reserved example domain — Let's Encrypt rejects it. Use a real address."
      exit 2 ;;
  esac
}

# Participant names, read from the rendered chart (single source of truth = values).
participant_names() {
  helm template "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" \
    --show-only templates/jupyter.yaml 2>/dev/null \
    | grep -oE "^  name: ${RELEASE}-[a-z0-9-]+" | sed "s/  name: ${RELEASE}-//" | sort -u
}

# Reuse a participant's token from the existing overrides (idempotent URLs across
# re-deploys); prints nothing and returns 1 if not present.
existing_token() { # <name>
  [[ -f "$OVERRIDES" ]] || return 1
  local t; t="$(grep -E "name: $1, token:" "$OVERRIDES" 2>/dev/null | sed -E 's/.*token: "([^"]+)".*/\1/' | head -1)"
  [[ -n "$t" ]] && printf '%s' "$t"
}

# Host-specific overrides — derived, NEVER committed (gitignored .deploy/).
write_overrides() {
  mkdir -p "$(dirname "$OVERRIDES")"
  local tmp; tmp="$(mktemp)"
  {
    echo "# Generated by deploy.sh — DO NOT COMMIT. baseDomain=${BASE_DOMAIN} scheme=${SCHEME}"
    echo "routing:"
    echo "  baseDomain: \"${BASE_DOMAIN}\""
    if [[ "$TLS" == "1" ]]; then
      echo "  tls:"
      echo "    enabled: true"
      echo "    clusterIssuer: \"${CLUSTER_ISSUER}\""
      echo "    email: \"${TLS_EMAIL}\""
      echo "    acmeServer: \"${ACME_SERVER}\""
    fi
    echo "eoapi:"
    echo "  browser:"
    echo "    catalogUrl: \"${SCHEME}://stac.${BASE_DOMAIN}\""
    echo "    oidcDiscoveryUrl: \"${SCHEME}://mock-oidc.${BASE_DOMAIN}/.well-known/openid-configuration\""
    # NOTE: stac-auth-proxy OIDC_DISCOVERY_URL is intentionally NOT overridden —
    # it must stay the in-cluster URL (the proxy fetches JWKS from that origin;
    # an external LB URL hairpins and fails). It is domain-independent.
    echo "  testing:"
    echo "    mockOidcServer:"
    echo "      extraEnv:"                       # list: restate in full
    echo "        - name: ISSUER"
    echo "          value: \"${SCHEME}://mock-oidc.${BASE_DOMAIN}\""
    echo "        - name: SCOPES"
    echo "          value: \"stac:read,stac:write\""
    echo "stac-manager:"
    echo "  publicUrl: \"${SCHEME}://manager.${BASE_DOMAIN}\""
    echo "  stacApi: \"${SCHEME}://stac.${BASE_DOMAIN}\""
    echo "  stacBrowser: \"${SCHEME}://browser.${BASE_DOMAIN}\""
    echo "  oidc:"
    echo "    authority: \"${SCHEME}://mock-oidc.${BASE_DOMAIN}\""
    echo "jupyter:"
    echo "  participants:"
    local name tok
    while read -r name; do
      [[ -n "$name" ]] || continue
      tok="$(existing_token "$name" || true)"; [[ -n "$tok" ]] || tok="$(openssl rand -hex 16)"
      echo "    - { name: ${name}, token: \"${tok}\" }"
    done < <(participant_names)
  } > "$tmp"
  mv "$tmp" "$OVERRIDES"
}

# Optional: let the cluster pull a PRIVATE workshop image. Set GHCR_TOKEN (a
# token with read:packages) + GHCR_USER to create an imagePullSecret and attach
# it to the namespace's default ServiceAccount (which the Labs use). Must run
# BEFORE the Lab pods are created so the secret is injected at creation time.
# Not needed if the GHCR package is public.
setup_pull_secret() {
  if [[ -z "${GHCR_TOKEN:-}" ]]; then
    log "No GHCR_TOKEN set — assuming the workshop image is public (skipping pull secret)"
    return
  fi
  log "Creating GHCR pull secret + attaching it to the default ServiceAccount"
  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$NAMESPACE" create secret docker-registry ghcr-pull \
    --docker-server=ghcr.io --docker-username="${GHCR_USER:-$USER}" --docker-password="$GHCR_TOKEN" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl -n "$NAMESPACE" patch serviceaccount default \
    -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}' >/dev/null
}

deploy_chart() {
  log "Building chart dependencies"
  # Register the dependency repos so `helm dependency build` can resolve them
  # from Chart.lock on a fresh machine (the vendored .tgz are gitignored).
  helm repo add eoapi https://developmentseed.org/eoapi-k8s/ --force-update >/dev/null 2>&1 || true
  helm repo add stac-manager https://stac-manager.ds.io/ --force-update >/dev/null 2>&1 || true
  helm repo update eoapi stac-manager >/dev/null 2>&1 || true
  helm dependency build "$CHART_DIR" >/dev/null
  log "Writing host overrides for ${BASE_DOMAIN} (tokens preserved across re-deploys)"
  write_overrides
  echo "  overrides: ${OVERRIDES}"
  setup_pull_secret          # before helm upgrade, so new Lab pods inherit the secret
  log "Deploying release '${RELEASE}' in namespace '${NAMESPACE}'"
  helm upgrade --install "$RELEASE" "$CHART_DIR" \
    -n "$NAMESPACE" --create-namespace -f "$OVERRIDES" --timeout "$HELM_TIMEOUT"
  log "Waiting for deployments (the database is created asynchronously by PGO)"
  local d
  for d in stac raster vector browser stac-auth-proxy mock-oidc-server stac-manager $(participant_names); do
    kubectl -n "$NAMESPACE" rollout status "deploy/${RELEASE}-${d}" --timeout=300s || true
  done
}

# curl a URL until it returns the expected code (nginx warmup can lag).
_expect() { # <url> <code> -> echoes actual code, returns 0 if matched
  local url="$1" want="$2" code="" _
  for _ in 1 2 3 4 5 6 7 8; do
    code="$(curl -s ${CURL_INSECURE:-} -o /dev/null -w '%{http_code}' --max-time 15 "$url" || true)"
    [[ "$code" == "$want" ]] && break; sleep 3
  done
  printf '%s' "$code"
}

verify() {
  local b="$BASE_DOMAIN" ok=1 code s="$SCHEME"
  # Over https, tolerate a freshly-issued (or staging) cert while it settles.
  [[ "$s" == "https" ]] && export CURL_INSECURE="-k" || export CURL_INSECURE=""
  log "Verifying service subdomains at *.$b (${s})"
  declare -a checks=(
    "${s}://stac.$b/healthz|200|stac"
    "${s}://stac.$b/collections|200|stac collections"
    "${s}://raster.$b/healthz|200|raster"
    "${s}://vector.$b/healthz|200|vector"
    "${s}://browser.$b/|200|browser"
    "${s}://manager.$b/|200|manager"
    "${s}://mock-oidc.$b/.well-known/openid-configuration|200|mock-oidc"
  )
  local c url want name
  for c in "${checks[@]}"; do
    IFS='|' read -r url want name <<<"$c"
    code="$(_expect "$url" "$want")"
    printf '  %-16s %-52s %s\n' "$name" "$url" "$code"
    [[ "$code" == "$want" ]] || ok=0
  done

  log "Verifying auth (expect 401 without a token, non-401 with one)"
  local no_tok token with_tok
  no_tok="$(curl -s ${CURL_INSECURE:-} -o /dev/null -w '%{http_code}' --max-time 15 \
    -X POST "${s}://stac.$b/collections" -H 'Content-Type: application/json' -d '{}' || true)"
  token="$(curl -s ${CURL_INSECURE:-} --max-time 15 "${s}://mock-oidc.$b/" \
    --data-raw 'username=testuser&scopes=openid+stac:read+stac:write' \
    -H 'Accept: application/json' | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
  with_tok="$(curl -s ${CURL_INSECURE:-} -o /dev/null -w '%{http_code}' --max-time 15 \
    -X POST "${s}://stac.$b/collections" -H "Authorization: Bearer ${token}" \
    -H 'Content-Type: application/json' -d '{}' || true)"
  printf '  POST without token: %s   with token: %s\n' "$no_tok" "$with_tok"
  [[ "$no_tok" == "401" && "$with_tok" != "401" && -n "$with_tok" ]] || ok=0

  print_urls
  if [[ "$ok" == 1 ]]; then log "OK — services reachable and auth enforced."; else log "FAILED — see codes above"; exit 1; fi
}

print_urls() {
  log "Participant JupyterLab URLs"
  local name tok
  while read -r name; do
    [[ -n "$name" ]] || continue
    tok="$(existing_token "$name" || true)"
    printf '  %-8s %s://%s.%s/lab?token=%s\n' "$name" "$SCHEME" "$name" "$BASE_DOMAIN" "$tok"
  done < <(participant_names)
  printf '  %-8s %s://manager.%s/\n' "manager" "$SCHEME" "$BASE_DOMAIN"
  printf '  %-8s %s://browser.%s/\n' "browser" "$SCHEME" "$BASE_DOMAIN"
}

teardown() {
  log "Uninstalling release '${RELEASE}'"
  helm uninstall "$RELEASE" -n "$NAMESPACE" 2>/dev/null || true
  kubectl -n "$NAMESPACE" delete pvc --all 2>/dev/null || true
  kubectl delete namespace "$NAMESPACE" --timeout=180s 2>/dev/null || true
  if [[ "${1:-}" == "--all" ]]; then
    # Only remove what deploy.sh owns (PGO + the release above). ingress-nginx
    # and cert-manager are cluster platform owned by Terraform — removing them
    # here would drift TF state. `terraform destroy` tears those (and the whole
    # cluster) down. Standalone (non-TF) users: `helm uninstall ingress-nginx
    # -n ingress-nginx` / `cert-manager -n cert-manager` by hand.
    log "Removing PGO (Postgres operator). ingress-nginx + cert-manager are Terraform-owned — left in place."
    helm uninstall pgo -n postgres-operator 2>/dev/null || true
    kubectl delete namespace postgres-operator --timeout=180s 2>/dev/null || true
  fi
}

case "${1:-deploy}" in
  deploy)   require_tls_config; install_prereqs; deploy_chart; verify ;;
  verify)   verify ;;
  urls)     print_urls ;;
  overrides) write_overrides; echo "written: ${OVERRIDES}"; cat "$OVERRIDES" ;;
  teardown) teardown "${2:-}" ;;
  *) echo "Usage: $0 {deploy|verify|urls|teardown [--all]}" >&2; exit 2 ;;
esac
