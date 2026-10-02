# Notebooks: docs/00–08 run headless in one participant's stack

> **Superseded.** This is the pre-fix run of 2026-10-01. The current stack is described by `fix.md` (the fixes and a re-run of every topic) and `verify.md` (the independent re-run). The method and the reproduce steps below still apply.

*2026-10-01 · local compose stack `eoapi-spike` (`spike/compose.participant.yml`), Lab image conda env `eoapi-workshop`, nbconvert 7.17.1 · reproducible via `spike/checks/notebooks/run.sh`*

**Resumed run.** The first attempt was cut off by a usage limit; its files were committed unverified in `95823c1`. Everything below was re-executed from scratch: run 1 (`./run.sh`, all phases, 17:56–18:45Z), then two read-only re-reports (run 3 is the one quoted in full). It replaces the WIP version of this file. Where a number differs from the WIP, that is said.

## Result

- **With the proposed edits, every notebook runs clean and every link resolves through the Lab.**
  - The `fixed` phase runs 00, 02, 03, 04, 05 and the link cells of 06/07/08 with **0 errored cells**.
  - All **29 browser-facing URLs** they embed, print or link answer **200 through the Lab** with a logged-in session.
  - Swagger specs and map tilejsons load, every tile URL is on the Lab origin, and **7/7 tiles** return 200 or 204.
  - All **38 edits** apply to the current `docs/` with no drift. On a scratch copy the diff is 108 insertions and 119 deletions, and it touches only cell sources.
- **The edits need one companion change, which the WIP missed.** They drop the `.replace("tipg", "localhost")` fallbacks, so the repo's `docker-compose.yml` must set the `*_BROWSER_URL` contract.
  - With its jupyterhub env as committed, **0/7** of the edited cells' URLs open from a laptop: `http://stac-auth-proxy:8000/api.html`, `http://tipg:8083/…`, and `None/` for 08[10].
  - With six added lines, **7/7** open (check `compose-env.*`, `compose_env.py`).
  - The unmodified notebooks work on compose today, so the edits and the compose lines must land in the same commit.
- **Unmodified, 06, 07 and 08 pass every assertion in the per-user stack.** That is 16, 14 and 7 `assert` statements, with 0 errored cells: transactions, scopes and row-level auth through stac-auth-proxy plus this pod's mock-oidc. Only the URLs they print or embed point at compose ports.
- **No path-prefix/proxy problem (b) shows up in any notebook output.**
  - Every IFrame target loads under its prefix.
  - No HTML page references localhost outside its own `/<prefix>/`.
  - No backend sends `X-Frame-Options: DENY` or `frame-ancestors 'none'`.
  - Every localhost URL in API JSON starts with a contract endpoint, so `to_browser()` is a valid prefix swap.
- **No external-data failure (d) in any notebook.** S3 (sentinel-cogs, MAAP), earth-search and roda were reachable from the containers. Earth-search dropped one connection in run 1's 100-point count, so `points.py` now retries once.
- **Three pre-existing bugs (e) break cells regardless of the redesign.** Each reproduces directly against the backend or the data source, and compose uses the same images and config:
  1. **stac-auth-proxy 1.2.0 mangles `+` in query strings** when the row-level filter is on. 03[23] fails silently and 03[28] raises; [30] and [32] cascade.
  2. **titiler-pgstac 3.2.0 rejects asset names in `expression`.** 04[17]'s NDVI map loads, but every tile is a 400.
  3. **9 of the 100 default points in `workshop_setup.random_land_points` return 0 Sentinel-2 items**: exactly the 9 south of 85°S. A participant who draws one gets `IndexError` at 02[16], with [24] and [26] cascading. That is a 9 % chance per participant.
- **The per-user simplification (c) is real.** Run headless, nobody types a username.
  - 03 filters `id LIKE '%%'` and picks `glad-global-forest-change-1.11`.
  - 04 asks for `-sentinel-2-c1-l2a`.
  - That gives 6 errored or silent cells in 03, 4 in 04, and a 404 map. `collection_id()` removes the widget.
- **`STAC_AUTH_PROXY_ENDPOINT` is not needed.** `docs/stac_auth.py:20` prefers `STAC_API_ENDPOINT`. With the legacy variable unset, `require_local_auth_stack()`, a minted token and an authenticated `GET /collections` all work (200; check `probe.stac-auth-without-legacy-env`, added to `probes.py` after run 3, output below).

**Counts (run 3): 110 PASS, 48 FAIL, 4 BLOCKED.** Run 1 had 185 PASS, because it also prints the 38 `fixes.*`, 17 `harness.*` and 18 `exec.*` lines.
- **Every FAIL is classified, and 0 are in the `fixed` phase.**
  - 17 cell failures and 4 per-notebook summaries in the unmodified notebooks.
  - 11 `md.orig` lines: 10 clickable compose-port links (8 in 00[19], 2 in 08[9]) plus their summary.
  - 10 URL lines, 1 tile line and 1 prefix line for 08's hard-coded `http://localhost:8080`.
  - 3 probe lines and 1 points line, which reproduce the (e) bugs on purpose.
  - 1 `compose-env.today`.

### What changed from the WIP

| WIP said | Verified |
|---|---|
| 9/100 default points give 0 items | Confirmed, after a retry. Run 1 saw 8 plus 1 connection error; a re-query of `(82.46, -86.63)` gave 0, and `points.py` now retries. All 9 are the points south of 85°S. |
| Edits complete | **Incomplete:** they need `*_BROWSER_URL` in the repo compose (above). |
| Fixed 03 takes 27–35 s | 6 s (with 02 pinned to one point, 1,136 items). |
| Cold tile 4–16 s | 8–13 s for Sentinel-2 mosaic tiles at z8. The footprint tester's titiler load container was running at the same time. |
| — | New `audit` phase: after 06–08 only 02's collection is left, with 0 items lacking a collection. |

## How to reproduce

```sh
cd spike && docker compose -p eoapi-spike -f compose.participant.yml up -d --wait   # stack up (README)
checks/notebooks/run.sh                       # all phases (~5 min + tiles)
PHASES=audit checks/notebooks/run.sh          # read-only: audit + probes + compose-env + points + report
POINTS=0 PHASES= checks/notebooks/run.sh      # report only, on the last executed copies
```

`run.sh` copies the scripts into the Lab container and runs them with the image's conda env (`/entrypoint.sh python …`):
- **`nbrun.py`** copies `/home/jovyan/docs` to `/tmp/nbrun-notebooks/<phase>/` and edits only that copy.
  - It runs `jupyter nbconvert --to notebook --execute --allow-errors --ExecutePreprocessor.timeout=600` from the copy's directory, so sibling helpers import.
  - The bind-mounted `docs/` is never written.
- **`report.py`** reads the executed copies.
  - It logs in the way a browser does: one `GET /lab?token=…`, then the cookie. The token is never forwarded to backends (build finding F1).
  - It probes `http://localhost:18888/...` from inside the pod netns, which is the browser's URL.
- **`probes.py`** reproduces the two backend bugs directly.
- **`points.py`** counts earth-search matches for all 100 default points.
- **`compose_env.py`** evaluates the edited cells' URLs under the repo compose env, as committed and with the proposed lines.
- Executed copies are copied back to `spike/checks/notebooks/out/` (gitignored).

### Phases

| Phase | Notebooks | What differs from `docs/` |
|---|---|---|
| `reset` | — | drops this topic's collections from an earlier run (`spike-notebooks-*`, `private-<owner>-spike-notebooks*`) |
| `asis` | 00 01 03 04 05 | nothing: no username typed, which is what headless execution sees |
| `participant` | 02 03 04 | harness: the typed username is `spike-notebooks`; 02's point pinned to the default `(148.09, -37.47)` (1,136 items); 02[24]'s DELETE scoped to the collection |
| `zeropoint` | 02 | harness: username `spike-notebooks-zero`, default point `(25.5, -89.99)`; its collection is dropped afterwards |
| `fixed` | 00 02 03 04 05 + `0608-links` (06[2], 07[7], 08[10] alone, no writes) | the proposed edits (`fixes.py`), `WORKSHOP_USER=spike-notebooks`, same pinned point |
| `writes` | 06 07 08, **run last and once** | harness: ids under `spike-notebooks` (below) |
| `audit` | — | read-only: what is left under our prefix |

Each harness substitution asserts that its original text is still there (17/17 PASS in run 1).

### STAC data this run created

| Notebook | Original ids | Ids used (run 1) | Fate |
|---|---|---|---|
| 02 | `<username>-sentinel-2-c1-l2a` | `spike-notebooks-sentinel-2-c1-l2a` (1,136 items); `spike-notebooks-zero-sentinel-2-c1-l2a` (0 items) | the first **left in place** (03/04 and `probes.py` read it; `reset` drops it); the second dropped by the `zeropoint` phase |
| 04[12] | titiler search registration | pgstac `searches` row `893d5f7bff6e5c45dbf36850c844bf26` | left (hash-keyed, harmless) |
| 06 | `tx-workshop-<run_id>`, `tx-item-<run_id>` | `spike-notebooks-tx-1790878508`, `spike-notebooks-tx-item-1790878508` | deleted by 06 itself |
| 07 | `public-demo-<run_id>`, `private-alice-<run_id>`, `private-bob-<run_id>` | `spike-notebooks-public-1790878510`, `private-alice-spike-notebooks-1790878510`, `private-bob-spike-notebooks-1790878510` | deleted by 07 itself |
| 08 | `public-demo`, `private-alice-notebook`, `private-bob-notebook` | `spike-notebooks-public-demo`, `private-alice-spike-notebooks`, `private-bob-spike-notebooks` | deleted by 08 itself |

- **Private ids must keep the `private-<owner>-` prefix** that `TenantFilter` keys on, so the `spike-notebooks` marker comes after it.
- Notebook 08's own ids appear only in its markdown in the executed copy. No code cell used them.
- `reset` dropped the WIP run's leftover `spike-notebooks-sentinel-2-c1-l2a` (1,136 items) before run 1.
- After run 1 the catalog held `glad-global-forest-change-1.11` (100 items) and `spike-notebooks-sentinel-2-c1-l2a` (1,136 items), with 0 orphan items (`audit.clean`).

## Errored or silently failing cells (unmodified notebooks)

| Cell | Phase | Error (first line) | Class | Cause / fix |
|---|---|---|---|---|
| 03[21] | asis | `IndexError: list index out of range` | (c) | empty username → `LIKE '%%'` picked `glad-global-forest-change-1.11` (03[15] output), "found 0 items" ≥ 2025-01-04 → `collection_id()` |
| 03[26] | asis | `IndexError` | (c) | same wrong collection |
| 03[23] | asis, participant | silent: `"detail": "Invalid RFC3339 datetime."` printed | (e) | stac-auth-proxy query rebuild (below); send `…Z` instead of `+00:00` |
| 03[28] | asis, participant | `KeyError: 'features'` | (e) | same; the 400 body has no `features` |
| 03[30], 03[32] | asis, participant | `KeyError: 'features'`, `NameError: name 'item_id' is not defined` | (e) | cascade from 03[28] |
| 04[7] | asis | silent: ``CollectionId `-sentinel-2-c1-l2a` not found`` | (c) | empty username → `collection_id()` |
| 04[12] | asis | `KeyError: 'extent'` | (c) | cascade from 04[7] |
| 04[14], 04[17] | asis | `NameError` (`search_response`, `search_id`) | (c) | cascade |
| 04[17] tiles | participant | map and tilejson 200; **every tile 400** `Invalid band/asset name 'nir'` | (e) | titiler-pgstac 3.2.0 / rio-tiler 9.4.4 (below); `(b1 - b2) / (b1 + b2)` |
| 02[16] | zeropoint | `IndexError: list index out of range` | (e) | default point `(25.5, -89.99)` → earth-search 0 items → `items[0]` |
| 02[24], 02[26] | zeropoint | `IndexError` | (e) | cascade: `items[-1]` of an empty list |

No cell errored in 00, 01, 05, 06, 07 or 08, or in 02 at a default point with data.

### (e) stac-auth-proxy 1.2.0 re-sends the query string unencoded

- **Mechanism.** With `ITEMS_FILTER_CLS` set (chapter 7's row-level filter), the proxy decodes the query and rebuilds it with `utils/filters.py: dict_to_query_string`. That function joins `f"{key}={val}"` **without percent-encoding**.
  - So `%2B00:00` reaches stac-fastapi as a raw `+`, which is read as a space.
  - Source read in the running container (`eoapi-spike-stac-auth-proxy-1`).
- **Not caused by the redesign.** The repo's `docker-compose.yml:96,117-120` uses the same image and the same filter env as `spike/compose.participant.yml:103,124-127`.
- **Probe** (`probes.py`; httpx sends `%2B` correctly encoded):

```
proxy  /collections/glad…/items datetime=2000-01-01T00:00:00+00:00/..  -> 400 {"detail": "Invalid RFC3339 datetime."}
proxy  /search                  datetime=…+00:00/..                    -> 400 {"detail": "Invalid RFC3339 datetime."}
direct :8081 (stac-fastapi) items and /search, same datetime           -> 200
proxy  items and /search, datetime=2000-01-01T00:00:00Z/..             -> 200
```

- **pystac-client is not affected:** it formats datetimes with `Z`, which is why 03[21] works once a username is set.
- **Fixes:**
  - Notebook workaround (tested in `fixed`): `strftime("%Y-%m-%dT%H:%M:%SZ")` in 03[23] and 03[28].
  - Real fix: upstream, URL-encode the values in `dict_to_query_string`. A newer release was not checked.

### (e) titiler-pgstac 3.2.0 expression syntax

- **Cause.** rio-tiler 9.4.4, in the running titiler image, sets `img.band_names = [f"b{ix + 1}" …]` before applying the expression (`rio_tiler/io/base.py:707` and 14 siblings). Asset names no longer resolve.
- **Probe** (`probes.py`, tile `8/233/156` of `spike-notebooks-sentinel-2-c1-l2a`):

```
assets=nir&assets=red&asset_as_band=True  expression=(nir - red) / (nir + red) -> 400 {"detail":"Invalid band/asset name 'nir'"}
assets=nir&assets=red&asset_as_band=True  expression=(b1 - b2) / (b1 + b2)     -> 200 image/jpeg
```

### (e) default points with no Sentinel-2 data

- **What `points.py` does.** It sends 02[14]'s exact search (bbox ±2°, 2025-01-01..04-18) for all 100 points and asks for the match count.
- **Result.** 9 points return 0 items, and they are exactly the 9 with latitude < −85°: `(-116.36, -86.78) (-111.18, -85.34) (-92.51, -86.57) (-92.31, -88.19) (-61.95, -88.61) (1.65, -89.03) (25.5, -89.99) (82.46, -86.63) (118.24, -88.41)`.
- **Volume per participant:** min 0, p10 14, median 1,144, p90 1,476, max 2,575 items. The capacity angle belongs to the footprint topic.
- **Fix:** drop those 9 points from `random_land_points` in `docs/workshop_setup.py`.

## Browser-facing URLs

| Where | Unmodified | Class | With the fix (`fixed` phase) |
|---|---|---|---|
| 00[19] markdown | 8 autolinks `<http://localhost:80xx>` (compose ports) | (a) | plain "port 8084" text; the new 00[23] `show_links()` renders 5 links, all 200 |
| 02[22] IFrame | `https://radiantearth.github.io/stac-browser/#/external/http://localhost:8084/stac/collections/…` (reads `STAC_BROWSER_ENDPOINT`, renamed `STAC_BROWSER_URL`) | (a) | `http://localhost:18888/browser/collections/spike-notebooks-sentinel-2-c1-l2a` → 200 |
| 03[2] print | `http://localhost:8084/stac` (kernel-side; JupyterLab linkifies it) | (a) | `http://localhost:18888/stac` → 200 |
| 03[11], 03[34] IFrame | `/stac/api.html` → 200, openapi 200 | — | same, via `endpoints()` |
| 04[3] IFrame | `/raster/api.html` → 200, openapi 200 | — | same, via `endpoints()` |
| 04[9], [14], [17] maps | 200, tiles on the Lab origin; tiles 200 except [17] (400, (e)) | asis (c): 404 | all tiles 200 |
| 04[29], [31] maps | 200 via `.replace(server, browser)`; [31]'s center tile is 204 (no glad item there), a tile inside an item is 200 | — | same via `to_browser()` |
| 05[16], [18], [25], [27] | 200; vector tiles 200 | — | same via `to_browser()` |
| 06[2], 07[7] prints | `http://localhost:8084/stac`, `http://localhost:8085/oidc` | (a) | `/stac`, `/oidc` on the Lab → 200 |
| 08[10] IFrame | `http://localhost:8080` (hard-coded) | (a) | `/browser/` → 200, plus a printed Step-5 link `/browser/collections/private-alice-notebook` → 200 (nginx index) |
| 08[9] markdown | `<http://localhost:8080>`, `<…/collections/private-alice-notebook>` | (a) | reworded to "the link the cell below prints" |
| 08[4], 08[17] markdown | "redirect URI is `<origin>/auth`" | (b) | `<origin><pathPrefix>auth`, i.e. `<Lab>/browser/auth` (STAC Browser 5.1.0 `src/auth/oidc.js:38-41`: `window.location.origin + this.router.resolve(appPath).href`, router base = `pathPrefix`) |
| 08[11] markdown | "clear site data for `localhost:8080`" | (a) | same origin as the Lab now: clearing it logs out of the Lab, so prefer a private window |

Other observations:
- **02[22]'s `/#/collections/<id>` only ever worked on the public browser.** STAC Browser 5.1.0 defaults to `historyMode: "history"` (`config.js:46`; `src/init.js:18` `createWebHistory(pathPrefix)`), and neither compose sets `SB_historyMode`. Checked in source, not in a real browser.
- **08[2] prints the auth scheme the proxy advertises:** `openIdConnectUrl: http://localhost:18888/oidc/.well-known/openid-configuration`, which is same-origin and is what STAC Browser needs.
- **Kernel-side links in printed API JSON stay dead in the browser.** In the `fixed` phase, 03 prints 15 such `http://localhost:8084/stac/…` links, 05 prints 13 and 04 prints 5. stac-fastapi builds them from the kernel's request host. JupyterLab linkifies them, but only port 18888 is published. This is accepted, not fixed: they are data in a JSON dump, and `to_browser()` maps any of them.
- **The ch. 6–8 notes saying "will not run against the hosted workshop" are now false.** The edits reword them.

## Proposed edits (exact tested sources in `spike/checks/notebooks/fixes.py`)

Apply them to the repo mechanically, from `spike/checks/notebooks/`:

```sh
python3 -B -c 'import nbrun; print(*nbrun.apply_fixes("../../../docs", links=False), sep="\n")'
```

- Each edit checks its `expect` text first and prints `FAIL fixes.<nb>[i] — cell drifted` instead of overwriting a changed cell.
- Notebooks are written the way Jupyter writes them, keeping 06/07's escaped non-ASCII.
- **Land it in the same commit as the compose lines below.**

| Notebook | Cells | Class | Change |
|---|---|---|---|
| 00 | md 19, code 23 | (a) | compose ports as plain text; empty last cell → `show_links()` |
| 02 | md 0, 3; code 4, 6 | (c) | drop the username widget; `collection_id = workshop_setup.collection_id()`; description from `workshop_user()` |
| 02 | code 22 | (a) | `endpoints()['browser']['browser'] + '/collections/<id>'`, public-browser fallback kept |
| 02 | code 24 | hygiene (plan §3) | `DELETE … WHERE id = %s AND collection = %s` (parameterised) |
| 03 | md 1, 13; code 14, 15, 17 | (c) | no widget; `filter=f"id LIKE '{workshop_user()}-%'"`; pick `collection_id()` from the results |
| 03 | code 2, 11 | (a) | print `to_browser(stac_api_endpoint)`; `endpoints()["stac"]["browser"]` |
| 03 | code 23, 28 | (e) | datetime with `Z` (proxy bug) |
| 04 | md 0; code 1, 5 | (c) | no widget; `workshop_setup.collection_id()` |
| 04 | code 3, 29, 31 | (a) | `endpoints()` and `to_browser()` instead of `os.getenv(...) or .replace(...)` |
| 04 | code 17 | (e) | `(b1 - b2) / (b1 + b2)` |
| 05 | code 3, 16, 25, 27 | (a) | `endpoints()` and `to_browser()`. These cells are not broken here, because the spike sets `*_BROWSER_URL`; the edit removes the `.replace` heuristic the contract replaces |
| 06 | md 0; code 2 | (a) | note reworded; print `to_browser()` URLs |
| 07 | md 0; code 7 | (a) | same |
| 08 | md 0, 4, 9, 11, 17; code 10 | (a)/(b) | IFrame and links from `endpoints()`; redirect URI with the path prefix |

Companion changes outside `docs/*.ipynb`:
- **`docker-compose.yml` jupyterhub env:** add `STAC_API_BROWSER_URL=http://localhost:8084`, `TITILER_BROWSER_URL=http://localhost:8082`, `TIPG_BROWSER_URL=http://localhost:8083`, `MOCK_OIDC_BROWSER_URL=http://localhost:8085`, `STAC_BROWSER_URL=http://localhost:8080` and `STAC_MANAGER_URL=http://localhost:8086`. Drop `STAC_BROWSER_ENDPOINT` and `STAC_MANAGER_ENDPOINT`, which nothing in `docs/` reads after the edits. Tested by `compose-env.proposed`.
- **`docs/workshop_setup.py`:** drop the 9 points south of 85°S from `random_land_points`.
- **`spike/compose.participant.yml:51`:** drop `STAC_AUTH_PROXY_ENDPOINT`, which is unused (tested above).

Kept on purpose:
- **07/08's alice/bob personas and fixed demo ids.** Row-level auth needs several identities within one stack, and in a per-user stack nobody else can clobber them.
- **The compose YAML in 08[4].** It is a code block documenting compose, not a link.

## Not tested (BLOCKED in `run.sh`)

- **Rendering.** Whether JupyterLab paints each IFrame. HTTP 200, sub-resources and framing headers were checked, not pixels.
- **STAC Browser's SPA route `/browser/collections/<id>`.** nginx returns `index.html` (200); the route itself runs in JS. The browser-apps topic drives a real browser.
- **The ch. 8 PKCE login** inside the Lab, in an IFrame or a tab.
- **TLS:** mixed content with an https Lab.
- **Execution on the real compose stack and on 2i2c.** The compose path was checked by evaluating the URL expressions under its env (`compose_env.py`), not by running the notebooks there.

## Raw output (lines trimmed to 200 characters)

### Run 1: `checks/notebooks/run.sh` (all phases), setup and execution lines

```
PASS reset.drop — spike-notebooks-sentinel-2-c1-l2a (1136 items)
PASS reset.clean — 1 dropped, 0 left
PASS exec.asis.00-introduction — nbconvert rc=0 in 2s []
PASS exec.asis.01-stac_metadata — nbconvert rc=0 in 14s []
PASS exec.asis.03-stac_fastapi_pgstac — nbconvert rc=0 in 2s []
PASS exec.asis.04-titiler_pgstac — nbconvert rc=0 in 3s []
PASS exec.asis.05-tipg — nbconvert rc=0 in 1s []
PASS harness.participant.02-database[4] — value=Haikunator().haikunate() -> value="spike-notebooks"
PASS harness.participant.02-database[2] — default_lon, default_lat = get_random_point() -> default_lon, default_lat = 148.09, -37.47  # harness: a default point, 1,136 items
PASS harness.participant.02-database[24] — where id = '{items[-1].id}'; -> where id = '{items[-1].id}' AND collection = '{my_collection.id}';
PASS harness.participant.03-stac_fastapi_pgstac[14] — value=None -> value="spike-notebooks"
PASS harness.participant.04-titiler_pgstac[1] — value=None -> value="spike-notebooks"
PASS exec.participant.02-database — nbconvert rc=0 in 16s []
PASS exec.participant.03-stac_fastapi_pgstac — nbconvert rc=0 in 6s []
PASS exec.participant.04-titiler_pgstac — nbconvert rc=0 in 1s []
PASS harness.zeropoint.02-database[4] — value=Haikunator().haikunate() -> value="spike-notebooks-zero"
PASS harness.zeropoint.02-database[2] — default_lon, default_lat = get_random_point() -> default_lon, default_lat = 25.5, -89.99  # harness: a default point with 0 items
PASS harness.zeropoint.02-database[24] — where id = '{items[-1].id}'; -> where id = '{items[-1].id}' AND collection = '{my_collection.id}';
PASS exec.zeropoint.02-database — nbconvert rc=0 in 3s []
PASS zeropoint.drop — spike-notebooks-zero-sentinel-2-c1-l2a (0 items)
PASS zeropoint.clean — 1 dropped, 0 left
PASS harness.fixed.02-database[2] — default_lon, default_lat = get_random_point() -> default_lon, default_lat = 148.09, -37.47  # harness: a default point, 1,136 items
PASS exec.fixed.00-introduction — nbconvert rc=0 in 2s []
PASS exec.fixed.02-database — nbconvert rc=0 in 17s []
PASS exec.fixed.03-stac_fastapi_pgstac — nbconvert rc=0 in 6s []
PASS exec.fixed.04-titiler_pgstac — nbconvert rc=0 in 1s []
PASS exec.fixed.05-tipg — nbconvert rc=0 in 1s []
PASS exec.fixed.0608-links — nbconvert rc=0 in 1s []
PASS harness.writes.06-stac_transactions_auth[4] — f"tx-workshop-{run_id}" -> f"spike-notebooks-tx-{run_id}"
PASS harness.writes.06-stac_transactions_auth[4] — f"tx-item-{run_id}" -> f"spike-notebooks-tx-item-{run_id}"
PASS harness.writes.07-row_level_auth[9] — f"public-demo-{run_id}" -> f"spike-notebooks-public-{run_id}"
PASS harness.writes.07-row_level_auth[9] — f"private-alice-{run_id}" -> f"private-alice-spike-notebooks-{run_id}"
PASS harness.writes.07-row_level_auth[9] — f"private-bob-{run_id}" -> f"private-bob-spike-notebooks-{run_id}"
PASS harness.writes.08-stac_browser_auth[6] — "public-demo" -> "spike-notebooks-public-demo"
PASS harness.writes.08-stac_browser_auth[6] — "private-alice-notebook" -> "private-alice-spike-notebooks"
PASS harness.writes.08-stac_browser_auth[6] — "private-bob-notebook" -> "private-bob-spike-notebooks"
PASS exec.writes.06-stac_transactions_auth — nbconvert rc=0 in 1s []
PASS exec.writes.07-row_level_auth — nbconvert rc=0 in 2s []
PASS exec.writes.08-stac_browser_auth — nbconvert rc=0 in 2s []
(38 `PASS fixes.<nb>[i]` lines omitted: every proposed edit applied without drift)
```

### Run 3: `PHASES=audit checks/notebooks/run.sh` (read-only, over run 1's executed copies)

```
PASS audit.clean — ours left: ['spike-notebooks-sentinel-2-c1-l2a']; unexpected: []; items without a collection: 0
FAIL probe.stac-datetime-plus.proxy.items — GET http://localhost:8084/stac/collections/glad-global-forest-change-1.11/items datetime=2000-01-01T00:00:00+00:00/.. (sent as datetime=2000-01-01T00%3A00%3
FAIL probe.stac-datetime-plus.proxy.search — GET http://localhost:8084/stac/search datetime=2000-01-01T00:00:00+00:00/.. (sent as datetime=2000-01-01T00%3A00%3A00%2B00%3A00%2F..&limit=1&coll) -> 400 {
PASS probe.stac-datetime-plus.direct.items — GET http://localhost:8081/collections/glad-global-forest-change-1.11/items datetime=2000-01-01T00:00:00+00:00/.. (sent as datetime=2000-01-01T00%3A00%3A00%
PASS probe.stac-datetime-plus.direct.search — GET http://localhost:8081/search datetime=2000-01-01T00:00:00+00:00/.. (sent as datetime=2000-01-01T00%3A00%3A00%2B00%3A00%2F..&limit=1&coll) -> 200 {"typ
PASS probe.stac-datetime-Z.proxy.items — GET http://localhost:8084/stac/collections/glad-global-forest-change-1.11/items datetime=2000-01-01T00:00:00Z/.. (sent as datetime=2000-01-01T00%3A00%3A00Z%2F.
PASS probe.stac-datetime-Z.proxy.search — GET http://localhost:8084/stac/search datetime=2000-01-01T00:00:00Z/.. (sent as datetime=2000-01-01T00%3A00%3A00Z%2F..&limit=1&collections=g) -> 200 {"type": 
PASS probe.stac-datetime-Z.direct.items — GET http://localhost:8081/collections/glad-global-forest-change-1.11/items datetime=2000-01-01T00:00:00Z/.. (sent as datetime=2000-01-01T00%3A00%3A00Z%2F..&li
PASS probe.stac-datetime-Z.direct.search — GET http://localhost:8081/search datetime=2000-01-01T00:00:00Z/.. (sent as datetime=2000-01-01T00%3A00%3A00Z%2F..&limit=1&collections=g) -> 200 {"type":"Feat
PASS probe.glad-tile-in-item — hansen-gfc-2023-v1.11-80N-180W bbox [-180, 70, -170, 80]: /collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/6/0/11 -> 200 image/jpeg 670 B in 0.6s 
FAIL probe.titiler-expression-asset-names — /collections/spike-notebooks-sentinel-2-c1-l2a/tiles/WebMercatorQuad/8/233/156 expression=(nir - red) / (nir + red) -> 400 application/json in 1.5s {"detail
PASS probe.titiler-expression-b1-b2 — /collections/spike-notebooks-sentinel-2-c1-l2a/tiles/WebMercatorQuad/8/233/156 expression=(b1 - b2) / (b1 + b2) -> 200 image/jpeg in 7.0s 
FAIL compose-env.today — repo compose jupyterhub env as committed: 0/7 edited-cell URLs open from a laptop; unreachable: {'03[11]': 'http://stac-auth-proxy:8000/api.html', '04[3]': 'http://titiler-pgs
PASS compose-env.proposed — repo compose jupyterhub env + proposed *_BROWSER_URL lines: 7/7 edited-cell URLs open from a laptop; unreachable: {}
FAIL points.02-default — 100 default points: 9 give 0 items [(-116.36, -86.78), (-111.18, -85.34), (-92.51, -86.57), (-92.31, -88.19), (-61.95, -88.61), (1.65, -89.03), (25.5, -89.99), (82.46, -86.63)
PASS points.02-volume — items loaded per participant: min 0, p10 14, median 1144 (e.g. ((148.09, -37.47), 1136)), p90 1476, max 2575 (top 3 [((-48.67, -80.69), 2575), ((-79.02, -78.54), 2521), ((123.2
PASS nb.asis.00-introduction — 1 code cells, 0 errored or silently failed (executed 2026-10-01T17:56Z)
PASS prefix.asis.00-introduction — 0 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.asis.01-stac_metadata — 11 code cells, 0 errored or silently failed (executed 2026-10-01T17:56Z)
PASS prefix.asis.01-stac_metadata — 0 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
FAIL cell.asis.03-stac_fastapi_pgstac[21] — IndexError: list index out of range | (c) per-user simplification: LIKE '%%' picked the wrong collection (no items >= 2025-01-04); username widget is empty 
FAIL cell.asis.03-stac_fastapi_pgstac[23] — silent: "detail": "Invalid RFC3339 datetime." | (e) pre-existing bug: stac-auth-proxy 1.2.0 filter injection (utils/filters.py dict_to_query_string) re-send
FAIL cell.asis.03-stac_fastapi_pgstac[26] — IndexError: list index out of range | (c) per-user simplification: same wrong collection, no items with eo:cloud_cover; username widget is empty when run he
FAIL cell.asis.03-stac_fastapi_pgstac[28] — KeyError: 'features' | (e) pre-existing bug: same proxy bug as [23]: the 400 body has no 'features'
FAIL cell.asis.03-stac_fastapi_pgstac[30] — KeyError: 'features' | (e) pre-existing bug: cascade from [28]
FAIL cell.asis.03-stac_fastapi_pgstac[32] — NameError: name 'item_id' is not defined | (e) pre-existing bug: cascade from [28]
FAIL nb.asis.03-stac_fastapi_pgstac — 15 code cells, 6 errored or silently failed (executed 2026-10-01T17:56Z)
FAIL url.asis.03-stac_fastapi_pgstac[2].printed — http://localhost:8084/stac -> not on the Lab origin (another localhost port: not published, only the Lab is) | (a) URL/env contract: kernel-side URL p
PASS url.asis.03-stac_fastapi_pgstac[11].printed — http://localhost:18888/stac/api.html#/default/Get_Collections_collections_get -> 200 text/html; openapi 200 application/json
PASS url.asis.03-stac_fastapi_pgstac[11].iframe — http://localhost:18888/stac/api.html#/default/Get_Collections_collections_get -> 200 text/html; openapi 200 application/json
PASS url.asis.03-stac_fastapi_pgstac[34].printed — http://localhost:18888/stac/api.html -> 200 text/html; openapi 200 application/json
PASS url.asis.03-stac_fastapi_pgstac[34].iframe — http://localhost:18888/stac/api.html -> 200 text/html; openapi 200 application/json
PASS prefix.asis.03-stac_fastapi_pgstac — 10 distinct localhost URLs in outputs, 7 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
FAIL cell.asis.04-titiler_pgstac[7] — silent: "detail": "CollectionId `-sentinel-2-c1-l2a` not found" | (c) per-user simplification: collection '-sentinel-2-c1-l2a' (empty username) not found; usernam
FAIL cell.asis.04-titiler_pgstac[12] — KeyError: 'extent' | (c) per-user simplification: cascade from [7]: the collection does not exist; username widget is empty when run headless; per-user stack: us
FAIL cell.asis.04-titiler_pgstac[14] — NameError: name 'search_response' is not defined | (c) per-user simplification: cascade from [12]
FAIL cell.asis.04-titiler_pgstac[17] — NameError: name 'search_id' is not defined | (c) per-user simplification: cascade from [12]
FAIL nb.asis.04-titiler_pgstac — 15 code cells, 4 errored or silently failed (executed 2026-10-01T18:13Z)
PASS url.asis.04-titiler_pgstac[3].printed — http://localhost:18888/raster/api.html -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.asis.04-titiler_pgstac[3].iframe — http://localhost:18888/raster/api.html -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
FAIL url.asis.04-titiler_pgstac[9].iframe — http://localhost:18888/raster/collections/-sentinel-2-c1-l2a/WebMercatorQuad/map.html?assets=red&assets=green&assets=blue&color_formula=Gamm -> 404 final=ht
PASS url.asis.04-titiler_pgstac[29].iframe — http://localhost:18888/raster/external/WebMercatorQuad/map.html?url=https%3A%2F%2Fnasa-maap-data-store.s3.us-west-2.amazonaws.com%2Ffile-sta -> 200 text/ht
PASS tile.asis.04-titiler_pgstac[29] — /raster/external/tiles/WebMercatorQuad/7/37/50?url=https%3A%2F%2Fnasa-maap-data-store.s3.us-west-2.amazonaws.c -> 200 image/jpeg in 0.5s
PASS url.asis.04-titiler_pgstac[31].iframe — http://localhost:18888/raster/collections/glad-global-forest-change-1.11/WebMercatorQuad/map.html?assets=lossyear&colormap=%7B%220%22%3A+%5B -> 200 text/ht
PASS tile.asis.04-titiler_pgstac[31] — /raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/2/2/2?assets=lossyear&colormap=%7B%22 -> 204  in 0.0s
PASS prefix.asis.04-titiler_pgstac — 4 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.asis.05-tipg — 12 code cells, 0 errored or silently failed (executed 2026-10-01T18:13Z)
PASS url.asis.05-tipg[16].iframe — http://localhost:18888/vector/collections/features.ecoregions/items?bbox=-77%2C39%2C-76%2C40&f=html -> 200 text/html
PASS url.asis.05-tipg[18].iframe — http://localhost:18888/vector/api.html#OGC Features API/items_collections__collectionId__items_get -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.asis.05-tipg[25].iframe — http://localhost:18888/vector/collections/features.ecoregions/tiles/WebMercatorQuad/map.html -> 200 text/html; tilejson 200 application/json; tiles on Lab origin=Tru
PASS tile.asis.05-tipg[25] — /vector/collections/features.ecoregions/tiles/WebMercatorQuad/3/1/2 -> 200 application/vnd.mapbox-vector-tile in 0.1s
PASS url.asis.05-tipg[27].iframe — http://localhost:18888/vector/collections/features.ecoregions/tiles/WebMercatorQuad/map.html?na_l2name=MEDITERRANEAN+CALIFORNIA -> 200 text/html; tilejson 200 applic
PASS tile.asis.05-tipg[27] — /vector/collections/features.ecoregions/tiles/WebMercatorQuad/3/1/2?na_l2name=MEDITERRANEAN+CALIFORNIA -> 200 application/vnd.mapbox-vector-tile in 0.0s
PASS prefix.asis.05-tipg — 17 distinct localhost URLs in outputs, 13 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.participant.02-database — 18 code cells, 0 errored or silently failed (executed 2026-10-01T18:13Z)
FAIL url.participant.02-database[22].iframe — https://radiantearth.github.io/stac-browser/#/external/http://localhost:8084/stac/collections/spike-notebooks-sentinel-2-c1-l2a -> not on the Lab origin (
PASS prefix.participant.02-database — 0 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
FAIL cell.participant.03-stac_fastapi_pgstac[23] — silent: "detail": "Invalid RFC3339 datetime." | (e) pre-existing bug: stac-auth-proxy 1.2.0 filter injection (utils/filters.py dict_to_query_string) 
FAIL cell.participant.03-stac_fastapi_pgstac[28] — KeyError: 'features' | (e) pre-existing bug: same proxy bug as [23]: the 400 body has no 'features'
FAIL cell.participant.03-stac_fastapi_pgstac[30] — KeyError: 'features' | (e) pre-existing bug: cascade from [28]
FAIL cell.participant.03-stac_fastapi_pgstac[32] — NameError: name 'item_id' is not defined | (e) pre-existing bug: cascade from [28]
FAIL nb.participant.03-stac_fastapi_pgstac — 15 code cells, 4 errored or silently failed (executed 2026-10-01T18:13Z)
FAIL url.participant.03-stac_fastapi_pgstac[2].printed — http://localhost:8084/stac -> not on the Lab origin (another localhost port: not published, only the Lab is) | (a) URL/env contract: kernel-sid
PASS url.participant.03-stac_fastapi_pgstac[11].printed — http://localhost:18888/stac/api.html#/default/Get_Collections_collections_get -> 200 text/html; openapi 200 application/json
PASS url.participant.03-stac_fastapi_pgstac[11].iframe — http://localhost:18888/stac/api.html#/default/Get_Collections_collections_get -> 200 text/html; openapi 200 application/json
PASS url.participant.03-stac_fastapi_pgstac[34].printed — http://localhost:18888/stac/api.html -> 200 text/html; openapi 200 application/json
PASS url.participant.03-stac_fastapi_pgstac[34].iframe — http://localhost:18888/stac/api.html -> 200 text/html; openapi 200 application/json
PASS prefix.participant.03-stac_fastapi_pgstac — 15 distinct localhost URLs in outputs, 12 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.participant.04-titiler_pgstac — 15 code cells, 0 errored or silently failed (executed 2026-10-01T18:13Z)
PASS url.participant.04-titiler_pgstac[3].printed — http://localhost:18888/raster/api.html -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.participant.04-titiler_pgstac[3].iframe — http://localhost:18888/raster/api.html -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.participant.04-titiler_pgstac[9].iframe — http://localhost:18888/raster/collections/spike-notebooks-sentinel-2-c1-l2a/WebMercatorQuad/map.html?assets=red&assets=green&assets=blue&col -> 200 t
PASS tile.participant.04-titiler_pgstac[9] — /raster/collections/spike-notebooks-sentinel-2-c1-l2a/tiles/WebMercatorQuad/8/233/156?assets=red&assets=green& -> 200 image/jpeg in 10.8s
PASS url.participant.04-titiler_pgstac[14].iframe — http://localhost:18888/raster/searches/893d5f7bff6e5c45dbf36850c844bf26/WebMercatorQuad/map.html?assets=red&assets=green&assets=blue&color_f -> 200 
PASS tile.participant.04-titiler_pgstac[14] — /raster/searches/893d5f7bff6e5c45dbf36850c844bf26/tiles/WebMercatorQuad/8/233/156?assets=red&assets=green&asse -> 200 image/jpeg in 8.1s
PASS url.participant.04-titiler_pgstac[17].iframe — http://localhost:18888/raster/searches/893d5f7bff6e5c45dbf36850c844bf26/WebMercatorQuad/map.html?assets=nir&assets=red&asset_as_band=True&ex -> 200 
FAIL tile.participant.04-titiler_pgstac[17] — /raster/searches/893d5f7bff6e5c45dbf36850c844bf26/tiles/WebMercatorQuad/8/233/156?assets=nir&assets=red&asset_ -> 400 application/json in 1.4s | (e) pre-e
PASS url.participant.04-titiler_pgstac[29].iframe — http://localhost:18888/raster/external/WebMercatorQuad/map.html?url=https%3A%2F%2Fnasa-maap-data-store.s3.us-west-2.amazonaws.com%2Ffile-sta -> 200 
PASS tile.participant.04-titiler_pgstac[29] — /raster/external/tiles/WebMercatorQuad/7/37/50?url=https%3A%2F%2Fnasa-maap-data-store.s3.us-west-2.amazonaws.c -> 200 image/jpeg in 1.0s
PASS url.participant.04-titiler_pgstac[31].iframe — http://localhost:18888/raster/collections/glad-global-forest-change-1.11/WebMercatorQuad/map.html?assets=lossyear&colormap=%7B%220%22%3A+%5B -> 200 
PASS tile.participant.04-titiler_pgstac[31] — /raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/2/2/2?assets=lossyear&colormap=%7B%22 -> 204  in 0.0s
PASS prefix.participant.04-titiler_pgstac — 11 distinct localhost URLs in outputs, 5 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
FAIL cell.zeropoint.02-database[16] — IndexError: list index out of range | (e) pre-existing bug: default point (25.5, -89.99) -> earth-search returns 0 items -> items[0]; 9/100 default points do this
FAIL cell.zeropoint.02-database[24] — IndexError: list index out of range | (e) pre-existing bug: cascade from [16]: items[-1] of an empty list
FAIL cell.zeropoint.02-database[26] — IndexError: list index out of range | (e) pre-existing bug: cascade from [16]: items[-1] of an empty list
FAIL nb.zeropoint.02-database — 18 code cells, 3 errored or silently failed (executed 2026-10-01T18:13Z)
FAIL url.zeropoint.02-database[22].iframe — https://radiantearth.github.io/stac-browser/#/external/http://localhost:8084/stac/collections/spike-notebooks-zero-sentinel-2-c1-l2a -> not on the Lab origi
PASS prefix.zeropoint.02-database — 0 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.fixed.00-introduction — 1 code cells, 0 errored or silently failed (executed 2026-10-01T18:13Z)
PASS url.fixed.00-introduction[23].link — http://localhost:18888/stac/ -> 200 application/json
PASS url.fixed.00-introduction[23].link — http://localhost:18888/raster/ -> 200 application/json
PASS url.fixed.00-introduction[23].link — http://localhost:18888/vector/ -> 200 application/json
PASS url.fixed.00-introduction[23].link — http://localhost:18888/browser/ -> 200 text/html
PASS url.fixed.00-introduction[23].link — http://localhost:18888/manager/ -> 200 text/html
PASS prefix.fixed.00-introduction — 5 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.fixed.02-database — 18 code cells, 0 errored or silently failed (executed 2026-10-01T18:14Z)
PASS url.fixed.02-database[22].printed — http://localhost:18888/browser/collections/spike-notebooks-sentinel-2-c1-l2a -> 200 text/html
PASS url.fixed.02-database[22].iframe — http://localhost:18888/browser/collections/spike-notebooks-sentinel-2-c1-l2a -> 200 text/html
PASS prefix.fixed.02-database — 1 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.fixed.03-stac_fastapi_pgstac — 15 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
PASS url.fixed.03-stac_fastapi_pgstac[2].printed — http://localhost:18888/stac -> 200 application/json
PASS url.fixed.03-stac_fastapi_pgstac[11].printed — http://localhost:18888/stac/api.html#/default/Get_Collections_collections_get -> 200 text/html; openapi 200 application/json
PASS url.fixed.03-stac_fastapi_pgstac[11].iframe — http://localhost:18888/stac/api.html#/default/Get_Collections_collections_get -> 200 text/html; openapi 200 application/json
PASS url.fixed.03-stac_fastapi_pgstac[34].printed — http://localhost:18888/stac/api.html -> 200 text/html; openapi 200 application/json
PASS url.fixed.03-stac_fastapi_pgstac[34].iframe — http://localhost:18888/stac/api.html -> 200 text/html; openapi 200 application/json
PASS prefix.fixed.03-stac_fastapi_pgstac — 19 distinct localhost URLs in outputs, 15 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.fixed.04-titiler_pgstac — 15 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
PASS url.fixed.04-titiler_pgstac[3].printed — http://localhost:18888/raster/api.html -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.fixed.04-titiler_pgstac[3].iframe — http://localhost:18888/raster/api.html -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.fixed.04-titiler_pgstac[9].iframe — http://localhost:18888/raster/collections/spike-notebooks-sentinel-2-c1-l2a/WebMercatorQuad/map.html?assets=red&assets=green&assets=blue&col -> 200 text/ht
PASS tile.fixed.04-titiler_pgstac[9] — /raster/collections/spike-notebooks-sentinel-2-c1-l2a/tiles/WebMercatorQuad/8/233/156?assets=red&assets=green& -> 200 image/jpeg in 8.5s
PASS url.fixed.04-titiler_pgstac[14].iframe — http://localhost:18888/raster/searches/893d5f7bff6e5c45dbf36850c844bf26/WebMercatorQuad/map.html?assets=red&assets=green&assets=blue&color_f -> 200 text/h
PASS tile.fixed.04-titiler_pgstac[14] — /raster/searches/893d5f7bff6e5c45dbf36850c844bf26/tiles/WebMercatorQuad/8/233/156?assets=red&assets=green&asse -> 200 image/jpeg in 8.0s
PASS url.fixed.04-titiler_pgstac[17].iframe — http://localhost:18888/raster/searches/893d5f7bff6e5c45dbf36850c844bf26/WebMercatorQuad/map.html?assets=nir&assets=red&asset_as_band=True&ex -> 200 text/h
PASS tile.fixed.04-titiler_pgstac[17] — /raster/searches/893d5f7bff6e5c45dbf36850c844bf26/tiles/WebMercatorQuad/8/233/156?assets=nir&assets=red&asset_ -> 200 image/jpeg in 10.5s
PASS url.fixed.04-titiler_pgstac[29].iframe — http://localhost:18888/raster/external/WebMercatorQuad/map.html?url=https%3A%2F%2Fnasa-maap-data-store.s3.us-west-2.amazonaws.com%2Ffile-sta -> 200 text/h
PASS tile.fixed.04-titiler_pgstac[29] — /raster/external/tiles/WebMercatorQuad/7/37/50?url=https%3A%2F%2Fnasa-maap-data-store.s3.us-west-2.amazonaws.c -> 200 image/jpeg in 1.0s
PASS url.fixed.04-titiler_pgstac[31].iframe — http://localhost:18888/raster/collections/glad-global-forest-change-1.11/WebMercatorQuad/map.html?assets=lossyear&colormap=%7B%220%22%3A+%5B -> 200 text/h
PASS tile.fixed.04-titiler_pgstac[31] — /raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/2/2/2?assets=lossyear&colormap=%7B%22 -> 204  in 0.0s
PASS prefix.fixed.04-titiler_pgstac — 11 distinct localhost URLs in outputs, 5 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.fixed.05-tipg — 12 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
PASS url.fixed.05-tipg[16].iframe — http://localhost:18888/vector/collections/features.ecoregions/items?bbox=-77%2C39%2C-76%2C40&f=html -> 200 text/html
PASS url.fixed.05-tipg[18].iframe — http://localhost:18888/vector/api.html#OGC Features API/items_collections__collectionId__items_get -> 200 text/html; openapi 200 application/vnd.oai.openapi+json
PASS url.fixed.05-tipg[25].iframe — http://localhost:18888/vector/collections/features.ecoregions/tiles/WebMercatorQuad/map.html -> 200 text/html; tilejson 200 application/json; tiles on Lab origin=Tr
PASS tile.fixed.05-tipg[25] — /vector/collections/features.ecoregions/tiles/WebMercatorQuad/3/1/2 -> 200 application/vnd.mapbox-vector-tile in 0.1s
PASS url.fixed.05-tipg[27].iframe — http://localhost:18888/vector/collections/features.ecoregions/tiles/WebMercatorQuad/map.html?na_l2name=MEDITERRANEAN+CALIFORNIA -> 200 text/html; tilejson 200 appli
PASS tile.fixed.05-tipg[27] — /vector/collections/features.ecoregions/tiles/WebMercatorQuad/3/1/2?na_l2name=MEDITERRANEAN+CALIFORNIA -> 200 application/vnd.mapbox-vector-tile in 0.0s
PASS prefix.fixed.05-tipg — 17 distinct localhost URLs in outputs, 13 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.fixed.0608-links — 4 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
PASS url.fixed.0608-links[1].printed — http://localhost:18888/stac -> 200 application/json
PASS url.fixed.0608-links[1].printed — http://localhost:18888/oidc -> 200 text/html
PASS url.fixed.0608-links[2].printed — http://localhost:18888/stac -> 200 application/json
PASS url.fixed.0608-links[3].printed — http://localhost:18888/browser/ -> 200 text/html
PASS url.fixed.0608-links[3].printed — http://localhost:18888/browser/collections/private-alice-notebook -> 200 text/html
PASS url.fixed.0608-links[3].iframe — http://localhost:18888/browser/ -> 200 text/html
PASS prefix.fixed.0608-links — 4 distinct localhost URLs in outputs, 0 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.writes.06-stac_transactions_auth — 10 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
FAIL url.writes.06-stac_transactions_auth[2].printed — http://localhost:8084/stac -> not on the Lab origin (another localhost port: not published, only the Lab is) | (a) URL/env contract: kernel-side 
FAIL url.writes.06-stac_transactions_auth[2].printed — http://localhost:8085/oidc -> not on the Lab origin (another localhost port: not published, only the Lab is) | (a) URL/env contract: kernel-side 
PASS prefix.writes.06-stac_transactions_auth — 2 distinct localhost URLs in outputs, 2 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.writes.07-row_level_auth — 9 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
FAIL url.writes.07-row_level_auth[7].printed — http://localhost:8084/stac -> not on the Lab origin (another localhost port: not published, only the Lab is) | (a) URL/env contract: kernel-side URL prin
PASS prefix.writes.07-row_level_auth — 1 distinct localhost URLs in outputs, 1 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: []
PASS nb.writes.08-stac_browser_auth — 6 code cells, 0 errored or silently failed (executed 2026-10-01T18:15Z)
FAIL url.writes.08-stac_browser_auth[10].iframe — http://localhost:8080 -> not on the Lab origin (another localhost port: not published, only the Lab is) | (a) URL/env contract: IFrame hard-codes comp
FAIL prefix.writes.08-stac_browser_auth — 2 distinct localhost URLs in outputs, 1 kernel-side (JupyterLab linkifies them; dead in the browser); outside the contract prefixes: ['http://localhost:8080']
BLOCKED render.iframes — HTTP 200 + sub-resources only; whether JupyterLab paints each IFrame needs a real browser
BLOCKED render.stac-browser-deep-link — /browser/collections/<id> returns index.html (200); the SPA route is JS
BLOCKED login.stac-browser-oidc-in-iframe — ch. 8 PKCE login inside the Lab needs a real browser
BLOCKED tls.mixed-content — no TLS locally; https Lab + https browser URLs untested
FAIL md.orig.00-introduction[19] — http://localhost:8080 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8081 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8082 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8083 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8084 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8085 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8086 -> compose port in static text: not the participant stack
FAIL md.orig.00-introduction[19] — http://localhost:8888 -> compose port in static text: not the participant stack
FAIL md.orig.08-stac_browser_auth[9] — http://localhost:8080 -> compose port in static text: not the participant stack
FAIL md.orig.08-stac_browser_auth[9] — http://localhost:8080/collections/private-alice-notebook -> compose port in static text: not the participant stack
FAIL md.orig — 10 clickable localhost links in the markdown of 9 notebooks
PASS md.fixed — 0 clickable localhost links in the markdown of 10 notebooks
```

### `probes.py` after adding the legacy-env check (same stack, after run 3)

```
PASS probe.stac-auth-without-legacy-env — STAC_AUTH_PROXY_ENDPOINT unset (was set): stac_auth -> http://localhost:8084/stac, token + GET /collections -> 200
```
