# eoapi-workshop Helm chart

A docker-compose-aligned Helm deployment of [eoAPI](https://eoapi.dev) for the
workshop: an *umbrella* chart over the upstream
[`eoapi`](https://github.com/developmentseed/eoapi-k8s) and
[`stac-manager`](https://github.com/developmentseed/stac-manager) charts, plus
per-participant **JupyterLab** environments — no observability/monitoring stack.

Every service is served at the **root of its own subdomain** under a wildcard
domain (`*.<baseDomain>`, default `eoapi-workshop.ds.io`).

## What gets deployed

| Component | Subdomain of `eoapi-workshop.ds.io` | Notes |
|---|---|---|
| STAC API (via stac-auth-proxy) | `stac.` | pgstac + stac-fastapi, fronted by the auth proxy |
| Raster (titiler-pgstac) | `raster.` | |
| Vector (tipg) | `vector.` | starts empty — see [Limitations](#limitations) |
| STAC Browser | `browser.` | root-serving `radiantearth/stac-browser` |
| STAC Manager (editing UI) | `manager.` | `stac-manager` chart 1.0.3 |
| Mock OIDC server | `mock-oidc.` | test-only auth |
| JupyterLab × N | `lab-01.`…`lab-05.` | one isolated pod + PVC + token each |
| Database (pgstac) | in-cluster only | Crunchy `PostgresCluster` |

Disabled (unlike upstream `experimental.yaml`): `multidim`, `docServer`,
`eoapi-notifier`, `knative`, `monitoring.*`, `observability.grafana`, autoscaling.

## Contracts (read first)

- **Wildcard DNS required** — `*.<baseDomain>` must A-record to the ingress
  LoadBalancer IP (check: `dig +short stac.eoapi-workshop.ds.io`).
- **Release name and namespace must both be `eoapi`** — the proxy's in-cluster
  OIDC URL (`eoapi-mock-oidc-server.eoapi.svc…`) is derived from them. `deploy.sh`
  defaults to this.
- **Test-only auth, http by default** — the mock OIDC ships `test-client` /
  `test-secret` and reads are public (`DEFAULT_PUBLIC=true`). STAC Manager (and
  Browser) *login/editing* needs a secure context, so enable `routing.tls` for
  HTTPS; over http the UIs are browse/read-only. Not for production.

## Prerequisites

Kubernetes 1.23+ with an **NGINX ingress controller**, the **Crunchy Postgres
Operator (PGO)** (hard requirement — `postgrescluster` only reconciles if PGO/CRDs
are installed), Helm 3.8+, and the wildcard DNS above. `deploy.sh` installs the
two operators for you (unless `SKIP_PREREQS=1`).

## Deploy

`deploy.sh` installs prerequisites, generates host overrides (per-subdomain URLs +
a stable per-participant token), installs the release, waits for rollouts, and
verifies end-to-end. Idempotent — tokens/URLs stay stable across re-runs.

```bash
cd infrastructure/charts/eoapi-workshop
./deploy.sh deploy              # prerequisites + chart + verify
./deploy.sh verify              # re-run endpoint/auth checks, print Lab URLs
./deploy.sh urls                # print participant Lab URLs (+ tokens)
./deploy.sh teardown [--all]    # remove release (--all also removes operators)
```

Env vars: `BASE_DOMAIN` (default `eoapi-workshop.ds.io`), `SKIP_PREREQS=1`,
`GHCR_USER`+`GHCR_TOKEN` (pull secret for a private image — see
[Participant JupyterLabs](#participant-jupyterlabs)). `RELEASE`/`NAMESPACE` must
stay `eoapi`.

The pgstac DB is created asynchronously by PGO and seeded with sample STAC data,
so API pods may restart a few times before `Ready` on first install.

To install without `deploy.sh`: `helm dependency update`, then `helm install eoapi
. -n eoapi --create-namespace` with a `-f` overrides file (generate one for a
non-default domain via `BASE_DOMAIN=… ./deploy.sh overrides`).

## Routing

All routing is one Ingress (`templates/subdomain-ingress.yaml`): a host rule per
service, each serving at `/` with no rewrite. The upstream path-based ingress is
off and each app serves at its subdomain root — stac/raster/vector with
`--root-path=`, proxy `ROOT_PATH=""`, browser via the root-serving
`radiantearth/stac-browser`, Labs without `--ServerApp.base_url`. Per-subdomain
URLs default to the workshop domain in `values.yaml`; `deploy.sh` rewrites them for
another `BASE_DOMAIN` via the gitignored `.deploy/overrides.yaml`.

## Verify

`./deploy.sh verify` checks every service subdomain, runs the auth test, and prints
the Lab URLs. Manually:

```bash
kubectl -n eoapi get pods
curl -s http://stac.eoapi-workshop.ds.io/healthz        # also raster. / vector.
curl -s http://stac.eoapi-workshop.ds.io/collections    # sample items
# UIs: browser.  manager.  mock-oidc./.well-known/openid-configuration
```

## Participant JupyterLabs

`jupyter.participants` (default `lab-01`…`lab-05`; edit for any N) → one Deployment
+ Service + PVC each at `<name>.<baseDomain>`, running the GHCR image
`ghcr.io/developmentseed/eoapi-workshop` (built by
`.github/workflows/publish-workshop-image.yml`). Each Lab gets the eoAPI endpoints
+ DB creds injected (from the `eoapi-pguser-eoapi` PGO secret) and an access token
(`./deploy.sh urls` prints them).

- **Persistence:** notebooks come fresh from the image (`/home/jovyan/docs`) on
  every start, so updates always appear; only `/home/jovyan/work` persists (save
  work there — edits to the provided notebooks reset on restart).
- **Private image:** GHCR packages are private by default. Either make the package
  public, or pass a pull token — `GHCR_USER=<u> GHCR_TOKEN=<read:packages token>
  ./deploy.sh deploy` creates the `ghcr-pull` secret and wires it to the default
  ServiceAccount before the Labs start.

## Testing auth

`stac-auth-proxy` fronts STAC at `stac.<baseDomain>`: **GET is public, mutations
need a bearer token** from the mock OIDC server (`jq` required).

```bash
b=eoapi-workshop.ds.io
curl -s -o/dev/null -w '%{http_code}\n' http://stac.$b/collections             # 200 (public read)
curl -s -o/dev/null -w '%{http_code}\n' -X POST http://stac.$b/collections \
  -H 'Content-Type: application/json' -d '{}'                                   # 401 (no token)
TOKEN=$(curl -s http://mock-oidc.$b/ \
  --data-raw 'username=testuser&scopes=openid+stac:read+stac:write' \
  -H 'Accept: application/json' | jq -r .token)
curl -s -o/dev/null -w '%{http_code}\n' -X POST http://stac.$b/collections \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'  # NOT 401
```

**401 without a token, non-401 with one** = working. If it stays 401, check
`kubectl -n eoapi logs deploy/eoapi-stac-auth-proxy` (usual cause: release/namespace
not `eoapi`).

## Upgrade / uninstall

```bash
./deploy.sh deploy                    # idempotent re-deploy (tokens preserved)
helm uninstall eoapi -n eoapi         # or ./deploy.sh teardown
kubectl -n eoapi delete pvc --all     # PVCs (DB + Lab work) are retained by design
```

## Limitations

- **`/vector` starts empty** — `pgstacBootstrap.loadSamples` loads STAC items, not
  the compose `features-loader` vector layer, so the `05-tipg` notebook needs it
  loaded separately (an `ogr2ogr` Job — follow-up).
- **UI login needs TLS** — STAC Manager / Browser OIDC login uses PKCE (needs
  HTTPS); over http they're read-only. Enable `routing.tls`. (Browser's
  `redirect_uri` also still derives from the apex host upstream.)
- **Capacity** — N always-on Labs at `limit 2 CPU / 4Gi` (default 5 ≈ ≤10 CPU /
  20Gi) + stac-manager's ~4Gi startup build + the backend. Size nodes to N.
- **Not production** — test auth, single 1-replica DB (5Gi), http. For production
  use the CDK/AWS stack in [`DEPLOYMENT.md`](../../../DEPLOYMENT.md).
