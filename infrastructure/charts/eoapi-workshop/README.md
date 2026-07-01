# eoapi-workshop Helm chart

A **docker-compose-aligned** Helm deployment of [eoAPI](https://eoapi.dev) for the
workshop. It is an *umbrella* chart over the upstream
[`eoapi`](https://github.com/developmentseed/eoapi-k8s) chart plus the published
[`stac-manager`](https://github.com/developmentseed/stac-manager) chart, and adds
per-participant **JupyterLab** environments — **no observability/monitoring stack**.

Every service is exposed at the **root of its own subdomain** under a wildcard
domain (`*.<baseDomain>`, default `eoapi-workshop.ds.io`).

## What gets deployed

| Component | Subdomain (default) | Notes |
|---|---|---|
| STAC API (via stac-auth-proxy) | `stac.eoapi-workshop.ds.io` | pgstac + stac-fastapi, fronted by the auth proxy |
| Raster (titiler-pgstac) | `raster.eoapi-workshop.ds.io` | |
| Vector (tipg) | `vector.eoapi-workshop.ds.io` | starts empty — see [Known limitations](#known-limitations) |
| STAC Browser | `browser.eoapi-workshop.ds.io` | root-serving `radiantearth/stac-browser` |
| STAC Manager (editing UI) | `manager.eoapi-workshop.ds.io` | `stac-manager` chart 1.0.3 |
| Mock OIDC server | `mock-oidc.eoapi-workshop.ds.io` | **test-only** auth |
| JupyterLab × N | `lab-01.…lab-05.eoapi-workshop.ds.io` | one isolated pod + PVC + token each |
| Database (pgstac) | — (in-cluster only) | Crunchy `PostgresCluster` |

**Disabled** (unlike upstream `experimental.yaml`): `multidim`, `docServer`,
`eoapi-notifier`, `knative`, `monitoring.*`, `observability.grafana`, autoscaling.

## ⚠️ Read first

**1. Wildcard DNS is required.** A record `*.<baseDomain>` must point at the
ingress LoadBalancer IP. Verify:
```bash
dig +short stac.eoapi-workshop.ds.io      # → your ingress LB IP
```

**2. Release name + namespace must both be `eoapi`.** The proxy's
`OIDC_DISCOVERY_INTERNAL_URL` is pinned to the in-cluster Service DNS
`eoapi-mock-oidc-server.eoapi.svc.cluster.local`, which is derived from the Helm
release name and namespace. Deploy as `eoapi`/`eoapi` (the `deploy.sh` default).

**3. Test-only auth.** The mock OIDC server ships hard-coded `test-client` /
`test-secret`, and reads are public (`DEFAULT_PUBLIC=true`) so notebooks work
without tokens. **Not for production.**

**4. HTTP by default → STAC Manager *editing* needs TLS.** STAC Manager login
uses OIDC/PKCE, which browsers only allow in a **secure context** (HTTPS). Over
plain `http` the UI loads and browses read-only; enable `routing.tls` (a wildcard
cert / cert-manager) for authenticated editing.

## Prerequisites

A Kubernetes cluster (1.23+) with:

1. **Wildcard DNS** `*.<baseDomain>` → the ingress LB IP (see above).
2. **NGINX ingress controller** (`ingressClassName: nginx`).
3. **Crunchy Postgres Operator (PGO)** — *hard requirement*; the `postgrescluster`
   resource only reconciles into a running DB if the operator/CRDs are installed.
4. **Helm 3.8+** (Helm 4 works).

`deploy.sh` installs #2 and #3 for you (unless `SKIP_PREREQS=1`).

## Deploy

### Recommended: `deploy.sh`

Installs prerequisites, generates host overrides (per-subdomain URLs + a stable
per-participant token), installs the release, waits for rollouts, and verifies
end to end. Idempotent — participant tokens/URLs stay stable across re-runs.

```bash
cd infrastructure/charts/eoapi-workshop

./deploy.sh deploy                 # prerequisites + chart + verify
./deploy.sh verify                 # re-run endpoint/auth checks + print Lab URLs
./deploy.sh urls                   # just print the participant Lab URLs (+ tokens)
./deploy.sh overrides              # (re)generate + print .deploy/overrides.yaml only
./deploy.sh teardown [--all]       # remove the release (--all also removes operators)
```

Environment:
```bash
BASE_DOMAIN=eoapi-workshop.ds.io   # wildcard base domain (default)
SKIP_PREREQS=1                     # operators already installed
# RELEASE / NAMESPACE must stay "eoapi" (see contract above)
```

The pgstac DB is created asynchronously by PGO and `pgstacBootstrap` seeds sample
STAC data, so API pods may restart a few times before `Ready` on first install.

### Manual

```bash
helm dependency update ./infrastructure/charts/eoapi-workshop   # first time (writes Chart.lock)
helm lint  ./infrastructure/charts/eoapi-workshop
helm template eoapi ./infrastructure/charts/eoapi-workshop -n eoapi | less
# For a domain other than the default, generate overrides first:
BASE_DOMAIN=my.domain.io ./infrastructure/charts/eoapi-workshop/deploy.sh overrides
helm install eoapi ./infrastructure/charts/eoapi-workshop -n eoapi --create-namespace \
  -f ./infrastructure/charts/eoapi-workshop/.deploy/overrides.yaml
```

## Routing model

All routing lives in **`templates/subdomain-ingress.yaml`**: one NGINX `Ingress`
with a host rule per service, each serving at path `/` with **no rewrite**. The
upstream eoapi path-based ingress is disabled (`eoapi.ingress.enabled=false`), and
each app is configured to serve at its subdomain root:

- stac/raster/vector: `ingress.path=""` → uvicorn `--root-path=` (empty);
- stac-auth-proxy: `ROOT_PATH=""`, health at `/healthz`;
- browser: root-serving `radiantearth/stac-browser` (the upstream custom image
  bakes a `/browser` prefix that breaks at a subdomain root), `catalogUrl` → the
  stac subdomain;
- JupyterLabs: no `--ServerApp.base_url` (served at `lab-NN.<baseDomain>` root).

The base domain and all per-subdomain URLs default to `eoapi-workshop.ds.io` in
`values.yaml`; `deploy.sh` rewrites them for a different `BASE_DOMAIN` via the
gitignored `.deploy/overrides.yaml` (never committed).

## Verify

```bash
kubectl -n eoapi get pods

curl -s http://stac.eoapi-workshop.ds.io/healthz       # STAC API (via auth proxy)
curl -s http://raster.eoapi-workshop.ds.io/healthz     # Raster
curl -s http://vector.eoapi-workshop.ds.io/healthz     # Vector
curl -s http://stac.eoapi-workshop.ds.io/collections   # sample collections
# UIs:
#   http://browser.eoapi-workshop.ds.io/
#   http://manager.eoapi-workshop.ds.io/
#   http://mock-oidc.eoapi-workshop.ds.io/.well-known/openid-configuration
```

`./deploy.sh verify` runs all of the above plus the auth check and prints the
participant Lab URLs.

## Participant JupyterLabs

`jupyter.participants` (default `lab-01`…`lab-05`) → one Deployment + Service +
RWO PVC each, at `<name>.<baseDomain>`. Each pod runs the GHCR workshop image
(`ghcr.io/developmentseed/eoapi-workshop`, published by
`.github/workflows/publish-workshop-image.yml`), gets the eoAPI endpoints + DB
creds injected (from the `eoapi-pguser-eoapi` PGO secret, direct-primary keys),
and a per-participant access token. Home dirs persist (a seed initContainer copies
the baked notebooks into the PVC once, so the volume doesn't shadow them).

```bash
./deploy.sh urls
#   lab-01   http://lab-01.eoapi-workshop.ds.io/lab?token=<token>
#   …
```

Change the headcount by editing the `jupyter.participants` list (any N).

## Testing the auth mechanism

`stac-auth-proxy` fronts STAC at `stac.<baseDomain>`. `DEFAULT_PUBLIC=true` →
**GET is open, mutations require a bearer token**. Tokens come from the mock OIDC
server (`iss` = its `ISSUER` = `http://mock-oidc.<baseDomain>`). The proxy fetches
JWKS in-cluster via `OIDC_DISCOVERY_INTERNAL_URL` (pods can't resolve the external
host). Needs `jq`.

```bash
b=eoapi-workshop.ds.io

# 1. discovery reachable
curl -s http://mock-oidc.$b/.well-known/openid-configuration | jq .issuer   # "http://mock-oidc.eoapi-workshop.ds.io"

# 2. public read works without a token
curl -s -o /dev/null -w '%{http_code}\n' http://stac.$b/collections          # 200

# 3. protected write rejected without a token
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://stac.$b/collections \
  -H 'Content-Type: application/json' -d '{}'                                 # 401

# 4. mint a token (stac:write scope)
TOKEN=$(curl -s http://mock-oidc.$b/ \
  --data-raw 'username=testuser&scopes=openid+stac:read+stac:write' \
  -H 'Accept: application/json' | jq -r .token)

# 5. same write now passes the auth gate
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://stac.$b/collections \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'  # NOT 401
```

Key signal: **401 without a token, non-401 with one**. If step 5 stays 401, check
`kubectl -n eoapi logs deploy/eoapi-stac-auth-proxy` — the usual cause is a
release/namespace other than `eoapi` (breaks `OIDC_DISCOVERY_INTERNAL_URL`).

## Upgrade / uninstall

```bash
./deploy.sh deploy                              # idempotent re-deploy (tokens preserved)
helm uninstall eoapi -n eoapi                   # or ./deploy.sh teardown
kubectl -n eoapi delete pvc --all               # PVCs (DB + Lab homes) are retained by design
```

## Known limitations

- **`/vector` starts empty.** The compose `features-loader` seeds a `features`
  schema for tipg; this chart's `pgstacBootstrap.loadSamples` loads STAC *items*
  only, not that vector layer. The `05-tipg` notebook has no data until it's
  loaded separately (an `ogr2ogr` Job — possible follow-up).
- **STAC Manager editing needs TLS.** OIDC/PKCE requires a secure context; over
  http the UI is read-only. Enable `routing.tls`.
- **Browser OIDC login** — the browser's OIDC `redirect_uri` still derives from
  the apex host in the upstream template; browsing works, browser-side login is a
  follow-up (and also needs TLS).
- **Capacity.** N always-on Labs at `limit 2 CPU / 4Gi` each (default 5 ≈ up to
  10 CPU / 20Gi), plus stac-manager's startup build (~4Gi) and the eoAPI backend.
  Size nodes accordingly.
- **Not production-ready.** Test-only auth, single 1-replica DB (5Gi), http.
  For production use the CDK/AWS stack in [`DEPLOYMENT.md`](../../../DEPLOYMENT.md).
