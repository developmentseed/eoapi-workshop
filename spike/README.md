# One eoAPI stack per participant

One participant's full eoAPI stack, run locally with docker compose and laid out like a Kubernetes pod; `chart/` runs one such pod per participant.

This started as a spike. Its investigation (every topic's checks, the write-ups and the screenshots) is on branch [`spike/per-user-stacks-evidence`](https://github.com/lhoupert/eoapi-workshop/tree/spike/per-user-stacks-evidence/spike), commit d50c0ce.

- The Lab container owns the network namespace, and every other service joins it (`network_mode: service:lab`), so they share `localhost`.
- Only the Lab is published, on `127.0.0.1:18888`.
- The browser reaches every service same-origin through jupyter-server-proxy, behind the Lab password.

| URL (after login) | Service | In-pod port |
|---|---|---|
| http://localhost:18888/lab | JupyterLab | 18888 |
| http://localhost:18888/stac/ | stac-auth-proxy → stac-fastapi-pgstac | 8084 → 8081 |
| http://localhost:18888/raster/ | titiler-pgstac | 8082 |
| http://localhost:18888/vector/ | tipg | 8083 |
| http://localhost:18888/oidc/ | mock-oidc | 8085 |
| http://localhost:18888/browser/ | STAC Browser | 8080 |
| http://localhost:18888/manager/ | STAC Manager | 8086 |
| — | pgstac (Postgres) | 5432 |

## Start

Run these from `spike/`:

```sh
# 1. Lab base image from the repo's Dockerfile.local (once; slow the first time)
docker build -f ../Dockerfile.local -t eoapi-spike-lab-base ..
# 2. Secrets (once): random Postgres password, Lab password and Lab token
./gen-env.sh
# 3. Build the Lab + DB images and start (about 10 s once the images exist)
docker compose -p eoapi-spike -f compose.participant.yml up -d --build --wait
```

Open http://localhost:18888 and log in with the password, or with `?token=<LAB_TOKEN>` (see below).

Every service but the Lab binds `127.0.0.1`: nothing else in the pod is reachable from another container or pod.

## From a laptop tool: token once, then the cookie

Jupyter's login parameter `?token=` has the same name as STAC's pagination cursor. On `/stac/search` or `/stac/collections/{id}/items` it gives HTTP 500, writes the Lab token to stac-fastapi's log, and is echoed into `next`/`self` links and tile URLs. So send it once, on a URL that is not a STAC page, and let the cookie do the rest:

```python
from pystac_client import Client
client = Client.open(f"{LAB}/stac/?token={TOKEN}")  # requests.Session keeps the Lab cookie
```

```sh
curl -c jar "$LAB/api/status?token=$TOKEN" && curl -b jar "$LAB/stac/search?limit=5"
```

- Never pass the token as pystac-client `parameters={"token": ...}`, and never as `Authorization: token ...` (stac-auth-proxy answers 401).
- Writes: the cookie (or `?token=`) plus `Authorization: Bearer <JWT>`, the JWT minted with `POST $LAB/oidc/`.
- QGIS XYZ: use `tiles[0]` from `/raster/.../tilejson.json?token=...`. Tile and tilejson URLs fetched that way contain the Lab token: do not paste them anywhere.

## Where the password is

`spike/.env` holds the secrets. It is gitignored and written by `gen-env.sh` with mode 600.

- `LAB_PASSWORD`: for the login form.
- `LAB_TOKEN`: for `?token=` or scripts. The login form accepts it too.
- `POSTGRES_PASSWORD`: the DB user is `eoapi`, the database `postgis`.

```sh
grep LAB_PASSWORD .env
```

## Stop

```sh
docker compose -p eoapi-spike -f compose.participant.yml down -v   # -v: drop the DB; the next up reloads the baked data
```

The DB lives in the pgstac image's anonymous volume. `up --force-recreate` alone keeps it: add `--renew-anon-volumes` (`-V`) to start from the baked data again.

```sh
docker compose -p eoapi-spike -f compose.participant.yml up -d --wait --force-recreate -V
```

## On Kubernetes (local kind)

`chart/` runs the same stack as one pod per participant, behind one Ingress (`lab-uNN.<domain>`).

- Each participant's DB and `/home/jovyan/work` are on PVCs: they survive pod replacement and are deleted with the participant or the release.
- The NetworkPolicy closes every port but the Lab's to the ingress controller. Out of the pod, only DNS and 80/443 on public addresses are allowed (`egressExcept` closes more).
- The Lab and DB images come from `<registry>/eoapi-workshop-{lab,db}:<image.tag>`. CI (`.github/workflows/publish-participant-images.yml`) pushes them for amd64 as `sha-<commit>`. On kind, tag the local builds `:local` and load them.
- `nodeSelector`/`tolerations` pin the pods to the workshop node pool; `prepull: true` adds a DaemonSet that pulls every image onto each of its nodes.

```sh
export KUBECONFIG=$PWD/.kind-kubeconfig
kind create cluster --name eoapi-spike --config kind/cluster.yaml --kubeconfig $KUBECONFIG
kubectl --context kind-eoapi-spike apply -f \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml
# Public images, per platform (an arm64 Mac here): `kind load` fails on multi-platform
# indexes with Docker's containerd store. stac-browser and stac-manager are amd64 only.
docker save --platform linux/arm64 ghcr.io/stac-utils/stac-fastapi-pgstac:7.0.0 ghcr.io/stac-utils/titiler-pgstac:3.2.0 \
  ghcr.io/developmentseed/tipg:1.6.1 ghcr.io/developmentseed/stac-auth-proxy:v1.2.0 \
  | docker exec -i eoapi-spike-control-plane ctr -n k8s.io images import --platform linux/arm64 --digests -
docker save --platform linux/amd64 ghcr.io/radiantearth/stac-browser:5.1.0 ghcr.io/developmentseed/stac-manager:1.0.3 \
  | docker exec -i eoapi-spike-control-plane ctr -n k8s.io images import --platform linux/amd64 --digests -
# The Lab and DB built by compose (rebuild the Lab whenever docs/ changes: it bakes the notebooks in)
for i in lab db; do docker tag eoapi-spike-$i ghcr.io/developmentseed/eoapi-workshop-$i:local; done
kind load docker-image --name eoapi-spike ghcr.io/developmentseed/eoapi-workshop-{lab,db}:local
kubectl --context kind-eoapi-spike create namespace spike-own
RELEASE=spike ./deploy.sh kind-eoapi-spike spike-own up local u01 u02
checks/frontdoor-own/run.sh && checks/verify/own.sh   # browser: http://lab-u01.spike.local:18080 (/etc/hosts)
```

`deploy.sh` is the only way in for a real cluster: it takes the context, namespace, image tag and the whole participant list every time, refuses to drop participants without `REMOVE=1`, prints the credentials as CSV (`creds`), and `down` uninstalls the release and its volumes but never the namespace.

## On a real cluster

The cluster provides ingress-nginx, cert-manager and a default StorageClass. The images must be in GHCR, and for more than a few participants the workshop node pool must exist (see Sizing). `chart/values-labs.yaml` holds the settings for the OVH cluster "labs": hosts, TLS through a namespaced Let's Encrypt issuer (staging for rehearsals), and the pool settings commented out until the pool exists.

```sh
C=<kube context>; NS=eoapi-workshop
VALUES=chart/values-labs.yaml ./deploy.sh $C $NS up sha-<commit> u01 u02 u03
./warm.sh $C $NS                       # the first world-view tile per stack, ~2 min cold
./deploy.sh $C $NS creds > slips.csv   # one URL + password per participant
```

Rehearse before the event: 2–3 participants, staging certificates, and nothing else in the namespace touched. Check what kind cannot prove:

- [ ] The Certificate is Ready and `https://lab-u01.<domain>` serves it. After login, the Lab's cookie is `Secure`.
- [ ] Every pod is 9/9, the PVCs are Bound, and a Lab terminal can write to `work/` (`fsGroup` on the cloud volume).
- [ ] After `kubectl rollout restart` of one participant, their collection and their `work/` file are still there.
- [ ] Egress, which depends on the cluster's policy engine: from a Lab terminal, `kubernetes.default.svc:443`, another namespace's Service and a node IP time out, while DNS, Earth Search and S3 answer. If the API server's endpoint is a public address, add it to `egressExcept`.
- [ ] u02's Lab cannot reach u01's pod IP.
- [ ] A notebook kernel starts and runs (websockets through ingress-nginx), and notebooks 00–08 run end to end for one participant.
- [ ] The STAC Browser and STAC Manager logins work in Safari and Firefox.
- [ ] `warm.sh` timings, then `CONFIRM=$NS ./deploy.sh $C $NS down` leaves the namespace and its other releases alone.

## Sizing

Measured in the spike on one participant's pod (local Docker, adjusted for Kubernetes):

| State | Memory per pod |
|---|---|
| Fresh | 0.64 GiB |
| Warm | 1.0–1.4 GiB |
| Busiest: tiles, STAC searches and a 478 MiB raster in a kernel | 2.7–3.0 GiB |

- The chart requests 580m CPU and 2.75 GiB per pod (limits: 6.1 GiB). Memory limits packing, not CPU: a pod averages 0.25–0.5 cores under load, and Postgres peaks around 1.2 cores during vector tiles.
- A 3 GiB Lab holds one big-raster kernel, not two.
- Pods per node: 1 on an 8 GB node, 4 on 16 GB, 8–10 on 32 GB (the last two extrapolated). Keep one spare node: losing a node stops every stack on it.
- Each node pulls about 3.4 GiB of images; `prepull: true` does it ahead of time.
- The world-view glad tile takes about 112 s cold and 0.4 s warm: warm each stack after deploying.

## Files

- `compose.participant.yml`: the stack. Images and tags come from PR #35's `docker-compose.yml`.
- `lab/`: `FROM eoapi-spike-lab-base` plus jupyter-server-proxy 4.6.0 and `jupyter_server_config.py`, which sets the login, the proxy routes and kernel culling.
- `db/`: pgstac v0.9.11 with the ecoregions table and the glad collection (100 items) baked in as init SQL. A container start needs no network.
- `stac-browser/default.conf.template`: the image's nginx template, listening on `127.0.0.1` only.
- `chart/`: the participant chart (`values-labs.yaml`: the labs cluster); `deploy.sh`: install, credentials and teardown for it;
  `warm.sh`: the first world-view tile of every stack.
- `checks/frontdoor-own/run.sh`, `checks/verify/own.sh`: the chart's tests on kind (isolation, egress, persistence, upgrades, credentials), one PASS|FAIL|BLOCKED line per check.
