# APIs: STAC, raster and vector under their prefixes, through the Lab

*2026-10-01 · Docker Desktop, arm64 Mac · branch `spike/per-user-stacks` · stack from `spike/compose.participant.yml` (left running by the build agent, not restarted) · reproducible via `spike/checks/apis/run.sh`*

## Result

The path-prefix design holds for all three APIs: **55 PASS, 8 FAIL, 0 BLOCKED.** None of the 8 FAILs is a broken prefix or a wrong generated link.

- **Every link the APIs generate points under the right prefix.** That covers landing pages, conformance, collections, items, item search GET and POST, `next` links, tilejson tile URLs, `map.html` and the tipg viewer and HTML pages. Through the Lab they read `http://localhost:18888/<prefix>/…`; on the in-pod ports they read `http://localhost:808x/<prefix>/…`. Following `next` links through the Lab works for GET and POST.
- **Behind a TLS-terminating ingress** (simulated with `Host`, `X-Forwarded-Proto/Host/Port` and `X-Scheme`), every generated link becomes `https://<host>/<prefix>/…`. No viewer requests anything over `http://`, and the Lab cookie gets `Secure`.
- **Real tiles render through the Lab:**
  - glad: PNG and JPEG, collection-level, search mosaic and item point.
  - A notebook-02/03/04 style Sentinel-2 collection loaded from Earth Search: collection RGB tile, and a cloud-filtered `searches/register` mosaic tile.
  - `/external` (notebook 04 §4.4): info, preview, `map.html` and a tile.
  - tipg vector tiles: `application/vnd.mapbox-vector-tile`, 61 kB at z4.
- **The kernel URLs work too.** `localhost:8082` and `:8083` answer both prefixed and unprefixed. `:8084` needs `/stac`, which is how the notebooks call it. `to_browser()` turns a server-side tile, viewer or STAC URL into one that loads through the Lab.

The 8 FAILs fall into three groups:

- **Two come from the Lab-as-front-door design. Both have fixes:**
  - A1: STAC Swagger UI.
  - A2: `?token=` collides with STAC's pagination `token`. Two FAILs.
- **Four are notebook and API-version bugs that also exist in PR #35 compose**, which uses the same images and config:
  - A3: stac-auth-proxy mangles query strings. Two FAILs.
  - A5: the NDVI expression.
  - A6: `maxsize`.
- **One is baked-data hygiene:** A4, glad carries MAAP's API links.

## How to reproduce

```sh
cd spike
docker compose -p eoapi-spike -f compose.participant.yml up -d --wait   # if not already up
checks/apis/run.sh
```

- `run.sh` pipes `apis.py` into `docker exec -i eoapi-spike-lab-1 /entrypoint.sh python -`. Inside the Lab, `localhost` is the pod network namespace and `http://localhost:18888` is the URL a browser uses.
- Three clients:
  - **browser:** logs in once with `?token=`, then sends the Lab cookie.
  - **ingress:** the same, plus the headers ingress-nginx sets, with `Host: lab-u01.example.test`.
  - **kernel:** in-pod URLs from the notebook URL contract.
- **Data:**
  - `apis.py` loads `spike-apis-sentinel-2-c1-l2a`: 30 Earth Search items, ids `spike-apis-*`, loaded with pypgstac as notebook 02 does.
  - It deletes them, plus any searches registered on that collection, at the end. `KEEP_DATA=1` keeps them.
  - It needs internet from the containers: Earth Search, the S3 COGs and the CDNs.
- **Throwaway container:** `run.sh` starts `eoapi-spike-apis-sapfix`, a second stac-auth-proxy, in the pod netns on port 18094. Nothing is published, and the container is removed afterwards. It verifies the A1 fix without touching the running service.
- The Lab token is redacted (`<LAB_TOKEN>`) in everything the script prints.

## Raw output (`checks/apis/run.sh`, final run, lines trimmed at 260 chars)

```
PASS stac.landing — 200; 9 links under http://localhost:18888/stac/; rels=['conformance', 'data', 'http://www.opengis.net/def/rel/ogc/1.0/queryables', 'root', 'search', 'self', 'service-desc', 'service-doc']
PASS stac.conformance — 200; 28 classes; missing=[]
PASS stac.collections — 200; 17 links under http://localhost:18888/stac/; foreign API-rel links: [('http://www.opengis.net/def/rel/ogc/1.0/queryables', 'stac.maap-project.org'), ('tilejson', 'titiler-pgstac.maap-project.org')]; ids=['glad-global-forest-change…
PASS stac.collection — 200; 5 links under http://localhost:18888/stac/; foreign API-rel links: [('http://www.opengis.net/def/rel/ogc/1.0/queryables', 'stac.maap-project.org'), ('tilejson', 'titiler-pgstac.maap-project.org')]
FAIL stac.collection.no-foreign-api-links — glad-global-forest-change-1.11: 6 links with API rels point at another deployment {('queryables', 'stac.maap-project.org'): 5, ('tilejson', 'titiler-pgstac.maap-project.org'): 1} (baked from the MAAP source collecti…
PASS stac.queryables — /queryables=200 /collections/{id}/queryables=200
PASS stac.items+next — 13 links under http://localhost:18888/stac/; next=/stac/collections/glad-global-forest-change-1.11/items?limit=2&token=next%3Aglad-global-fo… -> 200 2 new items
PASS stac.item — 200 hansen-gfc-2023-v1.11-80N-180W; 4 links under http://localhost:18888/stac/; asset href schemes=['s3'] (data, not rewritten)
PASS stac.search-get+next — 200; 11 links under http://localhost:18888/stac/; next (GET, carries STAC token=next:…) -> 200 2 new items
PASS stac.search-post+next — 200; 11 links under http://localhost:18888/stac/; next=POST /stac/search body.token -> 200 2 new items
PASS stac.openapi — 200; servers=[{'url': '/stac'}]
FAIL stac.api-docs — 200; Swagger UI loads its spec from ['/api'] = the Lab's own Jupyter API, which answers '{"version": "2.21.1"}', so Swagger UI cannot render the STAC API
PASS stac.no-trailing-slash — GET /stac -> 302 location=/stac/
FAIL stac.lab-token-in-query — {'/stac/': '200', '/stac/collections': '200 token-echoed', '/stac/search': '500', '/stac/collections/glad-global-forest-change-1.11/items': '500'}; /search and /items return 500 (pgstac: 'Could not find item using token: <LAB_TO…
PASS stac.lab-token-and-next-token — no cookie: next link -> 302 (login redirect, expected); next&token=LAB -> 200; token=LAB&next -> 302: Jupyter takes the LAST `token`, stac-fastapi the FIRST, so only one order works
PASS stac.pystac-client.cookie — collections=['glad-global-forest-change-1.11', 'spike-apis-sentinel-2-c1-l2a', 'spike-notebooks-sentinel-2-c1-l2a']; search limit=2 max_items=5 -> 5 items over 3 pages
PASS stac.pystac-client.token-once — Client.open('<lab>/stac/?token=…') then search paged -> 5 items (cookie from the first response)
FAIL stac.pystac-client.token-parameter — Client.open(…, parameters={'token': LAB_TOKEN}) then search: {'POST': '5 items', 'GET': 'APIError: Internal Server Error'}. POST works because the STAC pagination token travels in the body; GET puts both tokens in the…
PASS raster.landing — 200; 11 links under http://localhost:18888/raster/
PASS raster.api-docs — api.html 200 spec=['/raster/api']; /raster/api 200 servers=[{'url': '/raster'}]
PASS raster.tilejson.glad — 200 tiles[0]=http://localhost:18888/raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/{z}/{x}/{y}?assets=lossyear&tilesize=512
PASS raster.tile.glad — z8/46/80 200 image/png 20052 B, (4, 256, 256), opaque px=65536 (0.7s)
PASS raster.tile.glad-from-tilejson-template — 200 image/jpeg 20648 B (tilejson URL as-is)
PASS raster.point.glad — 200 {"coordinates":[-115.0,55.0],"assets":[{"name":"glad-global-forest-change-1.11/hansen-gfc-2023-v1.11-60N-120W","values":[0.0],"band_names":["b1"],"band_descript
PASS raster.map.glad — 200; 2 same-origin URLs, all under http://localhost:18888/raster/; requests ['http://localhost:18888/raster/collections/glad-global-forest-change-1.11/WebMercatorQuad/tilejson.js', 'http://localhost:18888/raster/collections/glad-global-…
PASS raster.searches.glad — register 200; 4 links under http://localhost:18888/raster/; tilejson tiles prefixed=True; tile 200 image/png 20052 B, (4, 256, 256), opaque px=65536 (0.5s)
PASS raster.s2.load-like-notebook-02 — 30 items from Earth Search into spike-apis-sentinel-2-c1-l2a; 2 with eo:cloud_cover < 10
PASS stac.s2.search-like-notebook-03 — server-side pystac-client: datetime>=2025-01-04 30 items, cql2 cloud<10 2; browser /items?filter=eo:cloud_cover<10 200 2 items, 12 links under http://localhost:18888/stac/; one item 200: 4 links under http://localhost:18…
FAIL stac.datetime-offset-like-notebook-03 — GET /search datetime=…: {'+00:00 lab': 400, '+00:00 8084': 400, '+00:00 8081 direct': 200, 'Z lab': 200, 'Z 8084': 200, 'Z 8081 direct': 200}. Behind stac-auth-proxy a '+' in the query reaches stac-fastapi unencode…
FAIL stac.collection-search-like-notebook-03 — {'%glad%': 'lab=1 direct=1', '%bal%': 'lab=0 direct=1 MISMATCH', '%c1-l2a%': 'lab=0 direct=2 MISMATCH', '%u01%': 'lab=0 direct=0'}; patterns starting '%<hex><hex>' (e.g. %ba, %c1, %da, %fa, %de...) silently match…
PASS raster.s2.tilejson-like-notebook-04 — server tiles[0]=http://localhost:8082/raster/collections/spike-apis-sentinel-2-c1-l2a/tiles/WebMercatorQua…; browser tiles[0]=http://localhost:18888/raster/collections/spike-apis-sentinel-2-c1-l2a/tiles/WebMercatorQu…
PASS raster.s2.collection-map+tile — map.html: 200; 2 same-origin URLs, all under http://localhost:18888/raster/; requests ['http://localhost:18888/raster/collections/spike-apis-sentinel-2-c1-l2a/WebMercatorQuad/tilejson.json', 'http://localhost:18888/raster/…
PASS raster.s2.mosaic-search-like-notebook-04 — register (kernel) 200 links under http://localhost:8082/raster/=True; map.html: 200; 2 same-origin URLs, all under http://localhost:18888/raster/; requests ['http://localhost:18888/raster/searches/326f70b307c326…
FAIL raster.s2.ndvi-tile-like-notebook-04 — notebook params (asset_as_band, '(nir - red) / (nir + red)'): 400 application/json '{"detail":"Invalid band/asset name \'nir\'"}' (1.1s); with expression '(b1 - b2) / (b1 + b2)' instead: 200 image/png 108237 B, (4, …
PASS raster.external.info+preview — kernel: info 200 (0.0s) width=40000; preview 200 image/jpeg (1, 1024, 1024) (0.0s); through the Lab: preview 200
FAIL raster.external.preview-size-like-notebook-04 — param=2048 -> (h, w): {'maxsize': (1024, 1024), 'max_size': (2048, 2048)}; `maxsize` is silently ignored (default 1024)
PASS raster.external.map-like-notebook-04 — 200; 2 same-origin URLs, all under http://localhost:18888/raster/; requests ['http://localhost:18888/raster/external/WebMercatorQuad/tilejson.json?url=https%3A%2F%2Fnasa-maap-dat', 'http://localhost:18888/raster/ext…
PASS vector.landing — 200; 15 links under http://localhost:18888/vector/
PASS vector.api-docs — api.html 200 spec=['/vector/api']; /vector/api 200 servers=[{'url': '/vector'}]
PASS vector.conformance — 200 18 classes
PASS vector.collections — 200; 7 links under http://localhost:18888/vector/; ids=['features.ecoregions'] (TIPG_DB_SCHEMAS=[features]: no public.*)
PASS vector.collection+queryables — 200; 8 links under http://localhost:18888/vector/; queryables 200 13 props
PASS vector.items+next — 7 links under http://localhost:18888/vector/; numberMatched=2548; next=/vector/collections/features.ecoregions/items?f=geojson&limit=2&offset=2 -> 200 ids=[3, 4]
PASS vector.items-variants-like-notebook-05 — geojsonseq 200 2 lines; na_l2name filter matched=45; bbox matched=20
PASS vector.items-html — 200; 18 same-origin URLs, all under http://localhost:18888/vector/; requests []; 5 external js/css all 200; third-party hosts ['cdnjs.cloudflare.com', 'files.dnr.state.mn.us']
PASS vector.tilejson+tile — tiles[0]=http://localhost:18888/vector/collections/features.ecoregions/tiles/WebMercatorQuad/{z}/{x}/{y}; z4/2/6 -> 200 application/vnd.mapbox-vector-tile 61014 B
PASS vector.viewer — 200; 9 same-origin URLs, all under http://localhost:18888/vector/; requests ['http://localhost:18888/vector/collections/features.ecoregions/tiles/WebMercatorQuad/tilejson.json']; 8 external js/css all 200; third-party hosts ['cdnjs.cloudf…
PASS xfp.lab-cookie-secure — Set-Cookie under X-Forwarded-Proto: https has Secure=True (trust_xheaders)
PASS xfp.stac.links — all links https://lab-u01.example.test/stac/…: {'/': '200 ok', '/collections': '200 ok', '/collections/glad-global-forest-change-1.11': '200 ok', '/collections/glad-global-forest-change-1.11/items': '200 ok', '/search': '200 ok', 'POST /…
PASS xfp.stac.static-urls — auth:schemes openIdConnectUrl=http://localhost:18888/oidc/.well-known/openid-configuration is config (OIDC_DISCOVERY_URL), not derived from the request: the chart must set it per participant to https://lab-uNN.<base>/oidc/.well-kno…
PASS xfp.stac.api-docs — /stac/api 200 servers=[{'url': '/stac'}] (relative, so https holds)
PASS xfp.raster.tilejson+map — tilejson tiles[0]=https://lab-u01.example.test/raster/collections/glad-global-forest-change-1.11/t…; map.html: 200; 2 same-origin URLs, all under https://lab-u01.example.test/raster/; requests ['https://lab-u01.example.test/rast…
PASS xfp.raster.searches — register 200; 4 links under https://lab-u01.example.test/raster/
PASS xfp.vector.links+tilejson+viewer — collections: 7 links under https://lab-u01.example.test/vector/; items: 7 links under https://lab-u01.example.test/vector/; tiles[0]=https://lab-u01.example.test/vector/collections/features.ecoregions/tiles/WebMercatorQ…
PASS xfp.oidc.discovery — endpoints ['https://lab-u01.example.test']; issuer=http://localhost:18888/oidc (ISSUER env, static: chart must set https://lab-uNN.<base>/oidc)
PASS xfp.no-trailing-slash-redirects — {'/stac': '302 /stac/', '/raster': '302 /raster/', '/vector': '302 /vector/', '/oidc': '302 /oidc/', '/browser': '302 /browser/', '/manager': '302 /manager/'}
PASS server.stac:8084/stac — STAC_API_ENDPOINT=http://localhost:8084/stac; landing: 9 links under http://localhost:8084/stac/; search: 11 links under http://localhost:8084/stac/; next -> 200; pystac-client 5 items, collections=['glad-global-forest-change-1.11…
PASS server.stac:8084-unprefixed — http://localhost:8084/collections -> 404 (stac-auth-proxy ROOT_PATH must be in the path; notebooks use http://localhost:8084/stac)
PASS server.stac-fastapi:8081-unprefixed — collections: 17 links under http://localhost:8081/; foreign API-rel links: [('http://www.opengis.net/def/rel/ogc/1.0/queryables', 'stac.maap-project.org'), ('tilejson', 'titiler-pgstac.maap-project.org')]; search: 7 …
PASS server.raster:8082 — {'http://localhost:8082/raster': '200 tiles[0]=http://localhost:8082/raster/collections/glad-global-forest-… tile 200', 'http://localhost:8082': '200 tiles[0]=http://localhost:8082/raster/collections/glad-global-forest-… tile 200'} (…
PASS server.vector:8083 — {'http://localhost:8083/vector': '200 self=http://localhost:8083/vector/collections/features.ecoregions/items?limit=1', 'http://localhost:8083': '200 self=http://localhost:8083/vector/collections/features.ecoregions/items?limit=1'}
PASS server.to_browser-contract — to_browser(server tile)=http://localhost:18888/raster/collections/glad-global-forest-change-1.… -> 200; vector viewer -> 200; stac collection -> 200
PASS fix.stac-api-docs — with SWAGGER_UI_INIT_OAUTH set, api.html loads its spec from ['/stac/api'] -> 200 openapi=3.1.0
```

## Findings

### A1: STAC Swagger UI under `/stac` loads the Lab's own API (FAIL `stac.api-docs`)

- **What happens:**
  - `GET /stac/api.html` is stac-fastapi's page, passed through by stac-auth-proxy.
  - It tells Swagger UI to fetch its spec from `url: '/api'`, because stac-fastapi doesn't know it sits under `/stac`.
  - In the browser, that resolves to `http://localhost:18888/api`, which is Jupyter's REST API: `{"version": "2.21.1"}`. Swagger UI can't render it.
  - Notebook 03 cells 11 and 34 IFrame exactly this page.
  - `/raster/api.html` and `/vector/api.html` are fine (`url: '/raster/api'`, `'/vector/api'`), and the STAC spec itself is fine at `/stac/api` (`servers: [{"url": "/stac"}]`).

  ```
  $ curl …/stac/api.html      →   url: '/api',
  $ curl …/api  (via the Lab) →   {"version": "2.21.1"}
  ```

- **Why:**
  - stac-auth-proxy v1.2.0 serves its *own* Swagger UI only when `SWAGGER_UI_INIT_OAUTH` is non-empty (`src/stac_auth_proxy/app.py:68-82`).
  - That handler builds the spec URL as `scope["root_path"] + "/api"` (`handlers/swagger_ui.py`), i.e. `/stac/api`.
- **Fix:** add `SWAGGER_UI_INIT_OAUTH: '{"clientId":"stac-api-docs","usePkceWithAuthorizationCodeGrant":true}'` to stac-auth-proxy.
  - Verified on the throwaway proxy (`fix.stac-api-docs`): `api.html` then loads `/stac/api` → 200, `openapi=3.1.0`.
  - It needs a proxy restart, so it wasn't applied to the running stack.
  - Behind an ingress the spec URL stays relative, so it stays https.

### A2: the Lab's `?token=` collides with STAC's pagination `token` (FAIL `stac.lab-token-in-query`, `stac.pystac-client.token-parameter`)

- **What happens:**
  - Jupyter reads `?token=` as the login token. stac-fastapi reads `?token=` as the pagination cursor.
  - With `?token=<LAB_TOKEN>` on every call (the "laptop" pattern):
    - `/stac/search` and `/stac/collections/{id}/items` return **HTTP 500**.
    - `/stac/` works.
    - `/stac/collections` works but echoes the token into its `self` link (build F1).

  ```
  $ docker logs eoapi-spike-stac-fastapi-1 | grep RaiseError
  asyncpg.exceptions.RaiseError: Could not find item using token: <LAB_TOKEN> item: <LAB_TOKEN> collection: <NULL>
  ```

  The token also lands in stac-fastapi's error log.

- **Following a `next` link without the cookie:**
  - `next` links carry `token=next:…`, so Jupyter treats them as a wrong login and returns 302 to `/login`.
  - Appending the Lab token works only in one order. `…&token=next:…&token=<LAB>` returns 200; `?token=<LAB>&…&token=next:…` returns 302.
  - That's because Tornado takes the **last** `token` and stac-fastapi the **first** (`stac.lab-token-and-next-token`).
- **pystac-client** with `parameters={"token": LAB_TOKEN}`:
  - Paging works with POST search (the default; the cursor travels in the body).
  - It fails with `method="GET"` (`APIError: Internal Server Error`).
- **What works** (all PASS):
  - Log in once, then use the cookie: `stac.pystac-client.cookie`.
  - `pystac_client.Client.open("<lab>/stac/?token=…")`, where the session keeps the cookie from the first response: `stac.pystac-client.token-once`.
  - The browser itself, which has the cookie: `stac.items+next`, `stac.search-get+next`, `stac.search-post+next`.
- **Fix (docs and `deploy.sh verify`, no code):** send `?token=` once, on a non-STAC URL (`/api/status` or `/stac/`), then use the cookie.
  - Never append it to `/stac/search` or `/stac/…/items`.
  - Never pass it as pystac-client `parameters`.
  - This supersedes the skeptic note that `…?token=…` works for laptop reads and writes "with no extra code". That holds only for the first request.

### A3: stac-auth-proxy rewrites query strings without percent-encoding (FAIL `stac.datetime-offset-like-notebook-03`, `stac.collection-search-like-notebook-03`)

- **Trigger:** when `ITEMS_FILTER_CLS` / `COLLECTIONS_FILTER_CLS` is set (chapter 7's `TenantFilter`), stac-auth-proxy v1.2.0 rebuilds the GET query string to append the tenant filter.
  - `Cql2ApplyFilterQueryStringMiddleware` → `utils/filters.py:append_qs_filter`: `parse_qs` decodes the values, keeping only the first value per key.
  - `dict_to_query_string` then joins `f"{key}={val}"` **without re-encoding**.
- **Effects, proven with the same request sent direct to `:8081` (200) and through the proxy (`:8084` and the Lab):**
  - **A `+` becomes a space.** Notebook 03 cells 23 and 28 build `datetime(2025,1,4,tzinfo=UTC).isoformat()` = `…T00:00:00+00:00`, which returns **400 `Invalid RFC3339 datetime.`** With `Z` the same request returns 200. What stac-fastapi received (its access log):

    ```
    "GET /search?datetime=2000-01-04T00:00:00+00:00/..&limit=1&collections=glad-…&filter=(NOT%20(collection%20LIKE%20'private-%'))&filter-lang=cql2-text HTTP/1.1" 400 Bad Request
    "GET /search?datetime=2000-01-04T00%3A00%3A00%2B00%3A00%2F..&limit=1&collections=glad-… HTTP/1.1" 200 OK      # direct :8081
    ```

  - **A `%` followed by two hex digits is decoded a second time.** Notebook 03 cells 15 and 17 filter `id LIKE '%{username}%'`. `'%bal%'` and `'%c1-l2a%'` match **nothing** through the proxy but 1 and 2 collections direct. The failure is silent: 200 with an empty list.
    - Any Haikunator name starting with a hex pair hits it (`ba…`, `ca…`, `da…`, `de…`, `fa…`).
    - `u01-…` ids are safe, because `u` isn't hex.
- **Not caused by the prefix design.** It reproduces on `:8084` (kernel path) as well as through the Lab.
  - PR #35 `docker-compose.yml:96,117-120` uses the same image and filter config, so notebook 03 should fail there too. Not run there.
- **Fixes:**
  - Notebook 03:
    - Cells 23 and 28: `datetime_string = "2025-01-04T00:00:00Z"`, or `.isoformat().replace("+00:00", "Z")`.
    - Cells 15 and 17: filter on the exact id (`id = '{collection_id()}'`), or keep `u01`-style ids.
  - Upstream (stac-auth-proxy): encode the values in `dict_to_query_string` (`urllib.parse.urlencode(params, quote_via=quote)` plus JSON for dicts), and keep repeated keys.

### A4: the baked glad collection carries MAAP's API links (FAIL `stac.collection.no-foreign-api-links`)

- `db/glad_to_sql.py` upserts the MAAP collection JSON as-is. The collection then has:
  - **5 identical `queryables` links to `stac.maap-project.org`**, next to the correct local one;
  - **a `tilejson` link to `titiler-pgstac.maap-project.org`**.
- stac-fastapi's own links (self, root, parent, items, local queryables) are correct.
- In STAC Browser, these send users to MAAP's API and tiler, not their own stack.
- **Items are clean:** 4 own links each. Asset hrefs stay `s3://…`; that's data, and titiler reads it.
- **Fix:** in `glad_to_sql.py`, drop the source links before printing: `coll["links"] = [l for l in coll.get("links", []) if l.get("rel") in ("license", "cite-as")]`. The chart's old loader had the same behaviour.
- The Earth Search items loaded the notebook-02 way also keep data links (`canonical`, `thumbnail`, `via`). That's expected for notebook data and not a finding.

### A5: the notebook 04 NDVI cell fails on titiler-pgstac 3.2.0 (FAIL `raster.s2.ndvi-tile-like-notebook-04`)

- Cell 17 sends `assets=nir&assets=red&asset_as_band=True&expression=(nir - red) / (nir + red)`.
  - That returns **400 `Invalid band/asset name 'nir'`** on tile and point.
  - The image ships rio-tiler 9.4.4 and titiler.core 2.3.0. `nir_b1` is rejected too.
- `assets=nir&assets=red&expression=(b1 - b2) / (b1 + b2)` returns **200**.
  - Its point value is +0.50 over vegetation, which confirms b1 = nir and b2 = red.
- It isn't prefix-related: PR #35 compose uses the same `titiler-pgstac:3.2.0` (`docker-compose.yml:130`).
- **Fix:** notebook 04 cell 17 should use the `b1/b2` form, and drop `asset_as_band`.

### A6: `maxsize` is silently ignored (FAIL `raster.external.preview-size-like-notebook-04`)

- titiler.core 2.x names the preview parameter `max_size`.
- Notebook 04 cells 23, 25, 27 and 29 pass `maxsize=2048` and get the default 1024×1024. `max_size=2048` gives 2048×2048.
- **Fix:** rename the parameter in notebook 04.

## What else the run showed (all PASS)

- **jsp `absolute_url=True` and each app's root path agree.** `/raster/`, `/vector/` and `/stac/` docs and specs carry the prefix (`servers: [{"url": "/raster"}]`, etc.). A missing trailing slash (`/stac`, `/raster`, …) returns 302 to `/<prefix>/`, and the redirect stays relative behind https.
- **Configured URLs, not request-derived.** These don't follow the request host, so the chart has to template them per participant:
  - the STAC `auth:schemes.oidc.openIdConnectUrl` (stac-auth-proxy `OIDC_DISCOVERY_URL`);
  - the mock-oidc `issuer` (`ISSUER`).

  For lab-u01 these become `https://lab-u01.<base>/oidc/…`. mock-oidc's *endpoints* (authorize, token, jwks) do follow the request host and become `https://`.
- **Third-party hosts the viewers load in the browser.** Participants' browsers need these on the venue network:
  - `unpkg.com`: Leaflet, proj4 and protomaps in titiler `map.html` and the tipg viewer.
  - `cdnjs.cloudflare.com`: jQuery, Leaflet and Bootstrap CSS in the tipg HTML.
  - `cdn.jsdelivr.net`: swagger-ui.
  - `files.dnr.state.mn.us`: `bootstrap.min.js` in every tipg HTML page, from the upstream tipg 1.6.1 template.
  - Basemaps from `server.arcgisonline.com` and `tile.openstreetmap.org`.

  Every script and stylesheet returned 200 when fetched from the pod.
- **Timing.** Through the Lab, single tiles took 0.5–2.4 s with cold GDAL caches (glad from `s3://nasa-maap-data-store`, Sentinel-2 from `e84-earth-search-sentinel-data`). Loading the 30 Earth Search items with pypgstac took a few seconds. The whole `run.sh` takes about 25 s.

## Notes for other topics

- **auth.** The query re-encoding in A3 also turns an encoded `%26` inside a value into a real `&` upstream. For example, `ids=x%26filter%3D…` reached stac-fastapi as `ids=x&filter=…&filter=<tenant filter>`.
  - stac-fastapi uses the **last** `filter` (checked direct on `:8081`), and the proxy appends the tenant filter last, so **no bypass was found**.
  - Not explored further. Keep it out of public text until a skeptic has looked at it.
- **laptop access.** See A2 for the token rule.

## Not tested

- A real browser (JavaScript execution, Leaflet drawing the tiles, Swagger UI rendering). Pages were checked by parsing what they request and fetching it.
- Real TLS: only the ingress headers were simulated.
- Load.
- Notebook cells were reproduced as requests. The notebooks themselves were not executed.
