"""The participant's laptop: a throwaway container that does NOT share the Lab
netns and reaches the published port via host.docker.internal:18888, the way
a browser, QGIS or local pystac-client would. Prepended with common.py.
"""

import math

from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO

LAB = "http://host.docker.internal:18888"
T = {"token": TOKEN}

# ---- 1. no credentials -> login or 403, never content ----
gate_checks(LAB, "laptop")


# ---- 2. reads with ?token= ----
def search(cl, method):
    s = cl.search(collections=[GLAD], limit=10, max_items=35, method=method)
    ids = [i.id for i in s.items()]
    return ids, [c.name for c in cl._stac_io.session.cookies]


for method in ("GET", "POST"):
    @check(f"laptop.pystac-client.url-token.{method}")
    def _():
        # Documented laptop recipe: ?token= on the root URL, then requests.Session's cookie.
        ids, cookies = search(Client.open(f"{LAB}/stac/?token={TOKEN}"), method)
        return len(ids) == 35 and len(set(ids)) == 35 and cookies, \
            f"35 items over 4 pages (limit=10): got {len(ids)} unique={len(set(ids))}; session cookies={cookies}"

    @check(f"laptop.pystac-client.parameters-token.{method}")
    def _():
        # parameters= adds ?token=<lab token> to EVERY request, search included.
        try:
            ids, _ = search(Client.open(f"{LAB}/stac/", parameters=T), method)
            return len(set(ids)) == 35, f"got {len(ids)} items, unique={len(set(ids))}"
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:120]} (pgstac reads ?token= as its pagination cursor)"


@check("laptop.stac.get-with-lab-token")
def _():
    # The query parameter name `token` is shared by Jupyter (login) and pgstac (paging).
    c = httpx.Client(timeout=30)
    out = {p: c.get(f"{LAB}{p}", params={**T, "limit": 1}).status_code
           for p in ["/stac/search", f"/stac/collections/{GLAD}/items", "/stac/collections", "/stac/"]}
    paged = [out["/stac/search"], out[f"/stac/collections/{GLAD}/items"]]
    return all(v == 200 for v in paged), \
        f"{out} — stac-fastapi log: 'Could not find item using token: <LAB_TOKEN>'"


@check("laptop.titiler.tile")
def _():
    c = httpx.Client(timeout=120)
    tj = c.get(f"{LAB}/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json",
               params={**T, "assets": "gain"})
    lon, lat = -175.0, 75.0  # centre of the item bbox [-180, 70, -170, 80]
    z = 6
    x = int((lon + 180) / 360 * 2**z)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**z)
    url = tj.json()["tiles"][0].format(z=z, x=x, y=y)
    tile = httpx.get(url, timeout=120)  # a cookieless client, e.g. QGIS XYZ layer
    bare = httpx.get(url.split("?")[0] + "?assets=gain", timeout=30)
    return tj.status_code == 200 and tile.status_code == 200 and tile.headers["content-type"].startswith("image/") \
        and bare.status_code == 302, \
        f"tilejson={tj.status_code}; tile {z}/{x}/{y} from the tilejson URL, no cookie: {tile.status_code} " \
        f"{tile.headers.get('content-type')} {len(tile.content)} B (URL carries ?token= from the tilejson); " \
        f"same tile without token: {bare.status_code}"


@check("laptop.tipg.items")
def _():
    c = httpx.Client(timeout=30)
    r = c.get(f"{LAB}/vector/collections/features.ecoregions/items", params={**T, "limit": 5})
    nxt = next(l["href"] for l in r.json()["links"] if l["rel"] == "next")
    r2 = c.get(nxt)
    a = [f["id"] for f in r.json()["features"]]
    b = [f["id"] for f in r2.json()["features"]]
    return r.status_code == 200 and r2.status_code == 200 and a != b and len(b) == 5, \
        f"page1={r.status_code} ids={a}; next link={r2.status_code} ids={b}"


@check("laptop.token-echo")
def _():
    # Build F1 extended: where does ?token=<lab token> come back in a response body?
    c = httpx.Client(timeout=60)
    probes = {
        "stac POST /search next.href": c.post(f"{LAB}/stac/search", params=T, json={"limit": 1}),
        "stac /collections self": c.get(f"{LAB}/stac/collections", params=T),
        "raster tilejson tiles[]": c.get(
            f"{LAB}/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json",
            params={**T, "assets": "gain"}),
        "vector items self/next": c.get(f"{LAB}/vector/collections/features.ecoregions/items",
                                        params={**T, "limit": 1}),
        "stac /stac -> /stac/ Location": c.get(f"{LAB}/stac", params=T, follow_redirects=False),
    }
    leaks = [k for k, r in probes.items() if TOKEN in r.text or TOKEN in r.headers.get("location", "")]
    return not leaks, f"Lab token echoed in: {leaks}" if leaks else "no echo"


# ---- 3. a write from the laptop: ?token= for the Lab + Bearer for stac-auth-proxy ----
CID = "spike-auth-test"


@check("laptop.write.token+bearer")
def _():
    c = httpx.Client(timeout=30)
    jwt = mint(f"{LAB}/oidc", username="spike-auth-laptop", client=c, params=T)
    c.delete(f"{LAB}/stac/collections/{CID}", params=T, headers=bearer(jwt))  # leftovers
    post = c.post(f"{LAB}/stac/collections", params=T, headers=bearer(jwt), json=collection(CID))
    get = c.get(f"{LAB}/stac/collections/{CID}", params=T)
    dele = c.delete(f"{LAB}/stac/collections/{CID}", params=T, headers=bearer(jwt))
    gone = c.get(f"{LAB}/stac/collections/{CID}", params=T)
    return post.status_code in (200, 201) and get.status_code == 200 and dele.status_code in (200, 204) \
        and gone.status_code == 404, \
        f"mint via /oidc/?token= ok; POST={post.status_code} GET={get.status_code} " \
        f"DELETE={dele.status_code} GET-after={gone.status_code} ({CID})"


@check("laptop.write.cookie+bearer")
def _():
    # No ?token= on the write: Jupyter tries the Bearer JWT as a Lab token,
    # it does not match, so it falls back to the cookie (identity.py _get_user).
    c = httpx.Client(timeout=30)
    c.get(f"{LAB}/stac/", params=T)
    jwt = mint(f"{LAB}/oidc", username="spike-auth-laptop", client=c)
    cid = f"{CID}-cookie"
    post = c.post(f"{LAB}/stac/collections", headers=bearer(jwt), json=collection(cid))
    dele = c.delete(f"{LAB}/stac/collections/{cid}", headers=bearer(jwt))
    return post.status_code in (200, 201) and dele.status_code in (200, 204), \
        f"cookie={list(c.cookies.keys())} POST={post.status_code} DELETE={dele.status_code} ({cid})"


@check("laptop.write.refusals")
def _():
    c = httpx.Client(timeout=30)
    jwt = mint(f"{LAB}/oidc", username="spike-auth-laptop", client=c, params=T)
    ro = mint(f"{LAB}/oidc", scopes="openid profile stac:read", username="spike-auth-laptop", client=c, params=T)
    body = collection(f"{CID}-refused")
    fresh = httpx.Client(timeout=30)
    out = {
        "Bearer only, no Lab login": fresh.post(f"{LAB}/stac/collections", headers=bearer(jwt), json=body),
        "?token= only, no Bearer": fresh.post(f"{LAB}/stac/collections", params=T, json=body),
        "?token= + stac:read-only Bearer": fresh.post(f"{LAB}/stac/collections", params=T,
                                                      headers=bearer(ro), json=body),
    }
    want = {"Bearer only, no Lab login": 403, "?token= only, no Bearer": 401,
            "?token= + stac:read-only Bearer": 403}
    return all(out[k].status_code == v for k, v in want.items()), \
        " ".join(f"[{k}]={r.status_code}" for k, r in out.items()) + \
        " (403 #1 is Jupyter, 401/403 #2/#3 are stac-auth-proxy)"


# ---- 4. Authorization: token <lab token> passes Jupyter, then stac-auth-proxy 401s it ----
@check("laptop.header-token.stac")
def _():
    out = {}
    for scheme in ("token", "Bearer"):
        r = httpx.get(f"{LAB}/stac/collections", headers={"Authorization": f"{scheme} {TOKEN}"}, timeout=30)
        out[scheme] = (r.status_code, r.json().get("detail") if r.status_code == 401 else "")
    return out["token"][0] == 401 and out["Bearer"][0] == 401, \
        f"'Authorization: token <LAB_TOKEN>' -> {out['token']}; 'Authorization: Bearer <LAB_TOKEN>' -> {out['Bearer']}" \
        " (Jupyter accepted both; the 401 bodies are stac-auth-proxy's)"


@check("laptop.header-token.other-prefixes")
def _():
    h = {"Authorization": f"token {TOKEN}"}
    out = {p: httpx.get(f"{LAB}{p}", headers=h, timeout=30).status_code
           for p in ["/raster/healthz", "/vector/collections", "/browser/", "/manager/",
                     "/oidc/.well-known/openid-configuration"]}
    return all(v == 200 for v in out.values()), f"{out} — only /stac rejects a non-Bearer header"


# ---- 6. mock-oidc only behind the Lab login ----
@check("laptop.oidc.mint-without-session")
def _():
    c = httpx.Client(timeout=30, follow_redirects=False)
    form = {"username": "spike-auth-anon", "scopes": "openid stac:write", "claims": "{}"}
    out = {
        "POST /oidc/": c.post(f"{LAB}/oidc/", data=form),
        "POST /oidc/token": c.post(f"{LAB}/oidc/token", data={"grant_type": "authorization_code", "code": "x"}),
        "GET /oidc/authorize": c.get(f"{LAB}/oidc/authorize", params={
            "client_id": "stac-browser", "response_type": "code", "scope": "openid stac:write",
            "redirect_uri": "http://localhost:18888/browser/auth", "state": "s"}),
        "GET jwks": c.get(f"{LAB}/oidc/.well-known/jwks.json"),
    }
    return all(blocked(r) for r in out.values()), \
        " ".join(f"[{k}]={r.status_code}" for k, r in out.items()) + "; no JWT in any body"


@check("laptop.oidc.mint-with-session")
def _():
    c = httpx.Client(timeout=30)
    c.get(f"{LAB}/stac/", params=T)  # Lab login cookie
    jwt = mint(f"{LAB}/oidc", username="spike-auth-laptop", client=c)
    return jwt.count(".") == 2, "with the Lab cookie, POST /oidc/ returns a JWT (positive control)"
