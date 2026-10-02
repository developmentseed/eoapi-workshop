# Auth: the Lab login as the participant's only door (local compose)

> **Superseded.** This is the pre-fix run of 2026-10-01. The current stack is described by `fix.md` (the fixes and a re-run of every topic) and `verify.md` (the independent re-run). The method and the reproduce steps below still apply.

*2026-10-01 · Docker Desktop, arm64 Mac · branch `spike/per-user-stacks` · stack from `evidence/build.md`, left running · reproducible via `spike/checks/auth/run.sh`*

## Result

**78 lines: 61 PASS, 17 FAIL, 0 BLOCKED.**

The Lab login holds. Without credentials, every prefix answers `302 /login` or `403`, and never content, whether the caller is a laptop or another pod. The same Lab token covers reads and writes from a laptop.

The 17 FAILs fall into three groups:

- **Around the front door (13 FAILs: 9 `sockets.*`, 4 `offpod.*`).** Every backend binds `0.0.0.0`. So another pod can:
  - mint a `stac:write` JWT from mock-oidc;
  - write through stac-auth-proxy;
  - write to stac-fastapi **with no token at all**.

  Loopback binds fix this for all five images that need more than a flag; that was tested on throwaway copies (`bindfix.*`, 10 PASS).
- **New: `?token=` collides with pgstac's pagination parameter (3 FAILs).** `GET /stac/search?token=<lab token>` and `GET …/items?token=` return **500**, and stac-fastapi writes the Lab token into its error log. pystac-client's `parameters={"token": …}` breaks GET search for the same reason. The working laptop recipe is below.
- **The Lab token is echoed (1 FAIL),** extending build F1. It comes back in stac, titiler and tipg links and in jupyter-server-proxy's `/stac` → `/stac/` redirect.

## How to reproduce

```sh
cd spike
docker compose -p eoapi-spike -f compose.participant.yml up -d --wait   # see evidence/build.md
checks/auth/run.sh
```

`run.sh` uses four vantage points. Each Python check is run with `common.py` prepended (`cat common.py X.py | docker … python -`).

| Vantage | How | Stands for |
|---|---|---|
| `inpod.py` | `docker exec` into the Lab | a notebook kernel: `localhost` = the pod |
| `laptop.py` | throwaway container in its own netns, to `http://host.docker.internal:18888` (the published port) | the participant's laptop: browser, QGIS, local pystac-client |
| `offpod.py` | throwaway container on `eoapi-spike_default`, **no credentials** (no `.env` mount), host `lab` = pod IP | another participant's pod without a NetworkPolicy |
| `bindprobe.py`, `cookieprobe.py` | throwaway copies of the images with the proposed config. The running stack is not touched. | proof that the proposed fixes work |

- **Secrets:** they come from the Lab's environment or a read-only `.env` mount. Every printed line goes through `redact()`. The final log was scanned: none of the three `.env` values and no `eyJ…` JWT appears.
- **Data:** collections `spike-auth-test`, `spike-auth-test-cookie`, `spike-auth-inpod` (+ one item), `spike-auth-offpod-proxy` and `spike-auth-offpod-direct`. Each is deleted in the same check. Nothing is left: `select id from pgstac.collections where id like 'spike-auth%'` returns 0 rows.

## Answers, item by item

### 1. No credentials: login or 403, never content (PASS, laptop and offpod)

- `{laptop,offpod}.unauth.{stac,raster,vector,browser,oidc,manager,lab,proxy}` probed 29 paths, including deep links, `/proxy/8081/…`, `/proxy/absolute/…` and `/proxy/localhost:8085/…`.
- Results by request type:
  - **GET and HEAD** return `302 /login?next=…`.
  - **Jupyter's `/api/*`** returns `403`.
  - **POST, PUT, PATCH, DELETE and OPTIONS** return `403` (30 requests).
  - **Websocket upgrades** return `403`.
- **Bodies:** no body contained a content marker (`stac_version`, `tilejson`, `FeatureCollection`, `"issuer"`, `"keys"`, `eyJ`, `<textarea`, …).
- **Wrong credentials are refused too:** `?token=wrong`, `Authorization: token wrong` and a forged login cookie all get a 302. A valid mock-oidc Bearer JWT with no Lab login gets a 403 (`laptop.write.refusals`).
- **Why it holds:** jupyter-server-proxy authenticates in `prepare()`, for every method (`jupyter-server-proxy@240a3ac handlers.py:139-170`; installed: 4.6.0). Websocket upgrades get a flat 403 (`:163-168`).
- **Public without login** (`*.unauth.public-surface`, PASS): `/login`, `/logout`, `/api` (`{"version": "2.21.1"}`), `/static/lab/*` and `/favicon.ico`. That is static assets plus the version, with no data.

### 2. Laptop reads with `?token=`

| What | Result |
|---|---|
| `Client.open(f"{LAB}/stac/?token={TOKEN}")`, then `search(limit=10, max_items=35)` | **PASS for GET and POST:** 35 unique items over 4 pages |
| `Client.open(f"{LAB}/stac/", parameters={"token": TOKEN})` | **FAIL for GET** (`APIError: Internal Server Error`); POST passes |
| `GET /stac/search?token=<lab>` and `GET /stac/collections/{id}/items?token=<lab>` | **500** (`/stac/` and `/stac/collections` are 200) |
| titiler: `tilejson.json?token=` → tile `6/0/11` | **PASS:** the tile URL in the tilejson carries `?token=`, so a cookieless client (QGIS XYZ) gets `200 image/jpeg` from S3. The same tile without the token gets a 302. |
| tipg: `items?token=&limit=5`, then follow `next` | **PASS:** page 1 ids 1–5, page 2 ids 6–10 |

- **Pagination:** yes, `requests.Session` keeps the Lab cookie (`username-host-docker-internal-18888`). The cookie is what makes GET pagination work.
  - The `next` link carries pgstac's `?token=next:…`.
  - Jupyter tries that as a Lab token. It doesn't match, so Jupyter falls back to the cookie: `user = token_user or cookie_user` (jupyter_server 2.21.1 `auth/identity.py:255-296`).
  - The cursor then reaches stac-fastapi intact.
- **Why `parameters=` fails:** it appends `token=<lab>` to *every* request. Both Jupyter and FastAPI take the last `token` value, so pgstac receives the Lab token as its cursor:

  ```
  asyncpg.exceptions.RaiseError: Could not find item using token: <HEX> item: <HEX> collection: <NULL>
  ```

  That is from `docker logs eoapi-spike-stac-fastapi-1`, with the hex redacted. `laptop.stac.lab-token-in-error-log` counts these lines on each run: there were 3 on the final run, each carrying the Lab token in clear.

### 3. Write from the laptop (PASS)

- **`laptop.write.token+bearer`:**
  1. `POST {LAB}/oidc/?token=` (form, same request as `docs/stac_auth.py`) mints a JWT.
  2. `POST /stac/collections?token=` with `Authorization: Bearer <JWT>` creates `spike-auth-test`: **201**.
  3. `GET`: 200. `DELETE`: 200. `GET` afterwards: 404.
- **`laptop.write.cookie+bearer`:** works without `?token=` on the write. Jupyter tries the Bearer JWT as a Lab token (`auth_header_pat = (token|bearer)\s+(.+)`, `identity.py:466-482`), it doesn't match, and Jupyter falls back to the cookie. Result: 201 / 200.
- **Refusals:**

  | Request | Result | Refused by |
  |---|---|---|
  | Bearer only, no Lab login | 403 | Jupyter |
  | `?token=` without Bearer | 401 | stac-auth-proxy |
  | `?token=` + a `stac:read`-only Bearer | 403 | stac-auth-proxy (scope check, `EnforceAuthMiddleware.py:176-192`) |

- This settles the plan's open point: laptop writes work, so the plan's "impossible, one Authorization header" line was wrong. The Lab credential travels in the query or cookie, and the Bearer in the header.

### 4. `Authorization: token <lab token>` → 401 from stac-auth-proxy (confirmed, documented)

| Header | Jupyter | Result on `/stac/collections` |
|---|---|---|
| `Authorization: token <LAB_TOKEN>` | accepts it | `401 {"detail": "Invalid Authorization header format"}` |
| `Authorization: Bearer <LAB_TOKEN>` | accepts it (the pattern also matches `bearer`) | `401 {"detail": "Invalid or expired token"}` |

- This happens on public GETs too. jupyter-server-proxy forwards every request header (`headers = self.request.headers.copy()`, `handlers.py:703`). stac-auth-proxy then rejects any non-Bearer header, and any non-JWT Bearer (`EnforceAuthMiddleware.py:138`).
- The other prefixes ignore the header: `/raster`, `/vector`, `/browser`, `/manager` and `/oidc` all return **200** with `Authorization: token`.
- **Rule for laptops:** the Lab token goes in `?token=` or the cookie, never in a header.

### 5. Notebook-style server-side writes (PASS)

- The check uses `docs/stac_auth.py` exactly as a notebook does:
  - `require_local_auth_stack()`;
  - `get_mock_oidc_token()` against `MOCK_OIDC_ENDPOINT=http://localhost:8085/oidc`;
  - `auth_headers()`.
- Results against `STAC_API_ENDPOINT=http://localhost:8084/stac`:
  - POST collection: 201. POST item: 201. Anonymous GET of the item: 200. DELETE item: 200. DELETE collection: 200.
  - Anonymous POST: 401. A `stac:read`-only Bearer: 403.
- No Lab login is involved: the kernel talks to the pod's localhost.

### 6. mock-oidc behind the Lab session: yes through the front door, no around it

- **Through the Lab** (`laptop.oidc.mint-without-session`, PASS):

  | Request | Result |
  |---|---|
  | `POST /oidc/` (mint form) | 403 |
  | `POST /oidc/token` | 403 |
  | `GET /oidc/authorize` | 302 |
  | `GET /oidc/.well-known/jwks.json` | 302 |

  No JWT appears in any body. With the Lab cookie, minting works (positive control).
- **Around the Lab** (`offpod.*`, FAIL), from a container that holds no credential at all:

  | Request | Result |
  |---|---|
  | `POST http://lab:8085/oidc/` | a `stac:write` JWT |
  | that JWT → `POST http://lab:8084/stac/collections` | **201** |
  | `POST http://lab:8081/collections` with **no token** | **201** (stac-fastapi has transactions on and no auth of its own) |

  Build F2 showed the ports *answer*. This shows the exploit end to end: any pod in the cluster can write to any participant's catalogue unless a NetworkPolicy or a loopback bind stops it.

### 7. Listening sockets in the pod netns

- **Method:** `ss` and `netstat` are not in the Lab image, so `inpod.py` parses `/proc/net/tcp{,6}`. Socket inodes are mapped to processes for the Lab container's own PIDs; other ports are named from the port plan.

| Bind | Port | Service | Reachable from other pods without a NetworkPolicy? |
|---|---|---|---|
| `0.0.0.0` | 18888 | Lab (jupyter-server) | yes, **by design** (the ingress target) |
| `0.0.0.0` + `::` | 5432 | postgres | **yes** (scram password off-pod; trust inside the pod, build F3) |
| `0.0.0.0` | 8080 | stac-browser (nginx) | **yes** |
| `0.0.0.0` | 8081 | stac-fastapi | **yes**, unauthenticated writes |
| `0.0.0.0` | 8082 | titiler-pgstac | **yes**, including `/external` (blind SSRF, skeptic finding 5) |
| `0.0.0.0` | 8083 | tipg | **yes** |
| `0.0.0.0` | 8084 | stac-auth-proxy | **yes** |
| `0.0.0.0` | 8085 | mock-oidc | **yes**, mints `stac:write` tokens |
| `0.0.0.0` | 8086 | stac-manager (http-server) | **yes** |
| `127.0.0.1` | ephemeral (6 in the final run, varies) | `python -m ipykernel` (kernel ZMQ, other testers' kernels) | no |
| `127.0.0.11` | ephemeral | Docker's embedded DNS | n/a (compose only) |

**Loopback binds tested** (`bindfix.*`). Each case is a throwaway container from the same image with the fix applied. For each, the check proves:
1. the listener is `127.0.0.1:<port>` only;
2. the service still answers 200 inside its netns;
3. a connect from another netns gets `ECONNREFUSED`.

| Service | Fix | Test result |
|---|---|---|
| mock-oidc | `uvicorn app:app --host 127.0.0.1 --port 8085 --workers 1` | PASS |
| stac-auth-proxy | `uvicorn stac_auth_proxy.app:create_app --factory --host 127.0.0.1 --port 8084`. The image's `python -m stac_auth_proxy` hard-codes `host="0.0.0.0"` (`__main__.py:10`). | PASS (`GET /stac/` 200) |
| stac-browser | mount `checks/auth/stac-browser-loopback.conf.template` (`listen 127.0.0.1:8080;`) over `/etc/nginx/conf.d/default.conf.template`. The entrypoint re-renders it with `SB_pathPrefix`, and the IPv6 hook leaves it alone. | PASS |
| stac-manager | `http-server -a 127.0.0.1 -p 8086 packages/client/dist` | PASS |
| postgres | `postgres -N 100 -c listen_addresses=127.0.0.1`. This also drops `::`, and the compose healthcheck (`pg_isready -h 127.0.0.1`) still works. | PASS |
| stac-fastapi, titiler-pgstac, tipg | `--host 127.0.0.1` | not run separately: the same uvicorn flag as mock-oidc |

**k8s caveat:** kubelet `httpGet` and `tcpSocket` probes target the pod IP, so they fail against loopback-bound containers. Use `exec` probes, or none on those containers. Loopback binds are defence in depth; the per-participant NetworkPolicy from skeptic finding 1 is still required.

### 8. Session cookie flags

| Request | `username-<host>` login cookie |
|---|---|
| `?token=` with `X-Forwarded-Proto: https` | `HttpOnly; Path=/; Secure; Expires=+30d` |
| `?token=` over plain http, no XFP | `HttpOnly; Path=/; Expires=+30d` (no Secure, as expected) |
| password form with `X-Forwarded-Proto: https` | `HttpOnly; Path=/; Secure; Expires=+30d` |
| `_xsrf` cookie (`GET /login`, XFP https) | `Path=/; Expires=+30d`. No Secure and no HttpOnly: it's a CSRF nonce that JS reads, not a credential. |

- **Secure comes from `trust_xheaders = True`:** tornado sets `request.protocol` from XFP, and `set_login_cookie` adds `secure` when it is `https` (`identity.py:386-400`).
- **Path is `/`** (`base_url`), so one login covers every prefix, including STAC Browser's OIDC `redirect_uri` under `/browser/auth`.
- **No SameSite attribute**, and a **30-day** lifetime (tornado's default).
- **Tested fix** (`cookiefix.samesite-expiry`, on a throwaway Lab with dummy credentials): `c.IdentityProvider.cookie_options = {"samesite": "Lax", "expires_days": 2}` gives `HttpOnly; Path=/; SameSite=Lax; Secure; Expires=+2.0d`.
- **XFP also reaches the backends:** jupyter-server-proxy copies the header and uvicorn trusts it (`FORWARDED_ALLOW_IPS=*`). Behind TLS, stac, vector, raster tilejson and the oidc endpoints all come out `https://…` (`xfp.links-https`).
  - Exception: mock-oidc's `issuer` stays `http://localhost:18888/oidc`, because it comes from the `ISSUER` env.
  - On k8s, `ISSUER` must be the https Lab URL.

## Other observations

- **The token echo is wider than build F1** (`laptop.token-echo`, FAIL). `?token=<lab>` comes back in:
  - stac `/collections` `self`;
  - the `href` of stac POST `/search`'s `next` link;
  - titiler tilejson `tiles[]`;
  - tipg items `self`/`next`;
  - the `Location` of jupyter-server-proxy's `/stac` → `/stac/` redirect.

  The impact is low: the echo goes to the token's owner, in the owner's own stack. It's the reason for the "send `?token=` once, then the cookie" advice. A tilejson URL copied into a chat leaks the Lab login.
- **jupyter-server-proxy forwards every request header to every backend**, the Lab session cookie included (`handlers.py:703`). That's harmless while every backend belongs to the participant. Source-read only; no echo server was run.
- **The Lab login is the real trust boundary.**
  - Once logged in, `/proxy/8081/…` reaches stac-fastapi directly, around stac-auth-proxy, and the terminal can `psql` as superuser.
  - Within one participant's pod, stac-auth-proxy is a teaching device, not a control.
  - Across pods, the NetworkPolicy plus loopback binds above are the control.
- **Exploration hygiene:** one exploratory probe printed the raw Lab token once to this session's tool output. It was the jupyter-server-proxy redirect `Location`, before the checks had `redact()`. It was not written to any file. `./gen-env.sh` plus a stack recreate rotates it if wanted.

## Laptop recipe (what the participant docs should say)

```python
LAB = "https://lab-u01.<domain>"          # local: http://localhost:18888
TOKEN = "<lab token>"
# Reads: ?token= ONCE on the root; requests.Session keeps the Lab cookie for every page.
from pystac_client import Client
cat = Client.open(f"{LAB}/stac/?token={TOKEN}")      # NOT parameters={"token": TOKEN}: GET search -> 500
items = cat.search(collections=[...], max_items=100).item_collection()
# Writes: Lab login (cookie or ?token=) + a mock-oidc Bearer in the header.
import httpx, re, html
s = httpx.Client(); s.get(f"{LAB}/stac/", params={"token": TOKEN})
jwt = html.unescape(re.search(r'id="token"[^>]*>(.*?)<', s.post(f"{LAB}/oidc/", data={
    "username": "me", "scopes": "openid stac:read stac:write", "claims": "{}"}).text, re.S)[1]).strip()
s.post(f"{LAB}/stac/collections", json={...}, headers={"Authorization": f"Bearer {jwt}"})
```

- **curl:** `curl -c jar "$LAB/stac/?token=$TOKEN" >/dev/null`, then `curl -b jar "$LAB/stac/search?..."`.
- **QGIS XYZ:** use the `tiles[0]` of `tilejson.json?token=…`.
- **Never** `Authorization: token …`, and never `?token=` on `/stac/search` or `/items`.

## Proposed fixes (for the fix-applying agent; not applied here)

1. **Loopback binds** (`compose.participant.yml`, later the chart). These are the exact commands proven by `bindfix.*`:
   - `database`: `command: postgres -N 100 -c listen_addresses=127.0.0.1`
   - `stac-fastapi`, `titiler-pgstac`, `tipg`: `--host 127.0.0.1`
   - `mock-oidc`: `["/app/.venv/bin/uvicorn","app:app","--host","127.0.0.1","--port","8085","--workers","1"]`
   - `stac-auth-proxy`: `command: uvicorn stac_auth_proxy.app:create_app --factory --host 127.0.0.1 --port 8084`
   - `stac-browser`: move `checks/auth/stac-browser-loopback.conf.template` to `spike/stac-browser/default.conf.template`, then mount it read-only at `/etc/nginx/conf.d/default.conf.template`
   - `stac-manager`: `command: ["http-server","-a","127.0.0.1","-p","8086","packages/client/dist"]`

   Then update `checks/build/offpod.py`:
   - `isolation.backends-unreachable-off-pod` should turn PASS;
   - `db.password-required-off-pod` can no longer connect, so it must expect "unreachable".

   On k8s: use `exec` probes, not `httpGet`, for those containers, and **keep the NetworkPolicy**.
2. **Docs, `deploy.sh verify` and notebook text:** apply the laptop recipe above.
   - `?token=` goes once on `/stac/`. Never on `/search` or `/items`, never as `parameters=`, never as an `Authorization: token` header.
   - No config-only fix exists: jupyter-server-proxy has no hook to rewrite the query string. A code fix would need a custom proxy handler.
3. **`lab/jupyter_server_config.py`:** add `c.IdentityProvider.cookie_options = {"samesite": "Lax", "expires_days": <workshop days>}`. Tested with 2 days on a throwaway Lab.
4. **Chart:** set mock-oidc `ISSUER` to `https://lab-uNN.<domain>/oidc`. Use the https URL in `OIDC_DISCOVERY_URL` and in `SB_authConfig.openIdConnectUrl` too.

## Raw output (`checks/auth/run.sh`, final run)

```
PASS inpod.write.notebook-helpers — STAC_API_ENDPOINT=http://localhost:8084/stac {'POST collection': 201, 'POST item': 201, 'GET item (anon)': 200, 'DELETE item': 200, 'DELETE collection': 200}
PASS inpod.write.refusals — anonymous=401 stac:read-only Bearer=403
FAIL sockets.0.0.0.0:5432 — postgres binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.:::5432 — postgres binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8080 — stac-browser binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8081 — stac-fastapi binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8082 — titiler-pgstac binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8083 — tipg binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8084 — stac-auth-proxy binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8085 — mock-oidc binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
FAIL sockets.0.0.0.0:8086 — stac-manager binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it
PASS sockets.0.0.0.0:18888 — lab (jupyter-server): the front door, must accept the ingress
PASS sockets.127.0.0.1:34293 — loopback only: /opt/conda/envs/eoapi-workshop/bin/python -Xfrozen_modules=off -m ipyk
PASS sockets.127.0.0.1:36597 — loopback only: /opt/conda/envs/eoapi-workshop/bin/python -Xfrozen_modules=off -m ipyk
PASS sockets.127.0.0.1:37217 — loopback only: /opt/conda/envs/eoapi-workshop/bin/python -Xfrozen_modules=off -m ipyk
PASS sockets.127.0.0.1:42417 — loopback only: /opt/conda/envs/eoapi-workshop/bin/python -Xfrozen_modules=off -m ipyk
PASS sockets.127.0.0.11:44993 — Docker's embedded DNS (compose only, absent on k8s)
PASS sockets.127.0.0.1:49643 — loopback only: /opt/conda/envs/eoapi-workshop/bin/python -Xfrozen_modules=off -m ipyk
PASS sockets.127.0.0.1:52425 — loopback only: /opt/conda/envs/eoapi-workshop/bin/python -Xfrozen_modules=off -m ipyk
PASS cookie.token-login.xfp-https — flags=['Expires=+30d', 'HttpOnly', 'Path=/', 'Secure'] SameSite=absent (browser default Lax)
PASS cookie.token-login.plain-http — flags=['Expires=+30d', 'HttpOnly', 'Path=/'] (no X-Forwarded-Proto -> no Secure, as expected)
PASS cookie.password-login.xfp-https — login=302 cookie flags=['Expires=+30d', 'HttpOnly', 'Path=/', 'Secure']; _xsrf cookie flags=['Expires=+30d', 'Path=/'] (no Secure/HttpOnly on _xsrf: a CSRF nonce JS must read, not a credential)
PASS xfp.links-https — stac/vector/raster/oidc endpoints all https=True; oidc issuer=http://localhost:18888/oidc (fixed by the ISSUER env, not the request)
PASS laptop.unauth.stac — /stac/=302 /stac/collections=302 /stac/search?limit=1=302 /stac/collections/glad-global-forest-change-1.11/items?limit=1=302
PASS laptop.unauth.raster — /raster/=302 /raster/healthz=302 /raster/collections/glad-global-forest-change-1.11/items/hansen-gfc-2023-v1.11-80N-180W/WebMercatorQuad/tilejson.json?assets=gain=302
PASS laptop.unauth.vector — /vector/=302 /vector/collections=302 /vector/collections/features.ecoregions/items?limit=1=302
PASS laptop.unauth.browser — /browser/=302 /browser/runtime-config.js=302
PASS laptop.unauth.oidc — /oidc/=302 /oidc/.well-known/openid-configuration=302 /oidc/.well-known/jwks.json=302 /oidc/authorize?client_id=x&response_type=code&redirect_uri=http://localhost:18888/browser/auth=302
PASS laptop.unauth.manager — /manager/=302 /manager/collections=302
PASS laptop.unauth.lab — /lab=302 /lab/tree/docs=302 /api/contents=403 /api/kernels=403 /api/terminals=403 /files/docs/README.md=302 /lab/terminals/1=302 /api/sessions=403
PASS laptop.unauth.proxy — /proxy/8081/collections=302 /proxy/absolute/8084/stac/=302 /proxy/localhost:8085/oidc/=302
PASS laptop.unauth.public-surface — /login=200 /logout=200 /api=200 /static/lab/index.html=200 /favicon.ico=200; /api body={"version": "2.21.1"}
PASS laptop.unauth.methods — 30 requests, non-GET -> 403, HEAD -> 302
PASS laptop.unauth.websocket — {'/stac/': 403, '/oidc/': 403, '/raster/': 403, '/browser/': 403, '/terminals/websocket/1': 403}
PASS laptop.unauth.bad-credentials — [?token=wrong]=302 [Authorization: token wrong]=302 [forged login cookie]=302
PASS laptop.pystac-client.url-token.GET — 35 items over 4 pages (limit=10): got 35 unique=35; session cookies=['username-host-docker-internal-18888']
FAIL laptop.pystac-client.parameters-token.GET — APIError: Internal Server Error (pgstac reads ?token= as its pagination cursor)
PASS laptop.pystac-client.url-token.POST — 35 items over 4 pages (limit=10): got 35 unique=35; session cookies=['username-host-docker-internal-18888']
PASS laptop.pystac-client.parameters-token.POST — got 35 items, unique=35
FAIL laptop.stac.get-with-lab-token — {'/stac/search': 500, '/stac/collections/glad-global-forest-change-1.11/items': 500, '/stac/collections': 200, '/stac/': 200} — stac-fastapi log: 'Could not find item using token: <LAB_TOKEN>'
PASS laptop.titiler.tile — tilejson=200; tile 6/0/11 from the tilejson URL, no cookie: 200 image/jpeg 1185 B (URL carries ?token= from the tilejson); same tile without token: 302
PASS laptop.tipg.items — page1=200 ids=[1, 2, 3, 4, 5]; next link=200 ids=[6, 7, 8, 9, 10]
FAIL laptop.token-echo — Lab token echoed in: ['stac POST /search next.href', 'stac /collections self', 'raster tilejson tiles[]', 'vector items self/next', 'stac /stac -> /stac/ Location']
PASS laptop.write.token+bearer — mint via /oidc/?token= ok; POST=201 GET=200 DELETE=200 GET-after=404 (spike-auth-test)
PASS laptop.write.cookie+bearer — cookie=['username-host-docker-internal-18888'] POST=201 DELETE=200 (spike-auth-test-cookie)
PASS laptop.write.refusals — [Bearer only, no Lab login]=403 [?token= only, no Bearer]=401 [?token= + stac:read-only Bearer]=403 (403 #1 is Jupyter, 401/403 #2/#3 are stac-auth-proxy)
PASS laptop.header-token.stac — 'Authorization: token <LAB_TOKEN>' -> (401, 'Invalid Authorization header format'); 'Authorization: Bearer <LAB_TOKEN>' -> (401, 'Invalid or expired token') (Jupyter accepted both; the 401 bodies are stac-auth-proxy's)
PASS laptop.header-token.other-prefixes — {'/raster/healthz': 200, '/vector/collections': 200, '/browser/': 200, '/manager/': 200, '/oidc/.well-known/openid-configuration': 200} — only /stac rejects a non-Bearer header
PASS laptop.oidc.mint-without-session — [POST /oidc/]=403 [POST /oidc/token]=403 [GET /oidc/authorize]=302 [GET jwks]=302; no JWT in any body
PASS laptop.oidc.mint-with-session — with the Lab cookie, POST /oidc/ returns a JWT (positive control)
FAIL laptop.stac.lab-token-in-error-log — stac-fastapi logged 3 x 'asyncpg RaiseError: Could not find item using token: <LAB_TOKEN>' during this run (pgstac took ?token= as its cursor)
PASS offpod.unauth.stac — /stac/=302 /stac/collections=302 /stac/search?limit=1=302 /stac/collections/glad-global-forest-change-1.11/items?limit=1=302
PASS offpod.unauth.raster — /raster/=302 /raster/healthz=302 /raster/collections/glad-global-forest-change-1.11/items/hansen-gfc-2023-v1.11-80N-180W/WebMercatorQuad/tilejson.json?assets=gain=302
PASS offpod.unauth.vector — /vector/=302 /vector/collections=302 /vector/collections/features.ecoregions/items?limit=1=302
PASS offpod.unauth.browser — /browser/=302 /browser/runtime-config.js=302
PASS offpod.unauth.oidc — /oidc/=302 /oidc/.well-known/openid-configuration=302 /oidc/.well-known/jwks.json=302 /oidc/authorize?client_id=x&response_type=code&redirect_uri=http://localhost:18888/browser/auth=302
PASS offpod.unauth.manager — /manager/=302 /manager/collections=302
PASS offpod.unauth.lab — /lab=302 /lab/tree/docs=302 /api/contents=403 /api/kernels=403 /api/terminals=403 /files/docs/README.md=302 /lab/terminals/1=302 /api/sessions=403
PASS offpod.unauth.proxy — /proxy/8081/collections=302 /proxy/absolute/8084/stac/=302 /proxy/localhost:8085/oidc/=302
PASS offpod.unauth.public-surface — /login=200 /logout=200 /api=200 /static/lab/index.html=200 /favicon.ico=200; /api body={"version": "2.21.1"}
PASS offpod.unauth.methods — 30 requests, non-GET -> 403, HEAD -> 302
PASS offpod.unauth.websocket — {'/stac/': 403, '/oidc/': 403, '/raster/': 403, '/browser/': 403, '/terminals/websocket/1': 403}
PASS offpod.unauth.bad-credentials — [?token=wrong]=302 [Authorization: token wrong]=302 [forged login cookie]=302
FAIL offpod.tcp-reachable — reachable without any credential: ['postgres:5432', 'stac-browser:8080', 'stac-fastapi:8081', 'titiler-pgstac:8082', 'tipg:8083', 'stac-auth-proxy:8084', 'mock-oidc:8085', 'stac-manager:8086']
FAIL offpod.oidc-mint-direct — POST http://lab:8085/oidc/ minted a stac:write JWT (652 chars) with no Lab login
FAIL offpod.write-via-auth-proxy — self-minted JWT -> POST http://lab:8084/stac/collections=201, DELETE=200 (spike-auth-offpod-proxy)
FAIL offpod.write-stac-fastapi-no-token — no token at all -> POST http://lab:8081/collections=201, DELETE=200 (spike-auth-offpod-direct)
PASS bindfix.mock-oidc.loopback — listens on ['127.0.0.1:8085']; GET /oidc/.well-known/openid-configuration -> 200
PASS bindfix.mock-oidc.offpod-refused — connect spike-auth-bind-mock-oidc:8085 from another netns -> ECONNREFUSED
PASS bindfix.stac-auth-proxy.loopback — listens on ['127.0.0.1:8084']; GET /stac/ -> 200
PASS bindfix.stac-auth-proxy.offpod-refused — connect spike-auth-bind-stac-auth-proxy:8084 from another netns -> ECONNREFUSED
PASS bindfix.stac-browser.loopback — listens on ['127.0.0.1:8080']; GET /browser/ -> 200
PASS bindfix.stac-browser.offpod-refused — connect spike-auth-bind-stac-browser:8080 from another netns -> ECONNREFUSED
PASS bindfix.stac-manager.loopback — listens on ['127.0.0.1:8086']; GET / -> 200
PASS bindfix.stac-manager.offpod-refused — connect spike-auth-bind-stac-manager:8086 from another netns -> ECONNREFUSED
PASS bindfix.postgres.loopback — listens on ['127.0.0.1:5432']; tcp connect ok
PASS bindfix.postgres.offpod-refused — connect spike-auth-bind-postgres:5432 from another netns -> ECONNREFUSED
PASS cookiefix.samesite-expiry — /api/status=200 flags=['Expires=+2.0d', 'HttpOnly', 'Path=/', 'SameSite=Lax', 'Secure']
```
