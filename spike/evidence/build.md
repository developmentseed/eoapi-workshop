# Build: one participant's stack in a "pod" (local compose)

*2026-10-01 · Docker Desktop 28.5.2, arm64 Mac · branch `spike/per-user-stacks` · reproducible via `spike/checks/build/run.sh`*

## Result

The stack builds and starts. Every service answers on its own port inside the shared netns, and through jupyter-server-proxy under its prefix behind the Lab login.

- **44 PASS, 2 FAIL, 0 BLOCKED.** Both FAILs are real findings about the design (F1, F2 below), not broken wiring.
- **Cold start: 9 s** to `up --wait`, and **11 s** to the first `200` from `http://localhost:18888/stac/collections`. Images were already built and pulled; the baked DB load is included.
- **Idle memory: about 0.7 GiB for the whole stack, Lab included.** Measured with one uvicorn worker everywhere and mock-oidc without its reload watcher (table below).

## How to reproduce

```sh
cd spike
docker build -f ../Dockerfile.local -t eoapi-spike-lab-base ..   # base Lab image (arm64)
./gen-env.sh                                                     # random secrets -> spike/.env (gitignored)
docker compose -p eoapi-spike -f compose.participant.yml up -d --build --wait
checks/build/run.sh
```

`run.sh` runs three kinds of checks:
- **Host side:** containers running, published ports, uvicorn process count, image architecture.
- **`smoke.py` and `contract.py`:** run with `docker exec` inside the Lab container, so `localhost` is the pod netns and `http://localhost:18888` is the browser URL.
- **`offpod.py`:** runs in a throwaway container on the compose network but outside the pod netns, i.e. what a neighbouring pod sees.

## Raw output (`checks/build/run.sh`, final run, lines trimmed at ~200 chars)

```
PASS compose.all-running — database lab mock-oidc stac-auth-proxy stac-browser stac-fastapi stac-manager tipg titiler-pgstac
PASS compose.only-lab-published — eoapi-spike-lab-1 127.0.0.1:18888->18888/tcp
PASS workers.stac-fastapi — 1 uvicorn process
PASS workers.titiler-pgstac — 1 uvicorn process
PASS workers.tipg — 1 uvicorn process
PASS workers.mock-oidc — 1 uvicorn process
PASS arch.stac-browser — amd64 (no arm64 image published; emulated)
PASS arch.stac-manager — amd64 (no arm64 image published; emulated)
PASS arch.lab — arm64 native
PASS arch.database — arm64 native
PASS arch.stac-fastapi — arm64 native
PASS arch.titiler-pgstac — arm64 native
PASS arch.tipg — arm64 native
PASS arch.stac-auth-proxy — arm64 native
PASS arch.mock-oidc — arm64 native
PASS db.ecoregions — features.ecoregions rows=2548
PASS db.glad — collection=1 items=100
PASS db.fixed-compose-user-gone — ... FATAL:  role "username" does not exist
PASS direct.stac-fastapi:8081 — 200 collections=['glad-global-forest-change-1.11']
PASS direct.stac-auth-proxy:8084/stac — 200 root links e.g. ['http://localhost:8084/stac/']
PASS direct.stac-auth-proxy:8084-without-prefix-404 — 404 (ROOT_PATH must be in the path)
PASS direct.titiler:8082/raster — prefixed=200 unprefixed=200
PASS direct.tipg:8083/vector — 200 ['features.ecoregions']
PASS direct.mock-oidc:8085/oidc — 200 issuer=http://localhost:18888/oidc jwks=http://localhost:8085/oidc/.well-known/jwks.json
PASS direct.stac-browser:8080/browser — 200 base=/browser/ catalogUrl in runtime-config=True
PASS direct.stac-manager:8086 — 200 PUBLIC_URL substituted=True
PASS proxy.token-once-then-cookie — ?token= -> 200; no token, same client -> 200
PASS proxy.no-token-blocked — {'stac': 302, 'raster': 302, 'vector': 302, 'oidc': 302, 'browser': 302, 'manager': 302}
PASS proxy.wrong-token-blocked — 302
PASS proxy.host-allowlist — /proxy/example.com:80/ -> 403
PASS login.password-form — wrong=401 right=302 then /stac/collections via cookie=200
PASS proxy.stac — 200 self=['http://localhost:18888/stac/collections/glad-global-forest-change-1.11']
PASS proxy.raster.tilejson — 200 tiles=http://localhost:18888/raster/collections/glad-global-forest-change-1.11/items/hansen-gfc-2023-v1.11-80N-180W/...
PASS proxy.vector — 200 features=1 link e.g. ['http://localhost:18888/vector/collections/features.ecoregions']
PASS proxy.oidc — 200 authorization_endpoint=http://localhost:18888/oidc/authorize
PASS proxy.browser — index=200 deep-link=200
PASS proxy.manager — index=200 asset ['http://localhost:18888/manager/client.3d2b3ded.css'] -> 200; deep-link status=404 (http-server 404.html fallback, body is the app=True)
PASS write.server-side — anon=401 bearer POST=201 DELETE=200
PASS write.through-proxy — anon=401 bearer POST=201 GET=200 DELETE=200 (POST/DELETE pass Jupyter's XSRF check)
FAIL proxy.token-not-echoed — Lab token appears in response body of: ['stac/collections']
PASS contract.endpoints — {'stac': ('http://localhost:8084/stac', 'http://localhost:18888/stac'), 'raster': (...8082/raster, ...18888/raster), ...}
PASS contract.to_browser — http://localhost:8082/raster/collections/glad-global-forest-… -> http://localhost:18888/raster/collections/glad-global-forest…
PASS contract.to_browser-passthrough — foreign URL unchanged
PASS contract.collection_id — u01-sentinel-2-c1-l2a
FAIL isolation.backends-unreachable-off-pod — reachable from another netns: ['postgres:5432', 'stac-fastapi:8081', 'titiler:8082', 'tipg:8083', 'stac-auth-proxy:8084', 'mock-oidc:8085', 'stac-manager:8086', 'stac-browser:8080']; on k8s a per-participant NetworkPolicy is required (skeptic finding 1)
PASS db.password-required-off-pod — wrong password: ... password authentication failed for user "eoapi"; generated password: ok
```

## Path-prefix wiring (what worked)

| Prefix | jsp `absolute_url` | App setting | Server-side URL (kernel) |
|---|---|---|---|
| `/stac` | **True** (the proxy 404s without its prefix: `direct.stac-auth-proxy:8084-without-prefix-404`) | stac-auth-proxy `ROOT_PATH=/stac`, `UPSTREAM_URL=http://localhost:8081` | `http://localhost:8084/stac` |
| `/raster` | True | `TITILER_PGSTAC_API_ROOT_PATH=/raster` (answers with or without the prefix) | `http://localhost:8082/raster` |
| `/vector` | True | `TIPG_ROOT_PATH=/vector` | `http://localhost:8083/vector` |
| `/oidc` | True | mock-oidc `ISSUER=http://localhost:18888/oidc` (path becomes FastAPI `root_path`) | `http://localhost:8085/oidc` |
| `/browser` | True | `SB_pathPrefix=/browser/` (nginx `location /browser/`), `SB_catalogUrl=http://localhost:18888/stac/` | — |
| `/manager` | **False** (http-server serves at `/`; assets are absolute `PUBLIC_URL/...`) | `PUBLIC_URL=http://localhost:18888/manager`, `command: http-server -p 8086 ...` | — |

- **Server-side URLs carry the prefix too.** So a server-side response contains links like `http://localhost:8082/raster/...`, and `to_browser()` is a pure prefix swap (`contract.to_browser`). Without the prefix, the swap would produce `/raster/raster/`.
- **stac-auth-proxy has two OIDC URLs.**
  - `OIDC_DISCOVERY_URL` is only *advertised* (auth extension, OpenAPI), so it gets the browser URL `http://localhost:18888/oidc/...`.
  - `OIDC_DISCOVERY_INTERNAL_URL` is what it *fetches* (JWKS and the startup wait), so it goes direct to `localhost:8085`, which needs no Lab login.
  - Source: `stac-auth-proxy@v1.2.0 src/stac_auth_proxy/app.py:116,124,169`.
- **Links come out right without per-app host config.**
  - jupyter-server-proxy forwards the incoming `Host` header (`handlers.py:700-705`).
  - So stac (via ProcessLinksMiddleware), titiler, tipg and mock-oidc all generate `http://localhost:18888/<prefix>/...` links for browser requests, and `localhost:<port>/<prefix>/...` for kernel requests.
- **Writes through the proxy work.**
  - jsp passes `Authorization: Bearer` through, and skips Jupyter's XSRF check (`check_xsrf_cookie` deferred, `handlers.py:719`).
  - The Lab login is satisfied by `?token=` at the same time.

## Findings

**F1: the Lab token is echoed into STAC links (FAIL `proxy.token-not-echoed`).**
- jupyter-server-proxy forwards the whole query string, `token=` included.
- stac-fastapi copies the request query into the `/collections` `self` link: `http://localhost:18888/stac/collections?token=<TOKEN>` (seen in the raw response; value redacted here).
- `/search`, tipg and titiler did not echo it in the probed responses.
- The token also lands in every backend's access log.
- **Impact is low.** The token goes back to its owner, inside the owner's own stack.
- **Workaround:** laptop tools send `?token=` once and then use the cookie (`proxy.token-once-then-cookie` PASS). Document that, rather than `?token=` on every call.

**F2: every backend port is reachable from another network namespace (FAIL `isolation.backends-unreachable-off-pod`).**
- A container on the same network but outside the pod reached all 8 backend ports on the pod IP.
- This confirms skeptic finding 1 with a live probe. **On k8s a per-participant NetworkPolicy is mandatory.**
- Mitigations already in place:
  - Postgres requires the generated password off-pod (`db.password-required-off-pod`, scram).
  - Compose's fixed `username/password` role no longer exists.
- mock-oidc, stac-auth-proxy (hard-coded `0.0.0.0` in their `__main__`) and stac-browser (`listen 8080`) can't be bound to localhost by env alone.

**F3: inside the pod, Postgres trusts every connection over 127.0.0.1.**
- The official postgres `pg_hba.conf` has `host all all 127.0.0.1/32 trust`.
- A login as `eoapi` with a wrong password over `localhost` succeeds.
- That's fine when the pod is the trust boundary: the participant owns the whole stack and its terminal already has `PGPASSWORD`. Only the off-pod scram rule protects the DB, which is one more reason for F2's NetworkPolicy.

```
$ docker exec eoapi-spike-database-1 grep -v '^#' /var/lib/postgresql/data/pg_hba.conf | grep -v '^$'
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
...
host all all all scram-sha-256
```

**F4: pgstac's init script sizes Postgres from the *host's* memory.**
- `990_pgstac.sh` sets `shared_buffers = MemTotal/4` from `/proc/meminfo`, which is the node's RAM, not the container limit.
- On a b3-16 node that's about 4 GB per participant Postgres, which is an OOM risk under a pod memory limit.
- `db/initdb/zz_00_tuning.sh` pins 128MB / 512MB / 64MB / 8MB. Verified:

```
$ docker exec eoapi-spike-database-1 psql -U eoapi -d postgis -Atc "show shared_buffers; show effective_cache_size; show work_mem; show max_connections"
128MB
512MB
8MB
100
```

**F5: mock-oidc's image runs uvicorn with `reload=True`** (`mock-oidc-server app/__main__.py`).
- That means a watchfiles supervisor plus a spawned worker. Idle cost measured over 3 samples: **6.5–9.1 % CPU and 128 MiB**.
- Replaced with `command: /app/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8085 --workers 1`, the same app (`app/__init__.py` exports `app`). Afterwards: **0.18 % CPU and 49 MiB**.
- Across 20 stacks that saves about 1.5 CPU.
- Each container still generates its own RSA key at start. Recreating mock-oidc alone rotates the key, while stac-auth-proxy may hold the old JWKS until PyJWKClient refetches on an unknown `kid`. That path was not tested.

**F6: stac-browser 5.1.0 publishes linux/amd64 only**, like stac-manager. Both run emulated here; on the amd64 OVH nodes it doesn't matter.

```
$ docker manifest inspect -v ghcr.io/radiantearth/stac-browser:5.1.0 | grep architecture
  "architecture": "amd64",
```

**F7: stac-manager deep links return HTTP 404 with the app body.**
- http-server falls back to `404.html`, a copy of `index.html`, so the SPA loads.
- Browsers render it, but the status is 404. That's cosmetic, but a link checker or `verify` must not treat it as an outage.

**F8: the baked DB makes cold start a non-issue.**
- The init log shows the pgstac schema, then tuning, then ecoregions (2548 rows, 48 MB gz SQL), then glad (1 collection + 100 items, 12 KB gz SQL), with no network.
- `eoapi-spike-db` is 1.13 GB locally.

```
/usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/990_pgstac.sh
/usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/999_pgstac.sql
/usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/zz_00_tuning.sh
/usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/zz_10_ecoregions.sql.gz
/usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/zz_20_glad.sql.gz
 upsert_collection
 upsert_items
... LOG:  database system is ready to accept connections
```

## Idle footprint (`docker stats --no-stream`, after the check run, mock-oidc without reload)

| Container | Mem | CPU |
|---|---|---|
| lab | 89 MiB | 0.00 % |
| database | 111 MiB | 1.5 % |
| stac-fastapi | 63 MiB | 0.15 % |
| titiler-pgstac | 139 MiB | 0.18 % |
| tipg | 65 MiB | 0.18 % |
| stac-auth-proxy | 133 MiB | 0.15 % |
| mock-oidc | 49 MiB | 0.18 % |
| stac-browser (amd64, emulated) | 15 MiB | 0.00 % |
| stac-manager (amd64, emulated) | 36 MiB | 0.00 % |
| **total** | **≈ 0.70 GiB** | |

These are idle numbers only. A load measurement (notebooks 02–08 running) is a later agent's job.

## Deviations from the task / PR #35 compose

- **Ecoregions** are baked as a **PGDump SQL file**, converted from the zip at build time with the same ogr2ogr options as compose, rather than as the zip itself.
  - The pgstac image has no `ogr2ogr` or `shp2pgsql` (`ls /usr/bin/shp2pgsql` → not found).
  - So conversion happens in a `ghcr.io/osgeo/gdal:ubuntu-small-latest` build stage.
- **glad** is baked as SQL that calls `pgstac.upsert_collection` / `pgstac.upsert_items`, generated at build time by `db/glad_to_sql.py`.
  - The pgstac image has no pypgstac.
  - The source is the same as the chart's loader (MAAP STAC, first 100 items).
- **DB:**
  - The user is `eoapi` with a generated password, instead of `username/password`.
  - `-N 100` instead of `-N 500`.
  - The DB service also sets `PGUSER/PGPASSWORD/PGDATABASE`, because the image's `990_pgstac.sh` runs a bare `psql`. The first `up` failed with `FATAL: role "postgres" does not exist`.
  - There is no named volume (ephemeral; `down -v`).
- **stac-browser** runs `platform: linux/amd64` (F6). `SB_authConfig` is **enabled**; compose has it commented out.
- **stac-manager:** `command` is overridden to `-p 8086` (8080 is stac-browser's port in the shared netns).
- **mock-oidc:** `command` is overridden to drop `reload=True` (F5).
- **tipg:** `TIPG_DB_SCHEMAS=["features"]`, as compose has it. The chart's `["features","public"]` would publish `public` (skeptic finding 6).
- **titiler:** uses the chart's GDAL envVars. `CPL_TMPDIR=/tmp` and `MOSAIC_CONCURRENCY=1` are kept from compose.
- **Lab:**
  - Published on `127.0.0.1:18888` only.
  - `../docs` is mounted at `/home/jovyan/docs`, as compose does, so the notebook agent's edits show live.
  - The legacy `STAC_AUTH_PROXY_ENDPOINT` is still set for `docs/stac_auth.py`.
- **jupyter-server-proxy 4.6.0:**
  - The routes have no `command`: the services are already running in their own containers ("If the command is not specified or is an empty list, the server process is assumed to be started ahead of time", `config.py:97`).
  - Launcher tiles are disabled.

## Not tested here (left for later agents)

- A real browser:
  - STAC Browser rendering and its OIDC PKCE login via `/oidc` (redirect URI `http://localhost:18888/browser/auth`);
  - stac-manager login and edits;
  - the titiler `map.html` viewer.
- Tile rendering. The tilejson resolves, but no tile was fetched from S3.
- Notebooks 02–08 against this stack.
- TLS: `trust_xheaders` plus X-Forwarded-Proto through jsp to uvicorn (`FORWARDED_ALLOW_IPS=*`). This needs the kind/ingress setup.
- Memory under load.
