# Spike: one participant's eoAPI stack in a "pod"

One participant's full eoAPI stack, run locally with docker compose and laid out like a Kubernetes pod.

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

Jupyter's login parameter `?token=` has the same name as STAC's pagination cursor. On `/stac/search` or `/stac/collections/{id}/items` it gives HTTP 500, writes the Lab token to stac-fastapi's log, and is echoed into `next`/`self` links and tile URLs (`evidence/auth.md`, `evidence/apis.md`). So send it once, on a URL that is not a STAC page, and let the cookie do the rest:

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

## Check

```sh
checks/build/run.sh      # one PASS|FAIL|BLOCKED line per check
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

`chart/` runs the same stack as one pod per participant, behind one Ingress (`lab-uNN.<domain>`). Steps, checks and findings are in `evidence/frontdoor-own.md` and `evidence/hardening.md`.

- Each participant's DB and `/home/jovyan/work` are on PVCs: they survive pod replacement and are deleted with the participant or the release.
- The NetworkPolicy closes every port but the Lab's to the ingress controller. Out of the pod, only DNS and 80/443 on public addresses are allowed (`egressExcept` closes more).
- The Lab and DB images come from `<registry>/eoapi-workshop-{lab,db}:<image.tag>`. CI (`.github/workflows/publish-participant-images.yml`) pushes them for amd64 as `sha-<commit>`. On kind, tag the local builds `:local` and load them.
- `nodeSelector`/`tolerations` pin the pods to the workshop node pool; `prepull: true` adds a DaemonSet that pulls every image onto each of its nodes.

```sh
kind create cluster --name eoapi-spike --config kind/cluster.yaml --kubeconfig .kind-kubeconfig
# then ingress-nginx and the public images as in evidence/frontdoor-own.md, and:
for i in lab db; do docker tag eoapi-spike-$i ghcr.io/developmentseed/eoapi-workshop-$i:local; done
kind load docker-image --name eoapi-spike ghcr.io/developmentseed/eoapi-workshop-{lab,db}:local
KUBECONFIG=.kind-kubeconfig RELEASE=spike ./deploy.sh kind-eoapi-spike spike-own up local u01 u02
checks/frontdoor-own/run.sh && checks/verify/own.sh
```

`deploy.sh` is the only way in for a real cluster: it takes the context, namespace, image tag and the whole participant list every time, refuses to drop participants without `REMOVE=1`, prints the credentials as CSV (`creds`), and `down` uninstalls the release and its volumes but never the namespace.

## Files

- `compose.participant.yml`: the stack. Images and tags come from PR #35's `docker-compose.yml`.
- `lab/`: `FROM eoapi-spike-lab-base` plus jupyter-server-proxy 4.6.0 and `jupyter_server_config.py`, which sets the login, the proxy routes and kernel culling.
- `db/`: pgstac v0.9.11 with the ecoregions table and the glad collection (100 items) baked in as init SQL. A container start needs no network.
- `stac-browser/default.conf.template`: the image's nginx template, listening on `127.0.0.1` only.
- `checks/<topic>/run.sh`: one PASS|FAIL|BLOCKED line per check, per topic (build, apis, auth, browser-apps, notebooks, footprint, frontdoor-own).
- `evidence/<topic>.md`: what was run, results and findings; `evidence/fix.md`: the fixes applied after the testers and the re-run of every topic.
- `chart/`: the participant chart; `deploy.sh`: install, credentials and teardown for it.
- `evidence/hardening.md`: persistence, egress, pinned images and `deploy.sh`, with their check runs.
