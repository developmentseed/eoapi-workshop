# Browser apps through the Lab front door (topic: browser-apps)

*2026-10-01 · re-run after the usage-limit interruption. Supersedes the unverified WIP files of
commit 95823c1: every check below was re-run and its claims re-checked against source or a probe.*

**Stack under test:** `compose.participant.yml` as built by the build agent, restarted with
`docker compose ... start` before this run. Nothing in it was changed. Chromium is headless
Playwright 1.55.0 (`mcr.microsoft.com/playwright/python:v1.55.0-noble`, arm64), run in a container
with `--network container:eoapi-spike-lab-1`, so `http://localhost:18888` is the participant's
URL and a secure context.

**Reproduce:** `spike/checks/browser-apps/run.sh`. It needs Docker and takes about 5 minutes. It
prints one line per check and always exits 0. `SKIP_BROWSER=1` runs only the HTTP probes and the
fix validations.

| File | What it does |
|---|---|
| `checks/browser-apps/run.sh` | Builds the Playwright image. Starts and removes the throwaway fix containers. Runs everything below. |
| `checks/browser-apps/probes.py` | HTTP checks behind the browser findings, plus validation of the `--root-path` fix against real containers. |
| `checks/browser-apps/tile_timing.py` | Cost of titiler's world-view tile, measured without the browser. |
| `checks/browser-apps/browser_apps.py` | The browser checks. Writes `evidence/screens/browser-apps-NN-*.png` and `browser-apps-console.json`. |

**Conditions:** other testers ran against the same stack at the same time. During this rerun that
included the notebooks tester (nbconvert in the Lab) and the footprint tester (a
`spike-footprint-load-titiler` container). The host load average was up to 9.4. No timing in this
file is a clean benchmark; each one says when it was taken.

## Result: 29 PASS, 7 FAIL, 0 BLOCKED (final run, raw output at the end)

| Task item | Verdict |
|---|---|
| 1. Lab login page, password, wrong password | **Works.** The wrong password gets 401 and no cookie. The right one lands on the Launcher with cookie `username-localhost-18888` (path `/`, HttpOnly, SameSite=Lax, not Secure on plain http). |
| 2. STAC Browser at `/browser/` | **Works:** catalog, collection, item, basemap tiles, deep-link reload, OIDC login with PKCE, and the private collection after login. The OIDC `redirect_uri` keeps the prefix (`http://localhost:18888/browser/auth`). |
| 3. stac-manager at `/manager/` | Loading, deep links and login **work**. **Every write fails as deployed** (create, edit). **Delete is a no-op in the UI** (upstream). With both proposed fixes, create and edit work. |
| 4. Notebook IFrames (titiler `map.html`, tipg viewer) | **Work.** Both load inside the Lab page, the Lab cookie is sent on each, and tiles render. Without the cookie the same URL returns 302 to `/login`. |
| Console errors and failed requests | 170–180 entries per run. Every one is classified (see below), and none is unexplained. |

## Findings

### F1. stac-manager cannot create a collection under the `/stac` prefix (prefix-specific)

stac-manager POSTs to `${STAC_API}/collections/` with a trailing slash
(`packages/client/src/pages/CollectionForm/index.tsx:166`). stac-fastapi has no such route, so
Starlette's `redirect_slashes` answers 307. It builds `Location` without the prefix because:

- stac-auth-proxy strips `/stac` before forwarding.
- stac-fastapi 7.0.0's `ProxyHeaderMiddleware` reads only proto, host and port from `Forwarded`,
  not the `path=/stac/` the proxy sends.
- stac-auth-proxy v1.2.0 rewrites links in JSON bodies (`ProcessLinksMiddleware`) but never the
  `Location` header.
- jupyter-server-proxy 4.6.0 rewrites `Location` only when `absolute_url` is False and the value is
  a bare path (`handlers.py:604-612, 279-317`), so neither applies here.

```
POST :8081/collections/        -> 307 Location=http://localhost:18888/collections   (stac-fastapi itself)
POST :8084/stac/collections/   -> 307 Location=http://localhost:18888/collections   (through the proxy)
browser: POST /stac/collections/ -> 307 [uvicorn] | POST /collections -> 403 [TornadoServer/6.5.10]
```

The browser follows the 307 to the **Lab's own** `/collections`, where Jupyter refuses the POST.
PR #35's compose serves stac-auth-proxy at the root, so there the 307 lands correctly. This finding
comes from the prefix. The same cause makes the queryables' JSON-schema `$id` lack `/stac`
(`http://localhost:18888/queryables`). That is harmless today because the schemas have no relative
`$ref`.

**Fix (validated, not yet applied):** start stac-fastapi with uvicorn `--root-path /stac`. `run.sh`
starts a throwaway stac-fastapi with that flag, plus a stac-auth-proxy with the live one's exact
environment, both in the Lab's netns on :18981/:18982. Against them:

- The 307 says `Location: http://localhost:18888/stac/collections` (for POST and GET).
- 9 GET paths × 2 Host headers (browser `localhost:18888`, kernel `localhost:8084`) return bodies
  identical to the live proxy, including 100 links and the OpenAPI doc. The only change is the 4
  queryables `$id`s, which now carry `/stac`.
- A trailing-slash create, then follow, then PUT, then DELETE with a `stac:write` token gives
  307, 201, 200, 200.

### F2. stac-manager never gets a `stac:write` token, so every write 403s (not prefix-specific)

stac-manager 1.0.3 hard-codes `scope='openid profile email offline_access'`. The source
(`packages/client/src/auth/Context.tsx:235`) and the deployed bundle (`client.e80894ec.js`) both say
so. mock-oidc grants exactly the requested scopes plus `openid profile`
(`mock-oidc-server app/app.py:231`). Its login form cannot add a scope. A custom `scope` claim is
overwritten too, because standard claims win (`app.py:379-390`). stac-auth-proxy's
`PRIVATE_ENDPOINTS` require `stac:write` for POST, PUT, PATCH and DELETE.

- As deployed, an edit of an existing collection gives `PUT /stac/collections/spike-browser-apps-test -> 403 [uvicorn]`.
- With only F1's fix simulated, the create still gives 403 from the proxy. Both fixes are needed.

PR #35's compose (`docker-compose.yml:105-113`) and chart (`values.yaml:278-283`) require the same
scope and use the same image. So **stac-manager writes would fail there too.** This is inferred
from config plus the behaviour verified here; it was not run against PR #35.

**Fix (validated on the image, not yet applied):** add `stac:write` to the bundle's scope at
container start, after the image's own placeholder `sed`. The `sed` is idempotent: the pattern no
longer matches once replaced. `run.sh` runs this exact command on a throwaway stac-manager:1.0.3
container. The bundle then holds `scope:"openid profile email offline_access stac:write"`. With both
fixes simulated in the browser, create gives 201 and edit gives 200.

**Upstream:** stac-manager could make the scope configurable (`REACT_APP_OIDC_SCOPE`). That would
replace the `sed`.

### F3. The Lab token appears on screen in stac-manager's error toast (as deployed)

When F1's redirect reaches Jupyter, the 403 body is Jupyter's HTML error page. For a logged-in
user, Jupyter's `page.html` embeds `data-jupyter-api-token="<token>"`
(`jupyter_server templates/page.html:25-26`). stac-manager shows that raw body in its notification
panel, so the participant sees the Lab token. Anyone watching a projected or shared screen sees it
too. It is the participant's own token, so this is not a cross-user leak. F1's fix removes it,
because the POST no longer reaches Jupyter.

- The check `manager.lab-token-not-on-screen` detects it.
- `shot()` masks any element that shows the token, so this run's screenshots don't contain it.
- **The WIP commit 95823c1 does contain it:** `spike/evidence/screens/browser-apps-14-manager-create-as-deployed.png`
  shows the first 35 characters of the local `LAB_TOKEN`. The commit is local and unpushed, and
  the Lab listens on 127.0.0.1 only. This rerun replaces the file, but the old blob stays in
  history (see proposed fixes).

### F4. stac-manager's Delete does nothing (upstream)

Options > Delete sends no request. `CollectionDetail/index.tsx:188` renders `<DeleteMenuItem />`
with no `onClick`, and `DeleteMenuItem` adds none. 1.0.3 is the latest release (CHANGELOG). The
spike collection was deleted through the API in cleanup. For the workshop: delete from a notebook
(ch. 6 already teaches `DELETE` with a Bearer token), or open an upstream issue.

### F5. The world-view raster `map.html` takes about a minute on a cold cache (compose parity)

The glad mosaic at zoom 0 needs titiler to read about 100 global COGs from S3, with
`MOSAIC_CONCURRENCY=1`. PR #35's compose sets the same value (`docker-compose.yml:155`). Measured
straight at titiler (:8082), no browser, no proxy:

| When | Tile | Time |
|---|---|---|
| 19:51, load average 2.9 | 0/0/0 cold | 67.6 s |
| | 0/0/0 again | 0.4 s |
| | 3/1/2 | 1.2 s |
| Through the IFrame, load average up to 9.4, two runs | 0/0/0 cold | 106 s and 111 s |

Warm requests take under 1 s. The front door adds nothing measurable. What fixes it was not
evaluated (higher `MOSAIC_CONCURRENCY`, a notebook map that opens zoomed in, pre-warming); that
belongs to the notebooks and footprint topics. `tile_timing.py` says when its run saw only a warm
cache.

### F6. The baked glad collection points at MAAP's services (data)

`db/glad_to_sql.py` copies the MAAP collection as-is. It keeps 5 `queryables` links to
`https://stac.maap-project.org/...` and a `tilejson` link to `https://titiler-pgstac.maap-project.org/...`.
STAC Browser follows one external queryables document and logs
`MissingPointerError: Missing $ref pointer "#/definitions/fieldsproperties/eo:cloud_cover"`. The
local `/stac/queryables` documents have no `$ref` at all. The `tilejson` link would send a curious
participant to MAAP's titiler instead of their own. PR #35's loader stores the same links.

### What works, briefly

- **Lab login:** the wrong password gets 401 and no cookie. The password lands on the Launcher.
- **STAC Browser:** the catalog lists glad, the collection lists 10 items, and an item page renders
  with its footprint over OSM basemap tiles (16 × 200). The deep-link reload and a fresh tab both
  return 200 (nginx serves the app for `/browser/...`).
- **Private collections:** anonymously, the private collection is absent from `/stac/collections`
  and its deep link renders nothing. Log in via `/oidc/authorize` (PKCE S256, client
  `stac-browser`, `redirect_uri=http://localhost:18888/browser/auth`), then POST `/oidc/token` (200).
  After that, `/stac/collections` is fetched with Bearer and lists `private-spike-browser-apps-notes`,
  and the deep link renders it.
- **STAC Browser item map:** it draws no data layer. The glad assets are `s3://` COGs with no
  thumbnail, which STAC Browser cannot draw. Compose looks the same.
- **stac-manager:** `/manager/` lists collections. Deep links render the app, though http-server
  answers **404** with `404.html` = `index.html`; browsers render it, but `curl`/monitoring see 404.
  Login via mock-oidc keeps the prefix in `redirect_uri`.
- **IFrames:** a notebook cell displays `IFrame(TITILER_BROWSER_URL + .../map.html?...)` and
  `IFrame(TIPG_BROWSER_URL + .../map.html)`. Both documents return 200 with the Lab cookie, and
  their frames stay on `/raster/...` and `/vector/...`. Tiles return 200: 1 titiler and 7–9 tipg
  per run. The same URL without the cookie returns 302 to `/login`.

### Console errors and failed requests, classified

`evidence/screens/browser-apps-console.json` holds every console error, failed request and HTTP
response of 400 or more, each with its step and class. An unclassified entry fails
`browser.console-and-network`. The classes, from the final run:

- **Upstream:** STAC Browser's `OPTIONS` permission probe gets 405. The probe shows stac-fastapi
  itself answers 405 on `:8081` (`browser.options-405-is-upstream`), so it is not the front door.
- **External:**
  - The `map.html` viewers request OSM tiles outside `0..2^z-1` at zoom 0–1 (400).
  - stac-manager looks up a gravatar with `d=404`.
- **Known:** stac-manager deep links return 404 with the app body.
- **Harmless:** JupyterLab workspace `PUT`s get their 204, then Chromium reports the unread body as
  `ERR_ABORTED`. A dedicated probe showed `response PUT 204` before every `failed PUT net::ERR_ABORTED`.
- **Expected:**
  - Requests cancelled by navigation or map pan/zoom (`ERR_ABORTED` on GET, POST and OPTIONS only).
  - The wrong-password 401.
  - The anonymous deep link to a private collection (404).
- **Findings above:** F1/F2 403s (six entries) and F6's `MissingPointerError`.

### Differences from the interrupted WIP run

- The WIP's "location fix" was only a browser-side rewrite of the header. It is now backed by real
  containers running `--root-path /stac` (F1), and those showed the extra `$id` correction.
- The WIP tested create but not **edit as deployed**. Edits also 403, so F2 covers every write.
- The WIP labelled the 403 on `/collections` without saying where it came from. It is Jupyter's
  (`[TornadoServer]`), and its body leaks the Lab token onto the screen (F3). The WIP's own
  screenshot captured it.
- The WIP's console classifier hid `Failed to fetch` and `Error activating plugin` as "navigation".
  Those patterns are gone: aborts now count only for `ERR_ABORTED`, and workspace `PUT`s are
  explained by a probe.
- The WIP's 111 s raster tile was unexplained. It is titiler's cold cost (F5).
- The WIP asserted nothing about cookies on the IFrame requests. Now it asserts
  `username-localhost-18888` is sent on both `map.html` documents.

## Not tested

- **https.** The `Secure` flag needs `trust_xheaders` plus X-Forwarded-Proto. This run was plain
  http on localhost.
- **Browsers other than Chromium.**
- The laptop `?token=` flow (auth topic).
- stac-manager **item** create and edit.
- STAC Browser logout.
- `map.html` performance on a quiet host.
- **The proposed fixes applied to the running stack.** They were validated on throwaway containers
  and in the browser only. After a later agent applies them, re-run `run.sh`. The
  `*-as-deployed` checks and `manager.lab-token-not-on-screen` should then pass, and the
  simulations become no-ops.

## Raw output of the final run

```
FAIL stac.trailing-slash-redirect-keeps-prefix — POST :8081/collections/ -> 307 Location=http://localhost:18888/collections; POST :8084/stac/collections/ -> 307 Location=http://localhost:18888/collections; GET :8084/stac/collections/ -> 307 Location=http://localhost:18888/collections. stac-fastapi (Starlette redirect_slashes) builds Location without /stac and stac-auth-proxy v1.2.0 rewrites links in JSON bodies only, not Location headers; the browser then POSTs to the Lab's own /collections
FAIL stac.queryables-id-keeps-prefix — JSON-schema $id: {'/stac/queryables': 'http://localhost:18888/queryables', '/stac/collections/glad-global-forest-change-1.11/queryables': 'http://localhost:18888/collections/glad-global-forest-change-1.11/queryables'} (same cause: stac-fastapi does not know its /stac prefix; harmless today, the schemas have no relative $ref)
PASS browser.options-405-is-upstream — OPTIONS stac-fastapi :8081/ -> 405, stac-auth-proxy :8084/stac/ -> 405: STAC Browser's permission probe 405s at the API itself, not at the Lab front door
PASS fix.root-path.redirect-keeps-prefix — stac-fastapi --root-path /stac behind a ROOT_PATH=/stac proxy: POST /stac/collections/ -> 307 Location=http://localhost:18888/stac/collections; GET -> 307 Location=http://localhost:18888/stac/collections
PASS fix.root-path.responses-unchanged — 9 GET paths x 2 Host headers: bodies (incl. 100 links, OpenAPI) identical to the running proxy, except 4 queryables $id that now carry /stac (corrected)
PASS fix.root-path.write-flow — Bearer token with stac:write, trailing-slash create as stac-manager sends it: POST /stac/collections/ -> 307 | POST /stac/collections -> 201 | PUT -> 200 | DELETE -> 200; gone afterwards=True
PASS fix.manager-scope-sed — after the entrypoint, the proposed sed leaves: scope:"openid profile email offline_access stac:write" scope:"openid" 
PASS iframe.raster-world-tile-latency — direct to titiler-pgstac (MOSAIC_CONCURRENCY=1, 100 glad items): 0/0/0 -> 200 in 0.9 s; 0/0/0 -> 200 in 0.5 s; 3/1/2 -> 200 in 1.3 s (cache already warm from an earlier request: this run did not measure the cold cost)
PASS lab.login-page — GET /lab/workspaces/spike-browser-apps -> /login?next=%2Flab%2Fworkspaces%2Fspike-browser-apps (200), password field visible
PASS lab.wrong-password — POST /login -> 401, still on /login?next=%2Flab%2Fworkspaces%2Fspike-browser-apps, login cookie set=False
PASS lab.password-login — lands on /lab/workspaces/spike-browser-apps with the JupyterLab Launcher; cookie username-localhost-18888 path=/ httpOnly=True secure=False sameSite=Lax
PASS setup.private-collection — POST private-spike-browser-apps-notes as owner=spike-browser-apps -> 201; GET anon -> 404, owner -> 200
PASS browser.catalog — /browser/ title='stac-fastapi', glad collection card listed
PASS browser.collection — /browser/collections/glad-global-forest-change-1.11 lists 10 item links on the first page
PASS browser.item — /browser/collections/glad-global-forest-change-1.11/items/hansen-gfc-2023-v1.11-80N-180W heading=hansen-gfc-2023-v1.11-80N-180W, assets listed
PASS browser.map-tiles — OpenLayers canvas=2, basemap tiles (tile.openstreetmap.org) 200=16 other=[]; item footprint drawn. No data layer: glad assets are s3:// COGs with no thumbnail, which STAC Browser cannot draw (same with PR #35 compose)
PASS browser.deep-link-reload — reload of item URL -> 200, heading rendered; fresh tab on /browser/collections/glad-global-forest-change-1.11 -> 200
PASS browser.private-hidden-anon — /stac/collections seen by the page: 1 response(s), private id listed=False; deep link /browser/collections/private-spike-browser-apps-notes shows the private title=False
PASS browser.oidc-redirect-uri — /oidc/authorize redirect_uri=http://localhost:18888/browser/auth client_id=['stac-browser'] scope=['openid'] PKCE=['S256']
PASS browser.oidc-login — mock-oidc 303 -> /browser/auth?code=<redacted> POST /oidc/token -> 200; back on /browser/ with a Log out button
PASS browser.private-visible — 1 /stac/collections response(s) sent with Bearer, first page lists private-spike-browser-apps-notes=True; deep link renders the private collection
PASS manager.loads — /manager/ renders the collection list (glad listed)
PASS manager.deep-link-reload — /manager/collections/glad-global-forest-change-1.11/ -> HTTP 404, reload -> HTTP 404; the app renders the collection both times (http-server serves 404.html = the app)
PASS manager.oidc-login — redirect_uri=http://localhost:18888/manager/collections/glad-global-forest-change-1.11/ scope='openid profile email offline_access'; back with a Logout button
FAIL manager.create-as-deployed — POST /stac/collections/ -> 307 [uvicorn, uvicorn] Location: http://localhost:18888/collections | POST /collections -> 403 [TornadoServer/6.5.10]; collection exists=False
FAIL manager.edit-as-deployed — collection created through the API, then stac-manager Save: PUT /stac/collections/spike-browser-apps-test -> 403 [uvicorn] (Bearer=True); stored title='Spike browser-apps test'
FAIL manager.create-root-path-fix-only — POST /stac/collections/ -> 307 [uvicorn] Location: http://localhost:18888/stac/collections | POST /stac/collections -> 403 [uvicorn]; created=False. With only fix 1 the token still lacks stac:write (scope 'openid profile email offline_access'), so fix 2 is needed too
PASS manager.create-with-fixes — scope=['openid profile email offline_access stac:write']; POST /stac/collections/ -> 307 [uvicorn] Location: http://localhost:18888/stac/collections | POST /stac/collections -> 201 [uvicorn, uvicorn]; GET /stac/collections/spike-browser-apps-test -> 200
PASS manager.edit-with-fixes — PUT /stac/collections/spike-browser-apps-test -> 200 [uvicorn, uvicorn] (Bearer=True); stored title='Spike browser-apps test (edited)'
FAIL manager.delete — clicked Options > Delete: DELETE requests sent=0, collection still there=True. stac-manager 1.0.3 renders <DeleteMenuItem /> with no onClick (packages/client/src/pages/CollectionDetail/index.tsx:188); no newer release
PASS iframe.map-pages-load-with-cookie — 2 IFrame outputs in the Lab; map.html documents: [('raster', 200), ('vector', 200)], Lab cookie sent on each=[True, True]; frame URLs stay on ['/raster/collections/glad-global-forest-change-1.11/WebMercatorQuad/map.html', '/vector/collections/features.ecoregions/tiles/WebMercatorQuad/map.html'] (no /login redirect)
PASS iframe.tiles-render — within 5 s of the IFrames appearing: titiler tiles 1 requested, 200=1, other=[], latency median 0.6 s max 0.6 s; tipg tiles 7 requested, 200=7, other=[], latency median 0.0 s max 1.3 s. Latency measured while other testers loaded the same host
PASS iframe.cookie-required — same map.html URL without the Lab cookie -> 302 Location=/login?next=%2Fraster%2Fcollections%2Fglad-global-forest-cha
PASS cleanup — session 204, notebook 204, workspace 204, spike-browser-apps-test 200, private-spike-browser-apps-notes 200; left behind=[]
FAIL manager.lab-token-not-on-screen — the Lab token was visible on ['14-manager-create-as-deployed: 1 element(s)'] (masked in the PNG). stac-manager's error toast shows the raw body of the 403 it got from Jupyter's own /collections, and Jupyter's page.html embeds data-jupyter-api-token for a logged-in user (jupyter_server templates/page.html:25-26). Goes away with the root-path fix (the POST no longer reaches Jupyter)
PASS browser.console-and-network — 172 console errors / failed or >=400 requests; 54x upstream: STAC Browser's OPTIONS permission probe gets 405 from stac-fastapi itself (probe browser.options-405-is-upstream); 50x external: map.html viewers ask OSM for out-of-range tiles (x or y outside 0..2^z-1) at low zoom; 20x known: stac-manager deep links are served by http-server's 404.html fallback (the app renders); 16x expected: request cancelled by a page navigation or a map pan/zoom; 14x external: stac-manager avatar lookup (gravatar d=404); 6x FINDING: stac-manager writes as deployed (see manager.*-as-deployed / *-root-path-fix-only); 5x harmless: JupyterLab workspace PUT gets its 204, then Chromium reports the unread body as aborted; 3x expected: anonymous deep link to a private collection; 2x expected: wrong-password probe; 2x data: the baked glad collection keeps 5 MAAP queryables links; STAC Browser follows one and hits a broken $ref
```
