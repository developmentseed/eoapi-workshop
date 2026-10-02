"""The three APIs under their prefixes, through the Lab (jupyter-server-proxy).

Runs INSIDE the lab container (`docker exec -i eoapi-spike-lab-1 /entrypoint.sh
python - < apis.py`), so `localhost` is the pod netns and http://localhost:18888
is the browser URL. Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>.

Groups:
  stac.* raster.* vector.*  the browser path: http://localhost:18888/<prefix>/...
                            with the Lab cookie (one ?token= to log in, as a browser)
  xfp.*                     the same, with the headers a TLS-terminating ingress
                            sends (Host, X-Forwarded-Proto/Host/Port, X-Scheme)
  server.*                  the kernel path: localhost:8081-8084, prefixed or not
Data created: collection spike-apis-sentinel-2-c1-l2a (items spike-apis-*),
loaded like notebook 02 and removed at the end (KEEP_DATA=1 keeps it).
"""

import json
import math
import os
import re
import sys
import time
import warnings
from datetime import datetime
from urllib.parse import urlencode, urlparse

import httpx

warnings.filterwarnings("ignore")  # rasterio NotGeoreferencedWarning on PNG tiles

LAB = "http://localhost:18888"
TOKEN = os.environ["LAB_TOKEN"]
GLAD = "glad-global-forest-change-1.11"
ECO = "features.ecoregions"
S2 = "spike-apis-sentinel-2-c1-l2a"
S2_BBOX = [-0.75, 44.7, -0.35, 45.0]  # Bordeaux, notebook-02 style (smaller box)
H = "lab-u01.example.test"  # what an ingress would forward for lab-u01.<base>
XF = {
    "Host": H,
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": H,
    "X-Forwarded-Port": "443",
    "X-Scheme": "https",
    "X-Forwarded-For": "203.0.113.7",
    "X-Real-IP": "203.0.113.7",
}
UA = {"User-Agent": "Mozilla/5.0 (spike apis check)"}
RGB = (
    ("assets", "red"),
    ("assets", "green"),
    ("assets", "blue"),
    ("color_formula", "Gamma RGB 3.0 Saturation 1.2 Sigmoidal RGB 15 0.35"),
)
NDVI = (  # notebook 04 cell 17: rio-tiler 9 names bands b1..bN in `assets` order
    ("assets", "nir"),
    ("assets", "red"),
    ("asset_as_band", "True"),
    ("expression", "(b1 - b2) / (b1 + b2)"),
    ("colormap_name", "viridis"),
    ("rescale", "-0.5,1"),
)
COG = (
    "https://nasa-maap-data-store.s3.us-west-2.amazonaws.com/file-staging/nasa-map/"
    "glad-global-forest-change-v1.11/Hansen_GFC-2023-v1.11_lossyear_40N_080W.tif"
)  # notebook 04 §4.4
# rels that describe *this* API; pointing anywhere else is a wrong link
API_RELS = {
    "self", "root", "parent", "collection", "items", "next", "prev", "previous",
    "search", "conformance", "data", "service-desc", "service-doc", "tilejson",
    "http://www.opengis.net/def/rel/ogc/1.0/queryables",
}  # fmt: skip
STATE = {}


def redact(s):
    return str(s).replace(TOKEN, "<LAB_TOKEN>")


def report(status, name, detail):
    print(f"{status} {name} — {redact(detail)[:600]}", flush=True)


def check(name):
    def wrap(fn):
        try:
            res = fn()
            status = res[0] if res[0] in ("PASS", "FAIL", "BLOCKED") else None
            if status is None:
                status = "PASS" if res[0] else "FAIL"
            detail = res[1]
        except Exception as e:  # a crash is a FAIL with the reason
            status, detail = "FAIL", f"{type(e).__name__}: {e}"
        report(status, name, detail)
        return fn

    return wrap


# ---------------------------------------------------------------- clients
browser = httpx.Client(timeout=180)  # one ?token=, then the Lab cookie
_r = browser.get(f"{LAB}/api/status", params={"token": TOKEN})
assert _r.status_code == 200 and browser.cookies, "Lab login with ?token= failed"
COOKIE = "; ".join(f"{k}={v}" for k, v in browser.cookies.items())

# The ingress client: log in once through "the ingress" (cookie name follows the
# Host header; it comes back Secure, so it's sent by hand over this plain hop).
_r = httpx.get(f"{LAB}/api/status", params={"token": TOKEN}, headers=XF, timeout=60)
XF_SETCOOKIE = _r.headers.get_list("set-cookie")
_ck = "; ".join(s.split(";")[0] for s in XF_SETCOOKIE if s.startswith("username-"))
ingress = httpx.Client(timeout=180, headers={**XF, "Cookie": _ck})
kernel = httpx.Client(timeout=180)  # server-side, no Lab in the path


# ---------------------------------------------------------------- helpers
def links(doc):
    """Every link object in a STAC/OGC JSON doc (top level, collections, features)."""
    out = list(doc.get("links", []))
    for key in ("collections", "features"):
        for sub in doc.get(key, []) or []:
            out += links(sub)
    return out


def own_or_bad(lks, base, own_hosts):
    """Split hrefs: under `base`; wrong (our host but not `base`); foreign."""
    good, bad, foreign = [], [], []
    for lk in lks:
        href = lk["href"]
        host = urlparse(href).netloc
        if href == base or href.startswith(base + "/") or href.startswith(base + "?"):
            good.append(lk)
        elif host in own_hosts or host.startswith("localhost"):
            bad.append(lk)
        else:
            foreign.append(lk)
    return good, bad, foreign


def links_ok(doc, base, own_hosts=("localhost:18888",)):
    good, bad, foreign = own_or_bad(links(doc), base, own_hosts)
    api_foreign = [lk for lk in foreign if lk.get("rel") in API_RELS]
    ok = bool(good) and not bad
    det = f"{len(good)} links under {base}/"
    if bad:
        det += f"; WRONG: {[lk['href'] for lk in bad][:4]}"
    if api_foreign:
        det += f"; foreign API-rel links: {sorted({(lk['rel'], urlparse(lk['href']).netloc) for lk in api_foreign})}"
    return ok, det


def next_link(doc):
    return next((lk for lk in doc.get("links", []) if lk.get("rel") == "next"), None)


def ids(doc):
    return [f["id"] for f in doc.get("features", [])]


def xyz(lon, lat, z):
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def png_stats(content):
    from rasterio.io import MemoryFile

    with MemoryFile(content) as m, m.open() as ds:
        arr = ds.read()
    return arr.shape, int((arr[-1] > 0).sum()) if arr.shape[0] in (2, 4) else -1


def tile_ok(client, url, params=None):
    """A rendered tile: 200 and a decodable image. `.png` URLs must be PNG; a
    tilejson template has no extension and titiler picks PNG or JPEG itself."""
    t = time.time()
    r = client.get(url, params=params)
    dt = time.time() - t
    ctype = r.headers.get("content-type", "")
    want = "image/png" if urlparse(str(r.url)).path.endswith(".png") else "image/"
    if r.status_code != 200 or not ctype.startswith(want):
        body = r.text[:200] if ctype.startswith(("text", "application")) else ""
        return False, f"{r.status_code} {ctype} {body!r} ({dt:.1f}s)"
    shape, opaque = png_stats(r.content)
    return (
        opaque != 0,
        f"200 {ctype} {len(r.content)} B, {shape}, opaque px={'n/a' if opaque < 0 else opaque} ({dt:.1f}s)",
    )


ASSET_RES = [  # what the page loads before anything runs
    r"""<script[^>]*\ssrc=["']([^"']+)["']""",
    r"""<link[^>]*\shref=["']([^"']+)["']""",
]
CALL_RES = [  # what its JavaScript requests: tilejson/point fetches, tiles, OpenAPI spec
    r"""fetch\(\s*[`'"]([^`'"]+)[`'"]""",
    r"""tileLayer\(\s*[`'"]([^`'"]+)[`'"]""",
    r"""\burl:\s*[`'"]([^`'"]+)[`'"]""",
]


def found(res, html):
    return list(dict.fromkeys(u for rx in res for u in re.findall(rx, html)))


def html_check(client, url, base, origin, params=None):
    """Load an HTML page as a browser would. Every same-origin URL it requests or
    links to must be under `base`; nothing it requests may be http:// when the
    page is https (mixed content); its external scripts/css must load."""
    r = client.get(url, params=params)
    if r.status_code != 200:
        return False, f"{r.status_code} {r.text[:200]!r}", None
    requested = found(ASSET_RES + CALL_RES, r.text)
    anchors = re.findall(r"""<a[^>]*\shref=["']([^"']+)["']""", r.text)
    own = [
        u
        for u in dict.fromkeys(requested + anchors)
        if u.startswith(origin) or u.startswith("/")
    ]
    path = urlparse(base).path
    wrong = [
        u
        for u in own
        if not (u == base or u.startswith((base + "/", base + "?", path + "/")))
    ]
    insecure = (
        [u for u in requested if u.startswith("http://")]
        if origin.startswith("https")
        else []
    )
    assets = [
        u
        for u in found(ASSET_RES, r.text)
        if u.startswith("https://") and not u.startswith(origin)
    ]
    other = sorted(
        {
            urlparse(u).netloc
            for u in requested
            if u.startswith("https://") and not u.startswith(origin)
        }
    )
    failed = []
    for u in assets:
        try:
            s = httpx.get(u, headers=UA, timeout=30, follow_redirects=True).status_code
        except httpx.HTTPError as e:
            s = type(e).__name__
        if s != 200:
            failed.append((u, s))
    calls = [u for u in own if u in requested]
    ok = bool(own) and not wrong and not insecure and not failed
    det = (
        f"200; {len(own)} same-origin URLs, all under {base}/"
        if not wrong
        else f"200; WRONG prefix: {wrong[:4]}"
    ) + (
        f"; requests {[redact(u)[:100] for u in calls[:3]]}"
        + (f"; MIXED CONTENT: {insecure}" if insecure else "")
        + f"; {len(assets)} external js/css"
        + (f", FAILED: {failed}" if failed else " all 200")
        + f"; third-party hosts {other}"
    )
    return ok, det, (r.text, own)


# ================================================================ STAC /stac
SB = f"{LAB}/stac"


@check("stac.landing")
def _():
    r = browser.get(f"{SB}/")
    j = r.json()
    rels = {lk["rel"] for lk in j["links"]}
    need = {
        "self",
        "root",
        "data",
        "conformance",
        "search",
        "service-desc",
        "service-doc",
    }
    ok, det = links_ok(j, SB)
    return (
        ok and r.status_code == 200 and need <= rels,
        f"{r.status_code}; {det}; rels={sorted(rels)}",
    )


@check("stac.conformance")
def _():
    r = browser.get(f"{SB}/conformance")
    cc = r.json()["conformsTo"]
    need = ["core", "item-search", "collections", "transaction", "filter"]
    miss = [n for n in need if not any(n in c for c in cc)]
    return (
        r.status_code == 200 and not miss,
        f"{r.status_code}; {len(cc)} classes; missing={miss}",
    )


@check("stac.collections")
def _():
    r = browser.get(f"{SB}/collections")
    j = r.json()
    cids = [c["id"] for c in j["collections"]]
    ok, det = links_ok(j, SB)
    return ok and GLAD in cids, f"{r.status_code}; {det}; ids={cids}"


@check("stac.collection")
def _():
    r = browser.get(f"{SB}/collections/{GLAD}")
    ok, det = links_ok(r.json(), SB)
    return ok and r.status_code == 200, f"{r.status_code}; {det}"


@check("stac.collection.no-foreign-api-links")
def _():
    j = browser.get(f"{SB}/collections/{GLAD}").json()
    _, _, foreign = own_or_bad(j["links"], SB, ("localhost:18888",))
    api = [lk for lk in foreign if lk.get("rel") in API_RELS]
    summary = {}
    for lk in api:
        k = (lk["rel"].rsplit("/", 1)[-1], urlparse(lk["href"]).netloc)
        summary[k] = summary.get(k, 0) + 1
    data = sorted(
        {(lk["rel"], urlparse(lk["href"]).netloc) for lk in foreign if lk not in api}
    )
    return not api, (
        f"{GLAD}: {len(api)} links with API rels point at another deployment "
        f"{summary} (baked from the MAAP source collection); data links kept: {data}"
    )


@check("stac.queryables")
def _():
    a = browser.get(f"{SB}/queryables").status_code
    b = browser.get(f"{SB}/collections/{GLAD}/queryables").status_code
    return a == b == 200, f"/queryables={a} /collections/{{id}}/queryables={b}"


@check("stac.items+next")
def _():
    r = browser.get(f"{SB}/collections/{GLAD}/items", params={"limit": 2})
    j = r.json()
    ok, det = links_ok(j, SB)
    nxt = next_link(j)
    r2 = browser.get(nxt["href"])
    page2 = ids(r2.json())
    ok = ok and r2.status_code == 200 and page2 and set(page2).isdisjoint(ids(j))
    return (
        ok,
        f"{det}; next={nxt['href'][len(LAB) :][:90]}… -> {r2.status_code} {len(page2)} new items",
    )


@check("stac.item")
def _():
    j = browser.get(f"{SB}/collections/{GLAD}/items", params={"limit": 1}).json()
    iid = j["features"][0]["id"]
    r = browser.get(f"{SB}/collections/{GLAD}/items/{iid}")
    it = r.json()
    ok, det = links_ok(it, SB)
    schemes = sorted({urlparse(a["href"]).scheme for a in it["assets"].values()})
    return (
        ok and r.status_code == 200,
        f"{r.status_code} {iid}; {det}; asset href schemes={schemes} (data, not rewritten)",
    )


@check("stac.search-get+next")
def _():
    r = browser.get(f"{SB}/search", params={"collections": GLAD, "limit": 2})
    j = r.json()
    ok, det = links_ok(j, SB)
    nxt = next_link(j)
    r2 = browser.get(nxt["href"])
    page2 = ids(r2.json())
    ok = (
        ok
        and nxt["href"].startswith(f"{SB}/search?")
        and r2.status_code == 200
        and set(page2).isdisjoint(ids(j))
    )
    return (
        ok,
        f"{r.status_code}; {det}; next (GET, carries STAC token=next:…) -> {r2.status_code} {len(page2)} new items",
    )


@check("stac.search-post+next")
def _():
    r = browser.post(f"{SB}/search", json={"collections": [GLAD], "limit": 2})
    j = r.json()
    ok, det = links_ok(j, SB)
    nxt = next_link(j)
    r2 = browser.request(nxt["method"], nxt["href"], json=nxt["body"])
    page2 = ids(r2.json())
    ok = (
        ok
        and nxt["method"] == "POST"
        and r2.status_code == 200
        and set(page2).isdisjoint(ids(j))
    )
    return (
        ok,
        f"{r.status_code}; {det}; next=POST {nxt['href'][len(LAB) :]} body.token -> {r2.status_code} {len(page2)} new items",
    )


@check("stac.openapi")
def _():
    r = browser.get(f"{SB}/api")
    j = r.json()
    return r.status_code == 200 and j.get("servers") == [
        {"url": "/stac"}
    ], f"{r.status_code}; servers={j.get('servers')}"


@check("stac.api-docs")
def _():
    # Notebook 03 cells 11 and 34 IFrame {STAC_API_BROWSER_URL}/api.html
    r = browser.get(f"{SB}/api.html")
    spec = re.findall(r"""\burl:\s*'([^']*)'""", r.text)
    target = (
        browser.get(f"{LAB}{spec[0]}") if spec and spec[0].startswith("/") else None
    )
    got = target.text[:60] if target is not None else None
    ok = r.status_code == 200 and spec == ["/stac/api"]
    return ok, (
        f"{r.status_code}; Swagger UI loads its spec from {spec} "
        + (
            ""
            if ok
            else f"= the Lab's own Jupyter API, which answers {got!r}, so Swagger UI cannot render the STAC API"
        )
    )


@check("stac.no-trailing-slash")
def _():
    r = browser.get(SB)  # STAC_API_BROWSER_URL as stored (no trailing slash)
    return r.status_code in (
        200,
        301,
        302,
        307,
        308,
    ), f"GET /stac -> {r.status_code} location={r.headers.get('location')}"


@check("stac.lab-token-in-query")
def _():
    # A laptop tool that sends ?token=<LAB_TOKEN> on every call (no cookie).
    # STAC uses `token` for pagination, so stac-fastapi gets the Lab token.
    out = {}
    for p, params in [
        ("/stac/", {}),
        ("/stac/collections", {}),
        ("/stac/search", {"collections": GLAD, "limit": 1}),
        (f"/stac/collections/{GLAD}/items", {"limit": 1}),
    ]:
        r = httpx.get(f"{LAB}{p}", params={**params, "token": TOKEN}, timeout=60)
        echoed = TOKEN in r.text
        out[p] = f"{r.status_code}{' token-echoed' if echoed else ''}"
    bad = {k: v for k, v in out.items() if not v.startswith("200") or "echoed" in v}
    return (
        not bad,
        f"{out}; /search and /items return 500 (pgstac: 'Could not find item using token: <LAB_TOKEN>')",
    )


@check("stac.lab-token-and-next-token")
def _():
    # Following a STAC next link (token=next:…) without the Lab cookie: Jupyter
    # reads the same `token` param, so the request is unauthenticated.
    j = browser.get(f"{SB}/search", params={"collections": GLAD, "limit": 1}).json()
    nxt = next_link(j)["href"]
    a = httpx.get(nxt, timeout=60)
    b = httpx.get(nxt + f"&token={TOKEN}", timeout=60)
    c = httpx.get(nxt.replace("?", f"?token={TOKEN}&", 1), timeout=60)
    return "PASS" if a.status_code == 302 else "FAIL", (
        f"no cookie: next link -> {a.status_code} (login redirect, expected); "
        f"next&token=LAB -> {b.status_code}; token=LAB&next -> {c.status_code}: "
        "Jupyter takes the LAST `token`, stac-fastapi the FIRST, so only one order works"
    )


@check("stac.pystac-client.cookie")
def _():
    import pystac_client

    cl = pystac_client.Client.open(f"{SB}/", headers={"Cookie": COOKIE})
    cols = [c.id for c in cl.get_all_collections()]
    its = list(cl.search(collections=[GLAD], limit=2, max_items=5).items())
    return (
        len(its) == 5 and GLAD in cols,
        f"collections={cols}; search limit=2 max_items=5 -> {len(its)} items over 3 pages",
    )


@check("stac.pystac-client.token-once")
def _():
    import pystac_client

    cl = pystac_client.Client.open(f"{SB}/?token={TOKEN}")
    its = list(cl.search(collections=[GLAD], limit=2, max_items=5).items())
    return (
        len(its) == 5,
        f"Client.open('<lab>/stac/?token=…') then search paged -> {len(its)} items (cookie from the first response)",
    )


@check("stac.pystac-client.token-parameter")
def _():
    import pystac_client

    out = {}
    for method in ("POST", "GET"):
        try:
            cl = pystac_client.Client.open(f"{SB}/", parameters={"token": TOKEN})
            its = list(
                cl.search(
                    collections=[GLAD], limit=2, max_items=5, method=method
                ).items()
            )
            out[method] = f"{len(its)} items"
        except Exception as e:
            out[method] = f"{type(e).__name__}: {str(e)[:90]}"
    ok = all(v == "5 items" for v in out.values())
    return ok, (
        f"Client.open(…, parameters={{'token': LAB_TOKEN}}) then search: {out}. POST works because the STAC "
        "pagination token travels in the body; GET puts both tokens in the query"
    )


# ================================================================ raster /raster
RB = f"{LAB}/raster"
GLAD_PT = (
    -115.0,
    55.0,
)  # boreal Canada, inside item 60N-120W (first 100 items are 50-80N)


@check("raster.landing")
def _():
    r = browser.get(f"{RB}/")
    ok, det = (
        links_ok(r.json(), RB)
        if "json" in r.headers.get("content-type", "")
        else (r.status_code == 200, r.headers.get("content-type"))
    )
    return ok and r.status_code == 200, f"{r.status_code}; {det}"


@check("raster.api-docs")
def _():
    r = browser.get(f"{RB}/api.html")
    spec = re.findall(r"""\burl:\s*'([^']*)'""", r.text)
    o = browser.get(f"{RB}/api")
    servers = o.json().get("servers")
    return (
        spec == ["/raster/api"] and o.status_code == 200,
        f"api.html {r.status_code} spec={spec}; /raster/api {o.status_code} servers={servers}",
    )


@check("raster.tilejson.glad")
def _():
    r = browser.get(
        f"{RB}/collections/{GLAD}/WebMercatorQuad/tilejson.json",
        params={"assets": "lossyear"},
    )
    t = r.json()["tiles"][0]
    STATE["glad_tiles"] = t
    return r.status_code == 200 and t.startswith(
        f"{RB}/collections/{GLAD}/tiles/"
    ), f"{r.status_code} tiles[0]={t}"


@check("raster.tile.glad")
def _():
    x, y = xyz(*GLAD_PT, 8)
    url = f"{RB}/collections/{GLAD}/tiles/WebMercatorQuad/8/{x}/{y}.png"
    ok, det = tile_ok(
        browser,
        url,
        {"assets": "lossyear", "colormap_name": "viridis", "rescale": "0,23"},
    )
    return ok, f"z8/{x}/{y} {det}"


@check("raster.tile.glad-from-tilejson-template")
def _():
    t = STATE["glad_tiles"]
    x, y = xyz(*GLAD_PT, 9)
    url = t.replace("{z}", "9").replace("{x}", str(x)).replace("{y}", str(y))
    r = browser.get(url)
    return (
        r.status_code == 200 and r.headers["content-type"].startswith("image/"),
        f"{r.status_code} {r.headers.get('content-type')} {len(r.content)} B (tilejson URL as-is)",
    )


@check("raster.point.glad")
def _():
    r = browser.get(
        f"{RB}/collections/{GLAD}/point/{GLAD_PT[0]},{GLAD_PT[1]}",
        params={"assets": "lossyear"},
    )
    return r.status_code == 200, f"{r.status_code} {r.text[:160]}"


@check("raster.map.glad")
def _():
    # notebook 04 cell 31 (IFrame of the map.html URL)
    ok, det, page = html_check(
        browser,
        f"{RB}/collections/{GLAD}/WebMercatorQuad/map.html",
        RB,
        LAB,
        params={"assets": "lossyear"},
    )
    if page:
        tj = [u for u in page[1] if "tilejson.json" in u][0]
        tiles = browser.get(tj).json()["tiles"][0]
        x, y = xyz(*GLAD_PT, 8)
        tok, tdet = tile_ok(
            browser,
            tiles.replace("{z}", "8").replace("{x}", str(x)).replace("{y}", str(y)),
        )
        ok, det = (
            ok and tok and tiles.startswith(RB + "/"),
            det
            + f"; its tilejson -> tiles {tiles[len(LAB) :][:70]}…; one tile: {tdet}",
        )
    return ok, det


@check("raster.searches.glad")
def _():
    # browser path: register through the Lab (POST passes jsp, no XSRF)
    r = browser.post(f"{RB}/searches/register", json={"collections": [GLAD]})
    j = r.json()
    ok, det = links_ok(j, RB)
    sid = j["id"]
    tj = browser.get(
        f"{RB}/searches/{sid}/WebMercatorQuad/tilejson.json",
        params={"assets": "lossyear"},
    ).json()["tiles"][0]
    x, y = xyz(*GLAD_PT, 8)
    tok, tdet = tile_ok(
        browser,
        f"{RB}/searches/{sid}/tiles/WebMercatorQuad/8/{x}/{y}.png",
        {"assets": "lossyear", "colormap_name": "viridis", "rescale": "0,23"},
    )
    return (
        ok and tok and tj.startswith(f"{RB}/searches/{sid}/"),
        f"register {r.status_code}; {det}; tilejson tiles prefixed={tj.startswith(RB + '/')}; tile {tdet}",
    )


# ---- notebook 02 -> 03/04: a participant's sentinel-2 collection
def s2_cleanup():
    import psycopg

    with psycopg.connect("") as conn:
        conn.execute("DELETE FROM pgstac.items WHERE collection = %s", [S2])
        conn.execute("DELETE FROM pgstac.collections WHERE id = %s", [S2])
        conn.execute(
            "DELETE FROM pgstac.searches WHERE search->'collections' ? %s", [S2]
        )


@check("raster.s2.load-like-notebook-02")
def _():
    import pystac_client
    from pypgstac.db import PgstacDB
    from pypgstac.load import Loader, Methods
    from pystac import Collection, Extent, SpatialExtent, TemporalExtent
    from pystac.utils import str_to_datetime

    s2_cleanup()
    try:
        src = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
        t = ["2025-01-01T00:00:00Z", "2025-04-18T00:00:00Z"]
        items = list(
            src.search(
                collections="sentinel-2-c1-l2a", bbox=S2_BBOX, datetime=t, max_items=30
            ).items()
        )
    except Exception as e:
        STATE["s2"] = None
        return (
            "BLOCKED",
            f"Earth Search unreachable from the pod: {type(e).__name__}: {e}",
        )
    coll = Collection(
        id=S2,
        description="spike apis check: notebook-02 style Sentinel-2 L2A collection",
        extent=Extent(
            SpatialExtent([S2_BBOX]),
            TemporalExtent([[str_to_datetime(t[0]), str_to_datetime(t[1])]]),
        ),
    )
    for it in items:
        it.id = f"spike-apis-{it.id}"
        it.set_collection(coll)
    db = PgstacDB()
    loader = Loader(db)
    loader.load_collections([coll.to_dict()], insert_mode=Methods.upsert)
    loader.load_items([it.to_dict() for it in items], insert_mode=Methods.upsert)
    n = db.query_one("SELECT count(*) FROM items WHERE collection = %s", [S2])
    db.close()
    clear = [it for it in items if (it.properties.get("eo:cloud_cover") or 100) < 10]
    STATE["s2"] = {"n": n, "clear": clear}
    return (
        n == len(items) > 0,
        f"{n} items from Earth Search into {S2}; {len(clear)} with eo:cloud_cover < 10",
    )


def s2_needed():
    if not STATE.get("s2"):
        raise RuntimeError(
            "no sentinel-2 collection (see raster.s2.load-like-notebook-02)"
        )
    return STATE["s2"]


def s2_point():
    """A point inside the box AND inside a cloud-free scene, so the filtered
    mosaic has something to draw (the scenes straddle several MGRS tiles)."""
    from shapely.geometry import box, shape

    clear = s2_needed()["clear"]
    area = box(*S2_BBOX)
    if clear:
        area = area.intersection(shape(clear[0].geometry))
    p = area.representative_point()
    return p.x, p.y


@check("stac.s2.search-like-notebook-03")
def _():
    import pystac_client

    s2_needed()
    srv = pystac_client.Client.open(os.environ["STAC_API_ENDPOINT"])  # kernel path
    its = srv.search(
        collections=[S2], datetime=[datetime(2025, 1, 4), None]
    ).item_collection()  # cell 21
    flt = srv.search(
        collections=[S2],
        filter={"op": "lt", "args": [{"property": "eo:cloud_cover"}, 10]},
        max_items=10,
    ).item_collection()  # cell 26
    # cells 28/30 with a Z datetime (upstream.stac-auth-proxy.query-encoding for +00:00)
    r = browser.get(
        f"{SB}/collections/{S2}/items",
        params={
            "datetime": "2025-01-04T00:00:00Z/..",
            "limit": 1000,
            "filter": "eo:cloud_cover < 10",
        },
    )
    j = r.json()
    ok, det = links_ok(j, SB)
    one = (
        browser.get(f"{SB}/collections/{S2}/items/{j['features'][0]['id']}")
        if j.get("features")
        else None
    )
    ok1, det1 = links_ok(one.json(), SB) if one is not None else (False, "no item")
    _, _, foreign = own_or_bad(links(j), SB, ("localhost:18888",))
    return ok and ok1 and len(its) > 0 and r.status_code == 200, (
        f"server-side pystac-client: datetime>=2025-01-04 {len(its)} items, cql2 cloud<10 {len(flt)}; "
        f"browser /items?filter=eo:cloud_cover<10 {r.status_code} {len(j.get('features', []))} items, {det}; "
        f"one item {one.status_code if one is not None else '-'}: {det1}; "
        f"foreign data links={sorted({(lk['rel'], urlparse(lk['href']).netloc) for lk in foreign})[:5]}"
    )


DT = {"+00:00": "2000-01-04T00:00:00+00:00/..", "Z": "2000-01-04T00:00:00Z/.."}
STAC_BASES = {
    "lab": SB,
    "8084": os.environ["STAC_API_ENDPOINT"],
    "8081 direct": "http://localhost:8081",
}


@check("stac.datetime-like-notebook-03")
def _():
    # cells 23 and 28 now send strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {
        label: browser.get(
            f"{b}/search", params={"collections": GLAD, "datetime": DT["Z"], "limit": 1}
        ).status_code
        for label, b in STAC_BASES.items()
    }
    return all(v == 200 for v in out.values()), f"GET /search datetime=...Z/..: {out}"


@check("upstream.stac-auth-proxy.query-encoding.plus")
def _():
    # The notebooks avoid it ('Z'); any other client sending isoformat() still hits it.
    out = {
        label: browser.get(
            f"{b}/search",
            params={"collections": GLAD, "datetime": DT["+00:00"], "limit": 1},
        ).status_code
        for label, b in STAC_BASES.items()
    }
    return all(v == 200 for v in out.values()), (
        f"GET /search datetime=...+00:00/..: {out}. Behind stac-auth-proxy v1.2.0 a '+' reaches stac-fastapi "
        "unencoded and is read as a space -> 400 'Invalid RFC3339 datetime.' (only with ITEMS_FILTER_CLS: "
        "utils/filters.py:dict_to_query_string, no percent-encoding). Upstream bug; notebook 03 uses 'Z'"
    )


def like_counts(pat):
    f = f"id LIKE '{pat}'"
    a = [
        c["id"]
        for c in browser.get(f"{SB}/collections", params={"filter": f}).json()[
            "collections"
        ]
    ]
    b = [
        c["id"]
        for c in kernel.get(
            "http://localhost:8081/collections", params={"filter": f}
        ).json()["collections"]
    ]
    return f"lab={len(a)} direct={len(b)}" + ("" if a == b else " MISMATCH")


@check("stac.collection-search-like-notebook-03")
def _():
    # cells 15 and 17 now filter id LIKE '{workshop_user()}-%': the '%' is followed by
    # "'", never two hex digits, whatever the user name (incl. ones starting ba/c1/de...)
    out = {pat: like_counts(pat) for pat in ["glad-%", "spike-apis-%", "ba-%", "de1-%"]}
    return not any("MISMATCH" in v for v in out.values()), f"{out}"


@check("upstream.stac-auth-proxy.query-encoding.percent")
def _():
    out = {pat: like_counts(pat) for pat in ["%glad%", "%bal%", "%c1-l2a%"]}
    return not any("MISMATCH" in v for v in out.values()), (
        f"{out}; a LIKE pattern with '%<hex><hex>' (e.g. %ba, %c1) is percent-decoded again by stac-auth-proxy "
        "v1.2.0 (same dict_to_query_string cause) and silently matches nothing. Upstream bug; the notebooks no longer use it"
    )


@check("raster.s2.tilejson-like-notebook-04")
def _():
    s2_needed()
    srv = os.environ["TITILER_PGSTAC_API_ENDPOINT"]
    r = kernel.get(
        f"{srv}/collections/{S2}/WebMercatorQuad/tilejson.json?{urlencode(RGB, doseq=True)}"
    )
    t = r.json()["tiles"][0]
    b = browser.get(
        f"{RB}/collections/{S2}/WebMercatorQuad/tilejson.json?{urlencode(RGB, doseq=True)}"
    ).json()["tiles"][0]
    return r.status_code == 200 and t.startswith(f"{srv}/") and b.startswith(
        f"{RB}/"
    ), f"server tiles[0]={t[:90]}…; browser tiles[0]={b[:90]}…"


@check("raster.s2.collection-map+tile")
def _():
    s2_needed()
    ok, det, page = html_check(
        browser,
        f"{RB}/collections/{S2}/WebMercatorQuad/map.html?{urlencode(RGB, doseq=True)}",
        RB,
        LAB,
    )
    x, y = xyz(*s2_point(), 11)
    tok, tdet = tile_ok(
        browser,
        f"{RB}/collections/{S2}/tiles/WebMercatorQuad/11/{x}/{y}.png?{urlencode(RGB, doseq=True)}",
    )
    return ok and tok, f"map.html: {det}; RGB tile z11/{x}/{y}: {tdet}"


@check("raster.s2.mosaic-search-like-notebook-04")
def _():
    s2_needed()
    srv = os.environ["TITILER_PGSTAC_API_ENDPOINT"]
    stac = os.environ["STAC_API_ENDPOINT"]
    bbox = kernel.get(f"{stac}/collections/{S2}").json()["extent"]["spatial"]["bbox"][0]
    r = kernel.post(
        f"{srv}/searches/register",
        json={
            "collections": [S2],
            "bbox": bbox,
            "filter": {"op": "lt", "args": [{"property": "eo:cloud_cover"}, 10]},
        },
    )
    sid = r.json()["id"]
    STATE["s2_search"] = sid
    srv_links = [lk["href"] for lk in r.json()["links"]]
    # cell 14: IFrame f"{titiler_browser_endpoint}/searches/{search_id}/WebMercatorQuad/map.html?…"
    ok, det, page = html_check(
        browser,
        f"{os.environ['TITILER_BROWSER_URL']}/searches/{sid}/WebMercatorQuad/map.html?{urlencode(RGB, doseq=True)}",
        RB,
        LAB,
    )
    x, y = xyz(*s2_point(), 11)
    tok, tdet = tile_ok(
        browser,
        f"{RB}/searches/{sid}/tiles/WebMercatorQuad/11/{x}/{y}.png?{urlencode(RGB, doseq=True)}",
    )
    return ok and tok and all(h.startswith(srv + "/") for h in srv_links), (
        f"register (kernel) {r.status_code} links under {srv}/={all(h.startswith(srv + '/') for h in srv_links)}; "
        f"map.html: {det}; RGB mosaic tile z11/{x}/{y}: {tdet}"
    )


@check("raster.s2.ndvi-tile-like-notebook-04")
def _():
    # cell 17. rio-tiler 9 (titiler-pgstac 3.2.0) names bands b1..bN across the
    # requested assets; asset names are no longer valid in `expression`.
    s2_needed()
    sid = STATE["s2_search"]
    x, y = xyz(*s2_point(), 11)
    url = f"{RB}/searches/{sid}/tiles/WebMercatorQuad/11/{x}/{y}.png"
    ok, det = tile_ok(browser, f"{url}?{urlencode(NDVI, doseq=True)}")
    old = [
        (k, "(nir - red) / (nir + red)" if k == "expression" else v) for k, v in NDVI
    ]
    _, det2 = tile_ok(browser, f"{url}?{urlencode(old, doseq=True)}")
    return (
        ok,
        f"notebook params ('(b1 - b2) / (b1 + b2)'): {det}; the old asset-name expression: {det2}",
    )


# ---- notebook 04 §4.4: /external
@check("raster.external.info+preview")
def _():
    srv = os.environ["TITILER_PGSTAC_API_ENDPOINT"]
    t = time.time()
    i = kernel.get(f"{srv}/external/info", params={"url": COG})
    t1 = time.time() - t
    t = time.time()
    p = kernel.get(
        f"{srv}/external/preview", params={"url": COG, "max_size": 2048}
    )  # cell 23
    t2 = time.time() - t
    shape, _ = png_stats(p.content)
    browser_p = browser.get(
        f"{RB}/external/preview", params={"url": COG, "max_size": 256}
    ).status_code
    return i.status_code == 200 and p.status_code == 200 and browser_p == 200, (
        f"kernel: info {i.status_code} ({t1:.1f}s) width={i.json().get('width')}; "
        f"preview {p.status_code} {p.headers.get('content-type')} {shape} ({t2:.1f}s); through the Lab: preview {browser_p}"
    )


@check("raster.external.preview-size-like-notebook-04")
def _():
    # cells 23/25/27/29 pass max_size=2048 (titiler.core 2.x; the old maxsize is ignored)
    srv = os.environ["TITILER_PGSTAC_API_ENDPOINT"]
    out = {}
    for k in ("maxsize", "max_size"):
        r = kernel.get(
            f"{srv}/external/preview", params={"url": COG, k: 2048, "format": "png"}
        )
        out[k] = png_stats(r.content)[0][1:]
    return out["max_size"] == (
        2048,
        2048,
    ), f"param=2048 -> (h, w): {out}; `maxsize` is silently ignored (default 1024)"


@check("raster.external.map-like-notebook-04")
def _():
    srv = os.environ["TITILER_PGSTAC_API_ENDPOINT"]
    cmap = json.dumps({i: [255, max(0, 255 - 11 * i), 0] for i in range(24)})
    m = kernel.get(
        f"{srv}/external/WebMercatorQuad/map.html",
        params={"url": COG, "colormap": cmap},
    )
    iframe = str(m.url).replace(srv, os.environ["TITILER_BROWSER_URL"])  # cell 29
    ok, det, page = html_check(browser, iframe, RB, LAB)
    if page:
        tj = [u for u in page[1] if "tilejson.json" in u][0]
        tiles = browser.get(tj).json()["tiles"][0]
        x, y = xyz(-75.0, 35.0, 8)  # inside 40N_080W
        tok, tdet = tile_ok(
            browser,
            tiles.replace("{z}", "8").replace("{x}", str(x)).replace("{y}", str(y)),
        )
        ok, det = ok and tok, det + f"; tile {tdet}"
    return ok, det


# ================================================================ vector /vector
VB = f"{LAB}/vector"


@check("vector.landing")
def _():
    r = browser.get(f"{VB}/")
    ok, det = links_ok(r.json(), VB)
    return ok and r.status_code == 200, f"{r.status_code}; {det}"


@check("vector.api-docs")
def _():
    r = browser.get(f"{VB}/api.html")
    spec = re.findall(r"""\burl:\s*'([^']*)'""", r.text)
    o = browser.get(f"{VB}/api")
    return (
        spec == ["/vector/api"] and o.status_code == 200,
        f"api.html {r.status_code} spec={spec}; /vector/api {o.status_code} servers={o.json().get('servers')}",
    )


@check("vector.conformance")
def _():
    r = browser.get(f"{VB}/conformance")
    return (
        r.status_code == 200,
        f"{r.status_code} {len(r.json()['conformsTo'])} classes",
    )


@check("vector.collections")
def _():
    r = browser.get(f"{VB}/collections")
    j = r.json()
    cids = [c["id"] for c in j["collections"]]
    ok, det = links_ok(j, VB)
    return ok and cids == [
        ECO
    ], f"{r.status_code}; {det}; ids={cids} (TIPG_DB_SCHEMAS=[features]: no public.*)"


@check("vector.collection+queryables")
def _():
    r = browser.get(f"{VB}/collections/{ECO}")
    q = browser.get(f"{VB}/collections/{ECO}/queryables")
    ok, det = links_ok(r.json(), VB)
    return (
        ok and q.status_code == 200,
        f"{r.status_code}; {det}; queryables {q.status_code} {len(q.json().get('properties', {}))} props",
    )


@check("vector.items+next")
def _():
    r = browser.get(
        f"{VB}/collections/{ECO}/items", params={"f": "geojson", "limit": 2}
    )
    j = r.json()
    ok, det = links_ok(j, VB)
    nxt = next_link(j)
    r2 = browser.get(nxt["href"])
    page2 = ids(r2.json())
    return (
        ok and r2.status_code == 200 and set(page2).isdisjoint(ids(j)),
        f"{det}; numberMatched={j.get('numberMatched')}; next={nxt['href'][len(LAB) :]} -> {r2.status_code} ids={page2}",
    )


@check("vector.items-variants-like-notebook-05")
def _():
    seq = browser.get(
        f"{VB}/collections/{ECO}/items", params={"f": "geojsonseq", "limit": 2}
    )
    flt = browser.get(
        f"{VB}/collections/{ECO}/items",
        params={"na_l2name": "MEDITERRANEAN CALIFORNIA", "f": "geojson", "limit": 2},
    ).json()
    bb = browser.get(
        f"{VB}/collections/{ECO}/items",
        params={"bbox": "-77,39,-76,40", "f": "geojson", "limit": 2},
    ).json()
    nseq = len(seq.text.strip().splitlines())
    ok = (
        seq.status_code == 200
        and nseq == 2
        and flt["numberMatched"] > 0
        and bb["numberMatched"] > 0
    )
    return (
        ok,
        f"geojsonseq {seq.status_code} {nseq} lines; na_l2name filter matched={flt['numberMatched']}; bbox matched={bb['numberMatched']}",
    )


@check("vector.items-html")
def _():
    # notebook 05 cell 16: IFrame of the f=html items page
    ok, det, _ = html_check(
        browser,
        f"{VB}/collections/{ECO}/items",
        VB,
        LAB,
        params={"bbox": "-77,39,-76,40", "f": "html"},
    )
    return ok, det


@check("vector.tilejson+tile")
def _():
    r = browser.get(f"{VB}/collections/{ECO}/tiles/WebMercatorQuad/tilejson.json")
    t = r.json()["tiles"][0]
    x, y = xyz(-120.0, 37.0, 4)  # California
    tr = browser.get(
        t.replace("{z}", "4").replace("{x}", str(x)).replace("{y}", str(y))
    )
    ok = (
        t.startswith(f"{VB}/collections/{ECO}/tiles/")
        and tr.status_code == 200
        and len(tr.content) > 1000
    )
    return (
        ok,
        f"tiles[0]={t}; z4/{x}/{y} -> {tr.status_code} {tr.headers.get('content-type')} {len(tr.content)} B",
    )


@check("vector.viewer")
def _():
    # notebook 05 cell 25 (and 27 with a filter)
    ok, det, page = html_check(
        browser, f"{VB}/collections/{ECO}/tiles/WebMercatorQuad/map.html", VB, LAB
    )
    if page:
        tj = [u for u in page[1] if "tilejson.json" in u][0]
        r = browser.get(tj)
        ok, det = (
            ok and r.status_code == 200,
            det + f"; its tilejson -> {r.status_code}",
        )
    f_ok, f_det, f_page = html_check(
        browser,
        f"{VB}/collections/{ECO}/tiles/WebMercatorQuad/map.html",
        VB,
        LAB,
        params={"na_l2name": "MEDITERRANEAN CALIFORNIA"},
    )
    ftj = [u for u in f_page[1] if "tilejson.json" in u] if f_page else []
    keeps = bool(ftj) and "na_l2name" in ftj[0]
    return ok and f_ok, det + f"; filtered viewer tilejson keeps the filter={keeps}"


# ================================================================ behind a TLS ingress
XB = f"https://{H}"


@check("xfp.lab-cookie-secure")
def _():
    secure = any("Secure" in s for s in XF_SETCOOKIE)
    return (
        secure,
        f"Set-Cookie under X-Forwarded-Proto: https has Secure={secure} (trust_xheaders)",
    )


@check("xfp.stac.links")
def _():
    out, ok = {}, True
    for p, kw in [
        ("/", {}),
        ("/collections", {}),
        (f"/collections/{GLAD}", {}),
        (f"/collections/{GLAD}/items", {"params": {"limit": 2}}),
        ("/search", {"params": {"collections": GLAD, "limit": 2}}),
    ]:
        r = ingress.get(f"{LAB}/stac{p}", **kw)
        o, d = links_ok(r.json(), f"{XB}/stac", (H,))
        out[p] = f"{r.status_code} {'ok' if o else d}"
        ok = ok and o and r.status_code == 200
    r = ingress.post(f"{LAB}/stac/search", json={"collections": [GLAD], "limit": 2})
    o, d = links_ok(r.json(), f"{XB}/stac", (H,))
    nxt = next_link(r.json())["href"]
    out["POST /search"] = f"{r.status_code} {'ok' if o else d} next={nxt}"
    return ok and o, f"all links https://{H}/stac/…: {out}"


@check("xfp.stac.static-urls")
def _():
    j = ingress.get(f"{LAB}/stac/").json()
    u = j["auth:schemes"]["oidc"]["openIdConnectUrl"]
    return "PASS", (
        f"auth:schemes openIdConnectUrl={u} is config (OIDC_DISCOVERY_URL), not derived from the request: "
        "the chart must set it per participant to https://lab-uNN.<base>/oidc/.well-known/openid-configuration"
    )


@check("xfp.stac.api-docs")
def _():
    r = ingress.get(f"{LAB}/stac/api")
    return (
        r.status_code == 200 and r.json().get("servers") == [{"url": "/stac"}],
        f"/stac/api {r.status_code} servers={r.json().get('servers')} (relative, so https holds)",
    )


@check("xfp.raster.tilejson+map")
def _():
    t = ingress.get(
        f"{LAB}/raster/collections/{GLAD}/WebMercatorQuad/tilejson.json",
        params={"assets": "lossyear"},
    ).json()["tiles"][0]
    ok, det, _ = html_check(
        ingress,
        f"{LAB}/raster/collections/{GLAD}/WebMercatorQuad/map.html",
        f"{XB}/raster",
        XB,
        params={"assets": "lossyear"},
    )
    return ok and t.startswith(
        f"{XB}/raster/"
    ), f"tilejson tiles[0]={t[:80]}…; map.html: {det}"


@check("xfp.raster.searches")
def _():
    r = ingress.post(f"{LAB}/raster/searches/register", json={"collections": [GLAD]})
    ok, det = links_ok(r.json(), f"{XB}/raster", (H,))
    return ok, f"register {r.status_code}; {det}"


@check("xfp.vector.links+tilejson+viewer")
def _():
    a, da = links_ok(
        ingress.get(f"{LAB}/vector/collections").json(), f"{XB}/vector", (H,)
    )
    b, db = links_ok(
        ingress.get(
            f"{LAB}/vector/collections/{ECO}/items", params={"limit": 2}
        ).json(),
        f"{XB}/vector",
        (H,),
    )
    t = ingress.get(
        f"{LAB}/vector/collections/{ECO}/tiles/WebMercatorQuad/tilejson.json"
    ).json()["tiles"][0]
    c, dc, _ = html_check(
        ingress,
        f"{LAB}/vector/collections/{ECO}/tiles/WebMercatorQuad/map.html",
        f"{XB}/vector",
        XB,
    )
    return a and b and c and t.startswith(
        f"{XB}/vector/"
    ), f"collections: {da}; items: {db}; tiles[0]={t}; viewer: {dc}"


@check("xfp.oidc.discovery")
def _():
    j = ingress.get(f"{LAB}/oidc/.well-known/openid-configuration").json()
    eps = {k: v for k, v in j.items() if k.endswith("_endpoint") or k == "jwks_uri"}
    ok = all(v.startswith(f"{XB}/oidc/") for v in eps.values())
    return (
        ok,
        f"endpoints {sorted(set(urlparse(v).scheme + '://' + urlparse(v).netloc for v in eps.values()))}; issuer={j['issuer']} (ISSUER env, static: chart must set https://lab-uNN.<base>/oidc)",
    )


@check("xfp.no-trailing-slash-redirects")
def _():
    out = {}
    for p in ["/stac", "/raster", "/vector", "/oidc", "/browser", "/manager"]:
        r = ingress.get(f"{LAB}{p}")
        out[p] = f"{r.status_code} {r.headers.get('location', '')}"
    bad = {k: v for k, v in out.items() if "http://" in v}
    return not bad, f"{out}" + (f"; http:// redirect under https: {bad}" if bad else "")


# ================================================================ server-side (kernel)
@check("server.stac:8084/stac")
def _():
    import pystac_client

    e = os.environ["STAC_API_ENDPOINT"]
    a, da = links_ok(kernel.get(f"{e}/").json(), e, ("localhost:8084",))
    j = kernel.get(f"{e}/search", params={"collections": GLAD, "limit": 2}).json()
    b, db = links_ok(j, e, ("localhost:8084",))
    r2 = kernel.get(next_link(j)["href"])
    cl = pystac_client.Client.open(e)
    its = list(cl.search(collections=[GLAD], limit=2, max_items=5).items())
    cols = [c.id for c in cl.get_all_collections()]
    return (
        a and b and r2.status_code == 200 and len(its) == 5,
        f"STAC_API_ENDPOINT={e}; landing: {da}; search: {db}; next -> {r2.status_code}; pystac-client {len(its)} items, collections={cols}",
    )


@check("server.stac:8084-unprefixed")
def _():
    r = kernel.get("http://localhost:8084/collections")
    return (
        r.status_code == 404,
        f"http://localhost:8084/collections -> {r.status_code} (stac-auth-proxy ROOT_PATH must be in the path; notebooks use {os.environ['STAC_API_ENDPOINT']})",
    )


@check("server.stac-fastapi:8081-unprefixed")
def _():
    e = "http://localhost:8081"
    ok, det = links_ok(kernel.get(f"{e}/collections").json(), e, ("localhost:8081",))
    j = kernel.get(f"{e}/search", params={"collections": GLAD, "limit": 1}).json()
    ok2, det2 = links_ok(j, e, ("localhost:8081",))
    return (
        ok and ok2,
        f"collections: {det}; search: {det2} (bypasses stac-auth-proxy: used by nothing in the notebooks)",
    )


@check("server.raster:8082")
def _():
    out, ok = {}, True
    for e in ["http://localhost:8082/raster", "http://localhost:8082"]:
        r = kernel.get(
            f"{e}/collections/{GLAD}/WebMercatorQuad/tilejson.json",
            params={"assets": "lossyear"},
        )
        t = r.json()["tiles"][0]
        x, y = xyz(*GLAD_PT, 8)
        s = kernel.get(
            t.replace("{z}", "8").replace("{x}", str(x)).replace("{y}", str(y))
        ).status_code
        out[e] = f"{r.status_code} tiles[0]={t[:60]}… tile {s}"
        ok = (
            ok
            and r.status_code == 200
            and t.startswith("http://localhost:8082/raster/")
            and s == 200
        )
    return ok, f"{out} (unprefixed requests still get /raster links: root_path)"


@check("server.vector:8083")
def _():
    out, ok = {}, True
    for e in ["http://localhost:8083/vector", "http://localhost:8083"]:
        r = kernel.get(f"{e}/collections/{ECO}/items", params={"limit": 1})
        self_ = [lk["href"] for lk in r.json()["links"] if lk["rel"] == "self"][0]
        out[e] = f"{r.status_code} self={self_}"
        ok = (
            ok
            and r.status_code == 200
            and self_.startswith("http://localhost:8083/vector/")
        )
    return ok, str(out)


@check("server.to_browser-contract")
def _():
    sys.path.insert(0, "/home/jovyan/docs")
    from workshop_setup import endpoints, to_browser

    e = endpoints()
    t = kernel.get(
        f"{e['raster']['server']}/collections/{GLAD}/WebMercatorQuad/tilejson.json",
        params={"assets": "lossyear"},
    ).json()["tiles"][0]
    x, y = xyz(*GLAD_PT, 8)
    b = to_browser(t).replace("{z}", "8").replace("{x}", str(x)).replace("{y}", str(y))
    v = to_browser(
        f"{e['vector']['server']}/collections/{ECO}/tiles/WebMercatorQuad/map.html"
    )
    s = to_browser(f"{e['stac']['server']}/collections/{GLAD}")
    rs = [browser.get(u).status_code for u in (b, v, s)]
    return (
        rs == [200, 200, 200] and b.startswith(RB + "/"),
        f"to_browser(server tile)={b[:70]}… -> {rs[0]}; vector viewer -> {rs[1]}; stac collection -> {rs[2]}",
    )


# ---------------------------------------------------------------- cleanup
if os.getenv("KEEP_DATA") != "1":
    try:
        s2_cleanup()
    except Exception as e:
        report("FAIL", "cleanup", f"{type(e).__name__}: {e}")
