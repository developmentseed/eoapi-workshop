"""Direct probes for the two pre-existing problems the notebooks hit (run in the Lab).
The notebooks now work around both (docs/ 03[23]/[28] send 'Z', 04[17] uses b1/b2).

upstream.* FAIL = the upstream bug still reproduces; probe.* = what the notebooks send.

1. stac-auth-proxy 1.2.0, with the row-level filter on (ITEMS_FILTER_CLS, as in the
   repo's docker-compose.yml), rebuilds the query string without percent-encoding
   (utils/filters.py dict_to_query_string): %2B in `+00:00` reaches stac-fastapi as "+",
   i.e. a space. 03[23] and 03[28] send `datetime.isoformat()`, which has `+00:00`.
2. titiler-pgstac 3.2.0 / rio-tiler 9.4.4 renames bands b1..bN before applying the
   expression (rio_tiler/io/base.py `img.band_names = [f"b{ix + 1}" ...]`), so 04[17]'s
   `(nir - red) / (nir + red)` is rejected on every tile.
"""

import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report import tile_of  # noqa: E402

PROXY = os.environ["STAC_API_ENDPOINT"]  # http://localhost:8084/stac
DIRECT = "http://localhost:8081"  # stac-fastapi, upstream of the proxy (in-pod only)
RASTER = os.environ["TITILER_PGSTAC_API_ENDPOINT"]  # http://localhost:8082/raster
GLAD = "glad-global-forest-change-1.11"  # baked into the DB image
S2 = "spike-notebooks-sentinel-2-c1-l2a"  # created by 02 in the docs phase


def say(ok, name, detail):
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}"[:400], flush=True)


def body(r):
    return r.text[:90].replace("\n", " ")


c = httpx.Client(timeout=120)

# 06-08's helper without the legacy STAC_AUTH_PROXY_ENDPOINT (the Lab env still sets it)
sys.dont_write_bytecode = True  # /home/jovyan/docs is the bind-mounted repo
sys.path.insert(0, "/home/jovyan/docs")
legacy = os.environ.pop("STAC_AUTH_PROXY_ENDPOINT", None)
from stac_auth import auth_headers, get_mock_oidc_token, require_local_auth_stack  # noqa: E402

stac, _ = require_local_auth_stack()
r = c.get(f"{stac}/collections", headers=auth_headers(get_mock_oidc_token()))
say(
    r.status_code == 200,
    "probe.stac-auth-without-legacy-env",
    f"STAC_AUTH_PROXY_ENDPOINT unset (was {'set' if legacy else 'unset'}): stac_auth -> {stac}, "
    f"token + GET /collections -> {r.status_code}",
)

for label, dt in (
    ("plus", "2000-01-01T00:00:00+00:00/.."),
    ("Z", "2000-01-01T00:00:00Z/.."),
):
    for where, base in (("proxy", PROXY), ("direct", DIRECT)):
        for path in (f"/collections/{GLAD}/items", "/search"):
            params = {"datetime": dt, "limit": 1}
            if path == "/search":
                params["collections"] = GLAD
            r = c.get(base + path, params=params)
            kind = (
                "upstream.stac-auth-proxy.query-encoding"
                if (label, where) == ("plus", "proxy")
                else f"probe.stac-datetime-{label}.{where}"
            )
            say(
                r.status_code == 200,
                f"{kind}.{path.rsplit('/', 1)[1]}",
                f"GET {base}{path} datetime={dt} (sent as {r.request.url.query.decode()[:60]}) -> {r.status_code} {body(r)}",
            )

# 04[31]'s glad map: report.py's tile at the global center is 204 (no item there), so
# also ask for a tile inside one glad item, as a browser panning to the data would.
item = c.get(f"{PROXY}/collections/{GLAD}/items", params={"limit": 1}).json()[
    "features"
][0]
w, s, e, n = item["bbox"]
gtj = c.get(
    f"{RASTER}/collections/{GLAD}/WebMercatorQuad/tilejson.json",
    params={"assets": "lossyear"},
).json()
gtile = tile_of(dict(gtj, bounds=[w, s, e, n], minzoom=6, maxzoom=6)).split("?")[0]
r = c.get(
    gtile, params={"assets": "lossyear", "colormap_name": "viridis", "rescale": "0,24"}
)
say(
    r.status_code == 200,
    "probe.glad-tile-in-item",
    f"{item['id']} bbox {[round(v) for v in item['bbox']]}: {gtile[len(RASTER) :]} -> "
    f"{r.status_code} {r.headers.get('content-type')} {len(r.content)} B in "
    f"{r.elapsed.total_seconds():.1f}s {'' if r.status_code == 200 else body(r)}",
)

tj = c.get(
    f"{RASTER}/collections/{S2}/WebMercatorQuad/tilejson.json", params={"assets": "red"}
)
if tj.status_code != 200:
    print(
        f"BLOCKED probe.titiler-expression — {S2} has no tilejson ({tj.status_code}); run the docs phase first"
    )
    sys.exit(0)
tile = tile_of(tj.json()).split("?")[0]
res = {}
for label, expr in (
    ("asset-names", "(nir - red) / (nir + red)"),
    ("b1-b2", "(b1 - b2) / (b1 + b2)"),
):
    params = [
        ("assets", "nir"),
        ("assets", "red"),
        ("asset_as_band", "True"),
        ("expression", expr),
        ("colormap_name", "viridis"),
        ("rescale", "-0.5,1"),
    ]
    res[label] = r = c.get(tile, params=params)
    res[label + "-detail"] = (
        f"expression={expr} -> {r.status_code} {r.headers.get('content-type')} "
        f"in {r.elapsed.total_seconds():.1f}s {'' if r.status_code == 200 else body(r)}"
    )
# rio-tiler 9 renamed the bands (an API change, not a bug): 04[17] now sends b1/b2
say(
    res["b1-b2"].status_code == 200,
    "probe.titiler-expression-b1-b2",
    f"{tile[len(RASTER) :]} {res['b1-b2-detail']}; the old asset-name form: {res['asset-names-detail']}",
)
