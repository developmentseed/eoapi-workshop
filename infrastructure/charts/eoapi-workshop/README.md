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
| STAC API (via stac-auth-proxy) | `stac.` | pgstac + stac-fastapi, fronted by the auth proxy (write scope + row-level filter, as docker-compose) |
| Raster (titiler-pgstac) | `raster.` | |
| Vector (tipg) | `vector.` | serves `features.ecoregions` (loaded by the features-loader Job) |
| STAC Browser | `browser.` | root-serving `radiantearth/stac-browser` |
| STAC Manager (editing UI) | `manager.` | `stac-manager` chart 1.0.3 |
| Mock OIDC server | `mock-oidc.` | test-only auth |
| JupyterLab × `jupyter.count` | `lab-01.`…`lab-NN.` | one isolated pod + PVC + token each |
| Database (pgstac) | in-cluster only | Crunchy `PostgresCluster` |

Disabled (unlike upstream `experimental.yaml`): `multidim`, `docServer`,
`eoapi-notifier`, `knative`, `monitoring.*`, `observability.grafana`, autoscaling.

## Contracts (read first)

- **Wildcard DNS required** — `*.<baseDomain>` must A-record to the ingress
  LoadBalancer IP (check: `dig +short stac.eoapi-workshop.ds.io`).
- **Release name must be `eoapi`** — the proxy's in-cluster OIDC URL
  (`eoapi-mock-oidc-server`) and other Service names are derived from it. Any
  namespace works (`NAMESPACE=…`; examples below use the default `eoapi`).
- **Test-only auth, http by default** — the mock OIDC ships `test-client` /
  `test-secret` and reads are public (`DEFAULT_PUBLIC=true`). STAC Manager (and
  Browser) *login/editing* needs a secure context, so serve over HTTPS (see
  below); over http the UIs are browse/read-only. Not for production.

## HTTPS / TLS

Run `deploy.sh` with `TLS=1 TLS_EMAIL=<you@your-org.org>` (a **real** address —
Let's Encrypt rejects `example.com`) to serve everything over
HTTPS. That renders a Let's Encrypt **ClusterIssuer**
(`templates/cluster-issuer.yaml`, HTTP-01 via ingress-nginx), annotates the
subdomain ingress with `cert-manager.io/cluster-issuer`, and switches every
browser-facing URL to `https://` — cert-manager issues one multi-SAN cert (all
service subdomains) into `routing.tls.secretName`. HTTP-01 needs no cloud
credentials; each subdomain is validated over port 80.

**cert-manager** is normally installed by Terraform (cluster platform — see
`infrastructure/terraform`). If it's absent, `deploy.sh` installs it for you;
either way `deploy.sh teardown` leaves it (and ingress-nginx) in place.

**Existing ClusterIssuer** — if the cluster already has a ClusterIssuer named
`CLUSTER_ISSUER` (default `letsencrypt`), e.g. on a shared cluster, `deploy.sh`
reuses it and renders none, so `TLS_EMAIL` isn't needed: `TLS=1 ./deploy.sh
deploy`. The chart never owns a shared issuer, so teardown can't delete it.

```bash
TLS=1 TLS_EMAIL=you@your-org.org ./deploy.sh deploy
# rate-limited while iterating? use LE staging (untrusted certs):
TLS=1 TLS_EMAIL=you@your-org.org \
  ACME_SERVER=https://acme-staging-v02.api.letsencrypt.org/directory ./deploy.sh deploy
```

First issuance takes ~1–2 min after the release installs; until the cert is
`Ready`, https serves nginx's default cert. Check with
`kubectl -n eoapi get certificate,certificaterequest,order`. The relevant
`routing.tls.*` values (`clusterIssuer`, `email`, `acmeServer`, `secretName`)
are documented in `values.yaml`; `deploy.sh` sets them from the env vars above.

## Prerequisites

Kubernetes 1.23+ with an **NGINX ingress controller**, the **Crunchy Postgres
Operator (PGO)** (hard requirement — `postgrescluster` only reconciles if PGO/CRDs
are installed), Helm 3.8+, and the wildcard DNS above. `deploy.sh` installs
what's missing (unless `SKIP_PREREQS=1`): it leaves an existing `nginx`
ingressclass and cert-manager alone, and installs/upgrades PGO in
`postgres-operator` — a cluster-wide operator, so mind other tenants on a
shared cluster.

## Deploy

`deploy.sh` installs prerequisites, generates host overrides (per-subdomain URLs +
a stable per-participant token), installs the release, waits for rollouts, and
verifies end-to-end. Idempotent — tokens/URLs stay stable across re-runs.

```bash
cd infrastructure/charts/eoapi-workshop
./deploy.sh deploy              # prerequisites + chart + verify
./deploy.sh verify              # re-run endpoint/auth checks, print Lab URLs
./deploy.sh urls                # print participant Lab URLs (+ tokens)
./deploy.sh teardown [--all]    # remove release, PVCs, namespace (--all also removes PGO)
```

Pass the same `NAMESPACE` / `TLS` to every command (`verify`, `urls`,
`teardown`), e.g. `NAMESPACE=eoapi-workshop TLS=1 ./deploy.sh urls`.

Env vars: `BASE_DOMAIN` (default `eoapi-workshop.ds.io`), `SKIP_PREREQS=1`,
`GHCR_USER`+`GHCR_TOKEN` (pull secret for a private image — see
[Participant JupyterLabs](#participant-jupyterlabs)). `RELEASE` must stay `eoapi`;
`NAMESPACE` (default `eoapi`) is free.

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

A Lab is one participant's own JupyterLab at its own URL — same notebooks in
each, separate kernels and storage, one shared eoAPI backend.
`jupyter.count` (default 5 → `lab-01`…`lab-05`) → one Deployment + Service +
PVC each at `lab-NN.<baseDomain>`, running the GHCR image
`ghcr.io/developmentseed/eoapi-workshop` (built by
`.github/workflows/publish-workshop-image.yml` on pushes to `main`). Each Lab gets
the eoAPI endpoints + DB creds injected (from the `eoapi-pguser-eoapi` PGO secret)
and an access token (`./deploy.sh urls` prints them).

- **Changing the count:** edit `jupyter.count` in `values.yaml` and re-run
  `./deploy.sh deploy` (not `--set`: `deploy.sh` reads the Lab names from the
  chart). Existing Labs keep their tokens — kept as a `jupyter.tokens` map in
  `.deploy/overrides.yaml` — new ones get fresh tokens. Delete that file for all
  new tokens.
- **Placement:** `jupyter.nodeSelector` pins the Labs to a node pool, e.g.
  `{ nodepool: workshop }` for the pool in
  [`infrastructure/terraform`](../../terraform/README.md#workshop-node-pool).
  Empty (default) = any node.

- **Persistence:** notebooks come fresh from the image (`/home/jovyan/docs`) on
  every start, so updates always appear; only `/home/jovyan/work` persists (save
  work there — edits to the provided notebooks reset on restart).
- **Private image:** GHCR packages are private by default. Either make the package
  public, or pass a pull token — `GHCR_USER=<u> GHCR_TOKEN=<read:packages token>
  ./deploy.sh deploy` creates the `ghcr-pull` secret and wires it to the default
  ServiceAccount before the Labs start.

## Testing auth

`stac-auth-proxy` fronts STAC at `stac.<baseDomain>`, configured as in
`docker-compose.yml`: **GET is public; mutations need a bearer token carrying the
`stac:write` scope** (`PRIVATE_ENDPOINTS`) from the mock OIDC server. Row-level
filtering (notebook 07) hides `private-<owner>-*` collections from everyone but
the token whose `owner` claim matches; the filter is `docs/workshop_filters.py`,
mounted from the `workshop-filters` ConfigMap (`files/` symlinks it). `jq`
required:

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

A token with only `stac:read` gets **403**. With `stac:write`, the empty `{}`
body above gets a 500, not a 400: the proxy can't evaluate the row-level filter
on a body with no `id` (a real collection has one).

**401 without a token, non-401 with one** = working. If it stays 401, check
`kubectl -n eoapi logs deploy/eoapi-stac-auth-proxy` (usual cause: release
not `eoapi`).

## Upgrade / uninstall

```bash
./deploy.sh deploy                    # idempotent re-deploy (tokens preserved)
helm uninstall eoapi -n eoapi         # or ./deploy.sh teardown
kubectl -n eoapi delete pvc --all     # PVCs (DB + Lab work) are retained by design
```

## Notebook data

The workshop notebooks (`docs/00`–`08`) run in the Labs against this deployment
(the Labs ship whichever notebooks the image was built with):
- `pgstacBootstrap.loadSamples` is **off** — the upstream sample collection
  `noaa-emergency-response` is stored without a STAC `type` field and breaks
  `pystac_client` (notebook 03). The notebooks create their own STAC data.
- the **features-loader Job** (`featuresLoader.enabled`) loads the NA CEC Level III
  Ecoregions into `features.ecoregions`, and tipg is configured with
  `TIPG_DB_SCHEMAS=["features","public"]`, so notebook 05 has vector data.

## Limitations
- **UI login needs TLS** — STAC Manager / Browser OIDC login uses PKCE (needs
  HTTPS); over http they're read-only. Enable `routing.tls`. (Browser's
  `redirect_uri` also still derives from the apex host upstream.)
- **Capacity** — Labs are always on: each requests `250m / 1Gi` and may burst
  to `2 CPU / 4Gi` (`jupyter.resources`), plus stac-manager's ~4Gi startup build
  and the backend. For ~20 participants, add 3× `b3-16` as a workshop node pool
  ([Terraform](../../terraform/README.md#workshop-node-pool)), raise the Lab
  requests to what a run-through of the notebooks actually uses (`kubectl top
  pods`), and consider `kubectl scale deploy/eoapi-raster --replicas=2` for tile
  load.
- **Not production** — test auth, single 1-replica DB (5Gi), http. For production
  use the CDK/AWS stack in [`DEPLOYMENT.md`](../../../DEPLOYMENT.md).
