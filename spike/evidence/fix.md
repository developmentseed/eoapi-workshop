# Fixes applied after the testers, and a re-run of every topic

*2026-10-01 · branch `spike/per-user-stacks` · compose project `eoapi-spike` + local kind `eoapi-spike` · every topic re-run from `spike/checks/<topic>/run.sh` after the fixes*

This run follows the interrupted tester runs (usage limit). Nothing from them was taken on trust. Each topic's own script was run again against the fixed stack. First, the uncommitted browser-apps work (staged, never committed because commit signing was blocked) was committed as `6356907` and `3fcdbec`, so it could not be lost.

## Results

| Topic | Before (tester report) | After the fixes | Remaining FAILs |
|---|---|---|---|
| build | 44 / 2 / 0 | **45 / 1 / 0** | `proxy.token-not-echoed`: the `?token=` design limit |
| apis | 55 / 8 / 0 | **61 / 4 / 0** | 2 × `?token=` collision, 2 × `upstream.stac-auth-proxy.query-encoding.*` |
| auth | 61 / 17 / 0 | **56 / 4 / 0** | 4 × `?token=` collision or echo |
| browser-apps | 29 / 7 / 0 | **32 / 1 / 0** | `manager.delete`: upstream no-op button |
| notebooks | 110 / 48 / 4 | **135 / 2 / 4** | 2 × `upstream.stac-auth-proxy.query-encoding.*`; 4 BLOCKED (real browser / TLS) |
| footprint | 31 / 0 / 0 (×3) | **31 / 0 / 0** (`results/postfix`) | none |
| frontdoor-own (kind) | 45 / 0 / 0 | **46 / 0 / 0** | none |

Counts are PASS / FAIL / BLOCKED. The auth total has fewer lines because the throwaway-container proofs of the bind and cookie fixes were dropped. The live stack now proves both directly (see "Check changes").

No remaining FAIL is a broken prefix, link or login. Every remaining FAIL belongs to one of three groups:
1. Jupyter's `?token=` shares its name with pgstac's pagination cursor (design limit, no hook to fix it).
2. stac-auth-proxy v1.2.0 rebuilds query strings without encoding them (upstream bug; the notebooks avoid it).
3. stac-manager 1.0.3's Delete button does nothing (upstream).

## Fixes applied

| # | Problem (tester) | Fix | Commit |
|---|---|---|---|
| 1 | auth: every backend bound `0.0.0.0`. Another pod could mint `stac:write` JWTs, write to stac-fastapi with no token, and reach Postgres | Every service but the Lab binds `127.0.0.1`: `listen_addresses`, `--host 127.0.0.1`, stac-auth-proxy run through uvicorn (its `__main__` hard-codes 0.0.0.0), nginx template `spike/stac-browser/default.conf.template`, `http-server -a 127.0.0.1`. Applied in compose and the chart; the NetworkPolicy stays | `ac03acf` |
| 2 | browser-apps F1: the trailing-slash 307 dropped `/stac`, so stac-manager create hit Jupyter (403) and showed the Lab token on screen; queryables `$id` lacked `/stac` | stac-fastapi `--root-path /stac` | `ac03acf` |
| 3 | apis A1: `/stac/api.html` loaded Jupyter's `/api` | Fixed by #2 (`/stac/api.html` → spec `/stac/api`). `SWAGGER_UI_INIT_OAUTH` was **not** needed | `ac03acf` |
| 4 | browser-apps F2: stac-manager never asks for `stac:write`, so every save got 403 | `sed` adds `stac:write` to the built bundle's scope at container start, then `exec http-server` | `ac03acf` |
| 5 | auth: the Lab cookie had no SameSite and a 30-day life | `cookie_options = {"samesite": "Lax", "expires_days": 2}` | `ac03acf` |
| 6 | apis A4 / browser-apps F6: glad carried MAAP's queryables and tilejson links | `glad_to_sql.py` keeps only `license` and `cite-as`; DB image rebuilt | `ac03acf` |
| 7 | notebooks: legacy `STAC_AUTH_PROXY_ENDPOINT` | Removed from compose and the chart | `ac03acf` |
| 8 | footprint: titiler still growing; CPU requests below measured averages | Chart: titiler 140m / 464Mi / 768Mi, stac-manager limit 192Mi, CPU requests lab 250m, stac-fastapi 30m, auth-proxy 50m, tipg 20m; comment points at the verified evidence | `ac03acf` |
| 9 | auth / apis A2: the token collision | README "token once, then the cookie" recipe (no code fix exists, see below) | `ac03acf` |
| 10 | notebooks (a)(c)(e) + apis A3/A5/A6 | The 38 tested edits from `checks/notebooks/fixes.py` applied to `docs/`, plus `maxsize` → `max_size` in 04[23,25,27,29]. Each notebook keeps its own JSON style (detected by an exact round-trip: indent 1, sorted keys except 06, ASCII escaping as found) | `caac1d9` |
| 11 | notebooks (e): 9 of 100 default points give 0 Sentinel-2 items | Dropped from `random_land_points` (91 left; `points.02-default` PASS, 0 of 91 empty) | `caac1d9` |
| 12 | notebooks prerequisite: the edits drop the `.replace()` fallbacks | Repo `docker-compose.yml` sets the six `*_BROWSER_URL` variables and drops `STAC_BROWSER_ENDPOINT`/`STAC_MANAGER_ENDPOINT`. Landed in the same commit as the notebook edits | `caac1d9` |
| 13 | notebooks: the PR #35 chart sets the old name | `jupyter.yaml`: `STAC_BROWSER_ENDPOINT` → `STAC_BROWSER_URL` (rename only; source-checked, not rendered or deployed) | `caac1d9` |
| 14 | browser-apps: a token fragment in the old screenshot in `95823c1` | Local secrets rotated (`rm .env && ./gen-env.sh`, stack recreated), so the fragment no longer matches anything. The blob is still in history (see "Not applied") | n/a (gitignored) |

### Verified directly after the recreate (in the Lab netns)

```
POST /stac/collections/ 307 http://localhost:18888/stac/collections
api.html 200 ['/stac/api']
queryables $id http://localhost:18888/stac/queryables
glad links: items, parent, root, self (all http://localhost:18888/stac/...), license, cite-as, queryables (own)
listeners: 127.0.0.1 on 5432, 8080-8086; 0.0.0.0 only on 18888
stac-manager bundle: scope:"openid profile email offline_access stac:write"
```

## Check changes (the fixes changed what "correct" means)

- **auth/offpod.py, build/offpod.py:** a refused connection is now the pass. `db.password-required-off-pod` became `db.off-pod`: PASS if unreachable, or, if it ever answers, the password must still hold.
- **auth/inpod.py:** the live login cookie must carry `SameSite=Lax` and expire within 2 days, for both token and password logins. The `bindfix.*`/`cookiefix.*` throwaway proofs (`bindprobe.py`, `cookieprobe.py`, `cookie_options.py`) were removed: they proved proposals that are now live, and `sockets.*`, `offpod.*` and `cookie.*` check the real stack. This is the only verification code removed. Restore it from `513b999` if wanted.
- **apis.py:** the `*-like-notebook-0X` checks send what the edited notebooks send (`Z` datetimes, `LIKE '<user>-%'`, `b1/b2`, `max_size`). The stac-auth-proxy encoding bug keeps its own `upstream.*` lines, which still FAIL.
- **browser-apps:** with both fixes deployed, the in-browser simulations of the two stac-manager fixes collided with the as-deployed create. The first re-run gave `manager.create-with-fixes` TimeoutError: the collection already existed. The checks now create, edit and delete one collection through stac-manager as deployed. Screenshots were renumbered and stale ones removed. "Failed to fetch" console lines from fetches the reload aborts are classified.
- **notebooks:** the old `asis/participant/zeropoint/fixed` phases tested pre-edit text that no longer exists. The `docs` phase runs `docs/` as committed and first checks that all 38 edits are still in place. `compose_env.py` now parses the repo's `docker-compose.yml` instead of a hard-coded copy.
- **frontdoor-own:** the A/B NetworkPolicy control used to expect `5432`/`8084` open without the policy, which loopback now prevents. It uses `18888`, and a new `loopback.without-policy` line shows that only `:18888` answers on the pod IP even with no policy.

## Re-run details (trimmed raw output)

Commands, from `spike/`. Raw logs are in `evidence/.fix-<topic>.log` (gitignored).

```sh
docker compose -p eoapi-spike -f compose.participant.yml up -d --build --wait --force-recreate -V
checks/build/run.sh; checks/apis/run.sh; checks/auth/run.sh; checks/browser-apps/run.sh
checks/notebooks/run.sh; checks/footprint/run.sh postfix
docker start eoapi-spike-control-plane    # the kind node had exited (137) about 2 h earlier
kind export kubeconfig --name eoapi-spike --kubeconfig .kind-kubeconfig
kind load docker-image --name eoapi-spike eoapi-spike-lab:latest eoapi-spike-db:latest
helm --kubeconfig .kind-kubeconfig --kube-context kind-eoapi-spike -n spike-own upgrade spike chart --reset-values --wait
checks/frontdoor-own/run.sh
```

```
# build
PASS isolation.backends-unreachable-off-pod — nothing but the Lab answers
PASS db.off-pod — not reachable from another netns (listen_addresses=127.0.0.1)
FAIL proxy.token-not-echoed — Lab token appears in response body of: ['stac/collections']
# apis
PASS stac.api-docs — 200; Swagger UI loads its spec from ['/stac/api']
PASS stac.collection.no-foreign-api-links — glad: 0 links with API rels point at another deployment
PASS stac.datetime-like-notebook-03 — GET /search datetime=...Z/..: {'lab': 200, '8084': 200, '8081 direct': 200}
PASS raster.s2.ndvi-tile-like-notebook-04 — '(b1 - b2) / (b1 + b2)': 200 image/png; old asset-name expression: 400
FAIL stac.lab-token-in-query — /stac/search and /items 500 with ?token=<LAB_TOKEN>
FAIL stac.pystac-client.token-parameter — parameters={'token': ...}: POST 5 items, GET APIError 500
FAIL upstream.stac-auth-proxy.query-encoding.plus — +00:00: lab 400, 8084 400, 8081 direct 200
FAIL upstream.stac-auth-proxy.query-encoding.percent — '%bal%', '%c1-l2a%': lab 0 vs direct 1
# auth
PASS sockets.127.0.0.1:{5432,8080..8086} — loopback only; sockets.0.0.0.0:18888 — the front door
PASS offpod.tcp-reachable — only the Lab answers
PASS offpod.oidc-mint-direct / write-via-auth-proxy / write-stac-fastapi-no-token — connection refused: loopback bind
PASS cookie.token-login.xfp-https — flags=['Expires=+2.0d', 'HttpOnly', 'Path=/', 'SameSite=Lax', 'Secure']
FAIL laptop.pystac-client.parameters-token.GET / laptop.stac.get-with-lab-token / laptop.token-echo /
     laptop.stac.lab-token-in-error-log — the ?token= collision (README recipe)
# browser-apps
PASS stac.trailing-slash-redirect-keeps-prefix — POST :8084/stac/collections/ -> 307 Location=http://localhost:18888/stac/collections
PASS manager.oidc-login — scope='openid profile email offline_access stac:write'
PASS manager.create-as-deployed — POST /stac/collections/ -> 307 | POST /stac/collections -> 201; exists=True
PASS manager.edit-as-deployed — PUT /stac/collections/spike-browser-apps-test -> 200 (Bearer=True)
PASS manager.lab-token-not-on-screen — no screenshot showed the Lab token
PASS browser.console-and-network — 147 entries, all classified
FAIL manager.delete — Options > Delete sends no DELETE (upstream <DeleteMenuItem /> has no onClick)
# notebooks
PASS fixes.* — 38/38 edits in place in docs/
PASS nb.docs.{00..05,0608-links} and nb.writes.{06,07,08} — 0 errored or silently failed cells
PASS tile.docs.04[9,14,17,29,31] and 05[25,27] — 200 (S2 z8 8-11 s cold), 204 for the empty glad centre tile
PASS compose-env.committed — repo docker-compose.yml: 7/7 notebook URLs open from a laptop
PASS points.02-default — 91 default points: 0 give 0 items
PASS md.docs — 0 clickable localhost links in the markdown of 9 notebooks
PASS audit.clean — only spike-notebooks-sentinel-2-c1-l2a left (by design); 0 orphan items
FAIL upstream.stac-auth-proxy.query-encoding.{items,search} — +00:00 -> 400 through the proxy
# footprint (results/postfix)
PASS plan.participant-under-3.5GiB-k8s-estimate — 2.40 GiB busiest moment (ESTIMATE)
PASS chart.requests-cover-steady / chart.limits-cover-peaks — with the new chart values
# frontdoor-own (kind)
PASS netpol.u02-to-u01-blocked — all 9 ports timeout
PASS netpol.control.without-policy — policy deleted: 5432..8086 closed, 18888 open
PASS loopback.without-policy — policy deleted: only :18888 open on u01's pod IP
```

### Iterations

1. **First re-run.**
   - auth `offpod.write-*` crashed with NameError: the `@check` decorator runs at definition, before the helpers it called existed. Fixed by moving the bodies under an inner `@refused` decorator.
   - browser-apps: the simulation collision described above.
   - Both were fixed and re-run.
2. **Second re-run.** The table above. No fix was left to try for the remaining FAILs (see below).

Also found on the way:
- `up --force-recreate` keeps the pgstac image's **anonymous** data volume, so the first recreate still served the old glad links. `-V` (`--renew-anon-volumes`) is needed. The README now says so.
- With `--root-path /stac`, stac-fastapi's direct port `:8081` still routes unprefixed requests, but the links it generates now read `http://localhost:8081/stac/...`, and those 404 if followed on `:8081`. Nothing uses `:8081` except debugging (the notebooks and stac-auth-proxy use `:8084/stac`), so this is accepted.
- Cold world-view glad tile: the first browser-apps re-run measured **109.8 s** cold (FAIL), and the second 0.8 s warm (PASS). This is F5, unchanged.

## Not applied

| Problem | Why not | Fallback / next step |
|---|---|---|
| `?token=` collides with pgstac's pagination `token` (500s, token in the stac-fastapi log, echoed in links and tile URLs) | jupyter-server-proxy has no hook to strip a query parameter, and Jupyter's login parameter name is fixed | README recipe: token once, then the cookie. Use it in a future `deploy.sh verify` and the participant laptop page |
| stac-auth-proxy v1.2.0 `dict_to_query_string` does not percent-encode (`+` becomes a space, `%xx` is decoded twice) | Upstream bug | The notebooks avoid it (`Z`, `LIKE '<user>-%'`). Report upstream: `urlencode(..., quote_via=quote)`; check a newer release first. Not security-sensitive |
| stac-manager 1.0.3 Delete is a no-op | Upstream: `<DeleteMenuItem />` has no onClick; no newer release | Workshop text: delete from a notebook (ch. 6 DELETE with a `stac:write` token). Its own subdomain would not help: this is a UI bug, not a routing one |
| Cold world-view glad mosaic takes 68-111 s (`MOSAIC_CONCURRENCY=1`, 100 COGs at z0) | Remedies untested; not a front-door issue | Try a higher `MOSAIC_CONCURRENCY`, opening the notebook map at a higher zoom, or pre-warming at pod start |
| Old screenshot with 35 chars of the then-current Lab token in commit `95823c1` | Rewriting branch history is Loïc's call | The token is rotated, so the fragment is dead. Before any push, drop or replace that blob (rebase `95823c1`) |
| `SWAGGER_UI_INIT_OAUTH` on stac-auth-proxy (apis A1) | Not needed: `--root-path` already fixes `/stac/api.html` | none |
| https for the PR #35 chart's `STAC_BROWSER_URL` | Production chart; not renderable or testable here | Loïc: set `https://browser.<base>` if that host has TLS |
| Capacity: real DaemonSet requests, b3-16/32 allocatable, multi-hour soak | Needs the "labs" cluster (out of bounds) or hours of runtime | footprint.md: plan 1 pod per b3-8, 4 per b3-16; soak before trimming memory |
| Pre-puller, stac-manager value toggle | Phase 2 chart work, not a correctness fix | footprint.md |

## State left behind

- The compose stack is **running**, recreated with the fixes and a fresh DB. It holds the baked data plus `spike-notebooks-sentinel-2-c1-l2a` (by design, read by 03/04) and one registered pgstac search from notebook 04.
- The kind node was found **Exited (137)**, restarted, upgraded to revision 15 and the checks re-run. It is **left running**: the two pods are 9/9, 0 restarts. Its kubeconfig was refreshed in `spike/.kind-kubeconfig`.
- `spike/.env` was regenerated (new Lab password, token and DB password). Read them with `grep LAB_ spike/.env`.
- Commits are unsigned (`-c commit.gpgsign=false`), like every other spike commit: the sandbox cannot reach the 1Password signing agent. Nothing was pushed.
