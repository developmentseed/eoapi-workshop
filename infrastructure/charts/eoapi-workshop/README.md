# eoapi-workshop Helm chart

A **minimal, docker-compose-aligned** Helm deployment of [eoAPI](https://eoapi.dev)
for the workshop. It is a thin *umbrella* chart that depends on the upstream
[`eoapi`](https://github.com/developmentseed/eoapi-k8s) chart and ships a trimmed
`values.yaml` enabling only the components the workshop's `docker-compose.yml`
runs — **no observability/monitoring stack**.

## What gets deployed

| docker-compose service | This chart |
|---|---|
| database (pgstac) | ✅ `postgrescluster` |
| stac-fastapi | ✅ `stac` → `/stac` |
| titiler-pgstac | ✅ `raster` → `/raster` |
| tipg | ✅ `vector` → `/vector` |
| stac-browser | ✅ `browser` |
| stac-auth-proxy | ✅ `stac-auth-proxy` (fronts `/stac`) |
| mock-oidc | ✅ `testing.mockOidcServer` → `/mock-oidc` |
| features-loader | ⚠️ no equivalent — see [Known limitations](#known-limitations) |
| jupyterhub | ➖ out of scope (notebook env, not an eoAPI service) |

**Disabled** (unlike upstream `experimental.yaml`): `multidim`, `docServer`,
`eoapi-notifier`, `knative`, `monitoring.*` (metrics-server / Prometheus /
adapter), `observability.grafana`, and autoscaling (fixed 1 replica per service).

## ⚠️ Release-name contract — read this first

The chart wires `stac-auth-proxy` to the mock OIDC server using the **internal
Service DNS name** `eoapi-mock-oidc-server.eoapi.svc.cluster.local`. That name is
derived from the Helm **release name** and **namespace**, so you **must** install
with release name `eoapi` in namespace `eoapi`:

```bash
helm install eoapi ./charts/eoapi-workshop -n eoapi --create-namespace
```

Any other release name or namespace breaks the proxy's OIDC discovery. If you
need a different name/namespace, also update `eoapi.stac-auth-proxy.env.OIDC_DISCOVERY_URL`
in `values.yaml` accordingly.

## ⚠️ Test-only auth

`stac-auth-proxy` is fronted by a **mock OIDC server** with hard-coded
`test-client` / `test-secret` credentials, and reads are left public
(`DEFAULT_PUBLIC=true`) so the notebooks work without tokens. **This is for the
workshop only — do not use it in production.**

## Prerequisites

A Kubernetes cluster (1.23+) with:

1. **An NGINX ingress controller** (`ingressClassName: nginx`). For example:
   ```bash
   helm upgrade --install ingress-nginx ingress-nginx \
     --repo https://kubernetes.github.io/ingress-nginx \
     --namespace ingress-nginx --create-namespace
   ```
2. **The Crunchy Postgres Operator (PGO)** — **hard requirement**. The
   `postgrescluster` component renders a `PostgresCluster` custom resource that
   only reconciles into a running database if the operator (and its CRDs) are
   already installed. Without it the chart installs but the database never comes
   up. Install it once per cluster, e.g.:
   ```bash
   helm upgrade --install pgo oci://registry.developers.crunchydata.com/crunchydata/pgo \
     --namespace postgres-operator --create-namespace
   ```
3. **Helm 3.8+** (Helm 4 works). Tested with Helm v4.

Local clusters (kind / minikube / k3s) are fine as long as the two operators
above are installed and the ingress is reachable on `localhost`.

## Deploy

### Recommended: `deploy.sh` (handles prerequisites + host + verify)

For most clusters — especially remote ones — use the bundled script. It installs
the prerequisites, **discovers the ingress host automatically**, generates the
host overrides, installs the release, and verifies it end to end. It is
idempotent (safe to re-run) and reproducible (re-creates everything on a fresh
cluster):

```bash
cd infrastructure/charts/eoapi-workshop

./deploy.sh deploy        # prerequisites + chart + verify
./deploy.sh verify        # re-run the endpoint/auth checks
./deploy.sh teardown      # remove the release (add --all to also remove operators)
```

The host is resolved in this order: `INGRESS_HOST` env var → the ingress
LoadBalancer IP as `<IP>.nip.io` → a LoadBalancer hostname. Pin it explicitly for
a custom domain or a local cluster:

```bash
INGRESS_HOST=eoapi.example.com ./deploy.sh deploy   # custom DNS
INGRESS_HOST=localhost ./deploy.sh deploy           # kind/minikube/k3s
SKIP_PREREQS=1 ./deploy.sh deploy                    # operators already installed
```

### Manual

```bash
# From the repo root.

# 1. Fetch the upstream `eoapi` chart dependency (writes Chart.lock + charts/*.tgz).
#    Use `update` the first time (no lock yet); `build` on later runs to honor the lock.
helm dependency update ./charts/eoapi-workshop

# 2. (optional) Sanity-check the rendered manifests without a cluster.
helm lint ./charts/eoapi-workshop
helm template eoapi ./charts/eoapi-workshop -n eoapi | less

# 3. Install — release name and namespace MUST be `eoapi` (see contract above).
#    On a remote cluster, also pass the host overrides (see "Remote clusters").
helm install eoapi ./charts/eoapi-workshop -n eoapi --create-namespace

# 4. Watch the rollout.
kubectl -n eoapi get pods -w
```

The pgstac database is created asynchronously by the operator and the
`pgstacBootstrap` job seeds sample STAC data, so the API pods may restart a few
times before they become `Ready` — this is expected on first install.

### Remote clusters (non-`localhost` host)

The default `values.yaml` is pinned to `localhost` (the docker-compose workflow).
On a remote cluster the NGINX ingress is exposed via a LoadBalancer with its own
IP/hostname, so the ingress host **and** the externally-reachable auth URLs must
point at that host instead. Kubernetes `Ingress` rejects a bare IP as a host, so
use a DNS name — [`nip.io`](https://nip.io) wildcard DNS (`<LB-IP>.nip.io`) works
out of the box.

Keep `values.yaml` environment-agnostic — pass the host in a **separate overrides
file** (`-f`) rather than editing the chart. An overrides file is more robust than
`--set` here because `mockOidcServer.extraEnv` is a YAML *list*: `--set` on a
single list index silently replaces the whole element (dropping `ISSUER`/`SCOPES`),
and the comma in `stac:read,stac:write` trips `--set` parsing. (`stac-auth-proxy.env`
is a *map* and deep-merges fine.) The **internal** OIDC URL stays in-cluster and is
left untouched.

```bash
# Discover the LoadBalancer IP the ingress controller was assigned.
INGRESS_HOST="$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}').nip.io"

# Generate an overrides file for this host (kept out of the chart).
cat > eoapi-remote.yaml <<EOF
eoapi:
  ingress:
    host: "${INGRESS_HOST}"
  stac-auth-proxy:
    env:
      OIDC_DISCOVERY_URL: "http://${INGRESS_HOST}/mock-oidc/.well-known/openid-configuration"
  browser:
    oidcDiscoveryUrl: "http://${INGRESS_HOST}/mock-oidc/.well-known/openid-configuration"
  testing:
    mockOidcServer:
      extraEnv:
        - name: ISSUER
          value: "http://${INGRESS_HOST}/mock-oidc"
        - name: SCOPES
          value: "stac:read,stac:write"
EOF

helm install eoapi ./charts/eoapi-workshop -n eoapi --create-namespace -f eoapi-remote.yaml
```

Then substitute `$INGRESS_HOST` for `localhost` in all the `curl` commands below.

### Ingress routing (why two Ingress objects)

The upstream eoapi ingress exposes every service through a single NGINX `Ingress`
with a cluster-wide `nginx.ingress.kubernetes.io/rewrite-target: /$2` annotation.
That correctly strips the prefix for services that serve at root (`raster`,
`vector`), but it **breaks** two services that must keep their prefix:

- `stac-auth-proxy` runs with `ROOT_PATH=/stac` and serves under `/stac`.
- the custom `stac-browser` image is built with the `/browser` pathPrefix baked
  in and only serves under `/browser/`.

A single ingress-wide rewrite can't satisfy both, so this chart sets
`eoapi.stac.ingress.enabled=false` and `eoapi.browser.ingress.enabled=false`
(removing their broken, rewritten paths from the upstream ingress) and ships a
**second, dedicated passthrough `Ingress`** — `templates/passthrough-ingress.yaml`
— that routes `/stac` and `/browser` with no rewrite. It also sets the required
`stac-auth-proxy.env.UPSTREAM_URL=http://eoapi-stac:8080` (the upstream chart
leaves it at the image default `http://localhost:8080`, which can't reach the
separate STAC Service in-cluster).

## Verify

```bash
# All pods Ready?
kubectl -n eoapi get pods

# Endpoints (through the NGINX ingress on localhost):
curl -s http://localhost/stac/healthz         # STAC API (via auth proxy)
curl -s http://localhost/raster/healthz       # Raster (titiler)
curl -s http://localhost/vector/healthz       # Vector (tipg)
curl -s http://localhost/stac/collections     # sample collections loaded by pgstacBootstrap
# STAC Browser + mock OIDC are served at:
#   http://localhost/browser/ (browser — note the /browser prefix)
#   http://localhost/mock-oidc/.well-known/openid-configuration
```

If `localhost` is not where your ingress is exposed (e.g. minikube), use
`kubectl -n eoapi port-forward svc/<ingress-controller> 8080:80` or the cluster's
ingress IP/hostname instead.

## Testing the auth mechanism

`stac-auth-proxy` fronts `/stac`. With `DEFAULT_PUBLIC=true`, **reads (GET) are
open** and **mutations (POST/PUT/DELETE) require a bearer token**. Tokens come
from the bundled **mock OIDC server**. The commands below assume the ingress is
reachable on `http://localhost` (adjust the host otherwise) and that `jq` is
installed.

How it's wired (mirrors `docker-compose.yml`):

- The mock server issues tokens whose `iss` is its `ISSUER`, `http://localhost/mock-oidc`.
- The proxy advertises that same external URL via `OIDC_DISCOVERY_URL`, but
  fetches the OIDC config + JWKS in-cluster via `OIDC_DISCOVERY_INTERNAL_URL`
  (`http://eoapi-mock-oidc-server.eoapi.svc.cluster.local:8080/...`), because a
  pod cannot resolve the `localhost` ingress host.

### 1. Discovery endpoint is reachable

```bash
curl -s http://localhost/mock-oidc/.well-known/openid-configuration | jq .issuer
# expect: "http://localhost/mock-oidc"
```

### 2. Public reads work *without* a token

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/stac/collections
# expect: 200
```

### 3. A protected (write) request is *rejected without* a token

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost/stac/collections \
  -H 'Content-Type: application/json' -d '{}'
# expect: 401 (blocked by the proxy before reaching STAC)
```

### 4. Mint a token from the mock OIDC server

The server mints a signed JWT via a POST to its root endpoint. Request the
`stac:write` scope (enabled via the `SCOPES` env var on the server):

```bash
TOKEN=$(curl -s http://localhost/mock-oidc/ \
  --data-raw 'username=testuser&scopes=openid+stac:read+stac:write' \
  -H 'Accept: application/json' | jq -r .token)

# Inspect the decoded claims (the server also returns them as token_body):
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq .
```

### 5. The same request now passes the auth gate *with* the token

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost/stac/collections \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{}'
# expect: NOT 401 — the proxy forwards the request upstream. (You'll get a 4xx
# such as 400/422 from STAC for the empty body; send a valid Collection to get 201.)
```

The key signal is step 3 vs step 5: **401 without a token, non-401 with one**.
That proves the proxy is enforcing auth and validating tokens against the mock
OIDC server's keys.

> **Note:** these steps are validated against the rendered chart config and
> mirror the proven `docker-compose` auth setup; run them against your live
> cluster after deploy to confirm end-to-end. If step 5 still returns 401,
> check the proxy logs (`kubectl -n eoapi logs deploy/eoapi-stac-auth-proxy`) —
> the most common cause is a release name/namespace other than `eoapi`, which
> breaks `OIDC_DISCOVERY_INTERNAL_URL`.

## Upgrade / uninstall

```bash
helm dependency update ./charts/eoapi-workshop   # if the dependency version changed
helm upgrade eoapi ./charts/eoapi-workshop -n eoapi

helm uninstall eoapi -n eoapi
# PersistentVolumeClaims (Postgres data) are retained by design — delete manually if desired:
kubectl -n eoapi delete pvc --all
```

## Configuration

All upstream `eoapi` values are configurable under the top-level `eoapi:` key
(this chart is an umbrella, so the subchart's values are nested). See
[`values.yaml`](./values.yaml) for the trimmed set and the upstream
[chart values](https://github.com/developmentseed/eoapi-k8s/blob/main/charts/eoapi/values.yaml)
for everything available. To override:

```bash
helm install eoapi ./charts/eoapi-workshop -n eoapi --create-namespace \
  --set eoapi.postgrescluster.instances[0].dataVolumeClaimSpec.resources.requests.storage=10Gi
```

## Known limitations

- **`/vector` starts empty.** The docker-compose `features-loader` loads the
  NA CEC Level III Ecoregions shapefile into a `features` schema that tipg
  serves. This chart enables `pgstacBootstrap.loadSamples`, which loads STAC
  sample *items* (for `/stac` and `/raster`) but **not** that vector layer. The
  `05-tipg` notebook will have no data until the layer is loaded separately
  (e.g. an `ogr2ogr` Job against the cluster database — a possible follow-up).
- **Not production-ready.** Test-only auth (mock OIDC), single 1-replica
  database with 5Gi storage, no TLS, no monitoring. This mirrors the local
  docker-compose workflow, not the CDK/AWS production stack documented in
  [`DEPLOYMENT.md`](../../DEPLOYMENT.md).
