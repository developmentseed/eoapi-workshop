"""z2jh front door, checked through the URL a browser on this Mac opens.

Runs in a throwaway container with hub.spike.local -> host-gateway (run.sh), so
http://hub.spike.local:18080 goes through the host's published port, the kind
ingress, the hub's proxy, and the participant's Lab, like a browser.
Passwords come from the environment (U01_PASSWORD, U02_PASSWORD) and are never
printed. Prints: PASS|FAIL <name> — <detail>
"""

import json
import os
import re
import time

import httpx

ORIGIN = "http://hub.spike.local:18080"
USERS = ["u01", "u02"]
GLAD = "glad-global-forest-change-1.11"
GLAD_ITEM = "hansen-gfc-2023-v1.11-80N-180W"
PW = {u: os.environ[f"{u.upper()}_PASSWORD"] for u in USERS}
JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
QS = re.compile(r"((?:code|state|token|_xsrf)=)[^&\s\"']+")


def redact(s):
    for v in PW.values():
        s = s.replace(v, "<password>")
    return QS.sub(r"\1<redacted>", JWT.sub("<jwt>", s))


def check(name):
    def wrap(fn):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"[:300]
        print(redact(f"{'PASS' if ok else 'FAIL'} {name} — {detail}"), flush=True)
    return wrap


def client():
    return httpx.Client(base_url=ORIGIN, timeout=120)


def login(c, user, password):
    page = c.get("/hub/login").text
    xsrf = re.search(r'name="_xsrf" value="([^"]+)"', page).group(1)
    return c.post("/hub/login", data={"username": user, "password": password, "_xsrf": xsrf})


def path(r):
    return str(r.url).replace(ORIGIN, "")


def mint(c, u):
    r = c.post(f"/user/{u}/oidc/", headers={"Accept": "application/json"},
               data={"username": "spike-frontdoor-hub", "scopes": "openid stac:read stac:write",
                     "claims": json.dumps({"email": "spike@example.com"})}, follow_redirects=True)
    r.raise_for_status()
    return r.json()["token"]


def collection(cid):
    return {"type": "Collection", "stac_version": "1.0.0", "id": cid, "description": "frontdoor-hub check",
            "license": "proprietary", "links": [],
            "extent": {"spatial": {"bbox": [[-180, -90, 180, 90]]}, "temporal": {"interval": [[None, None]]}}}


S = {u: client() for u in USERS}  # logged-in sessions, filled by the login checks

for u in USERS:
    o = f"{ORIGIN}/user/{u}"

    @check(f"{u}.anonymous-blocked")
    def _():
        leaks = {}
        for p in ["stac/", "raster/healthz", "vector/", "oidc/.well-known/jwks.json", "browser/", "manager/", "lab"]:
            r = client().get(f"/user/{u}/{p}", follow_redirects=True)
            if not (r.status_code in (200, 403) and path(r).startswith("/hub/login")) and r.status_code != 403:
                leaks[p] = f"{r.status_code} {path(r)[:60]}"
        return not leaks, f"7 paths under /user/{u}/ without login → hub login page or 403; leaks: {leaks or 'none'}"

    @check(f"{u}.login.wrong-password")
    def _():
        c = client()
        r = login(c, u, "not-the-password")
        st = c.get(f"/hub/api/user")
        return r.status_code == 403 and st.status_code == 403, \
            f"POST /hub/login wrong password → {r.status_code}; /hub/api/user → {st.status_code}"

    @check(f"{u}.login.password")
    def _():
        r = login(S[u], u, PW[u])
        # A page under /user/<u>/ runs the OAuth hop that sets the server's own
        # cookie; API paths answer 403 instead of redirecting.
        hop = S[u].get(f"/user/{u}/", follow_redirects=True)
        st = S[u].get(f"/user/{u}/api/status")
        return r.status_code == 302 and hop.status_code == 200 and st.status_code == 200, \
            f"POST /hub/login → {r.status_code} {r.headers.get('location')}; /user/{u}/ → " \
            f"{' → '.join(path(h).split('?')[0] for h in hop.history)} → {path(hop)} {hop.status_code}; " \
            f"/user/{u}/api/status → {st.status_code}"

    @check(f"{u}.stac.pagination-token")
    def _():
        # STAC's cursor is ?token=. JupyterHub 5 ignores ?token= (JUPYTERHUB_ALLOW_TOKEN_IN_URL
        # defaults to false), so the cursor reaches stac-fastapi untouched.
        p1 = S[u].get(f"/user/{u}/stac/search", params={"limit": 10, "collections": GLAD}).json()
        nxt = next(l["href"] for l in p1["links"] if l["rel"] == "next")
        p2 = S[u].get(nxt.replace(ORIGIN, ""))
        ids1, ids2 = {f["id"] for f in p1["features"]}, {f["id"] for f in p2.json().get("features", [])}
        return "token=" in nxt and p2.status_code == 200 and len(ids2) == 10 and not ids1 & ids2, \
            f"next link {nxt.split('?')[0].replace(ORIGIN, '')}?token=…; page 2 → {p2.status_code}, " \
            f"{len(ids2)} items, overlap with page 1: {len(ids1 & ids2)}"

    @check(f"{u}.stac")
    def _():
        land = S[u].get(f"/user/{u}/stac/", follow_redirects=True).json()
        self_ = next(l["href"] for l in land["links"] if l["rel"] == "self")
        cols = [c["id"] for c in S[u].get(f"/user/{u}/stac/collections").json()["collections"]]
        n = S[u].get(f"/user/{u}/stac/collections/{GLAD}/items", params={"limit": 100}).json()
        ok = self_.startswith(f"{o}/stac") and GLAD in cols and len(n["features"]) == 100
        return ok, f"self={self_}; collections={cols}; glad items={len(n['features'])}"

    @check(f"{u}.raster")
    def _():
        h = S[u].get(f"/user/{u}/raster/healthz")
        tj = S[u].get(f"/user/{u}/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json",
                      params={"assets": "gain"})
        tile = tj.json()["tiles"][0] if tj.status_code == 200 else tj.text[:120]
        return h.status_code == 200 and tile.startswith(f"{o}/raster/"), \
            f"healthz {h.status_code}; tilejson {tj.status_code} tiles[0]={tile}"

    @check(f"{u}.vector")
    def _():
        j = S[u].get(f"/user/{u}/vector/collections").json()
        ids = [c["id"] for c in j["collections"]]
        f = S[u].get(f"/user/{u}/vector/collections/features.ecoregions/items", params={"limit": 1})
        nm = f.json().get("numberMatched")
        links = [l["href"] for l in j["links"] if l.get("rel") == "self"]
        return "features.ecoregions" in ids and nm and nm > 0 and links[0].startswith(f"{o}/vector"), \
            f"collections={ids}; ecoregions numberMatched={nm}; self={links[0]}"

    @check(f"{u}.oidc")
    def _():
        conf = S[u].get(f"/user/{u}/oidc/.well-known/openid-configuration").json()
        jwks = S[u].get(conf["jwks_uri"].replace(ORIGIN, ""))
        ok = conf["issuer"] == f"{o}/oidc" and conf["authorization_endpoint"].startswith(f"{o}/oidc/") \
            and conf["token_endpoint"].startswith(f"{o}/oidc/") and jwks.status_code == 200
        return ok, f"issuer={conf['issuer']}; authorize={conf['authorization_endpoint']}; " \
                   f"token={conf['token_endpoint']}; jwks {jwks.status_code}"

    @check(f"{u}.browser-manager")
    def _():
        b, m = S[u].get(f"/user/{u}/browser/"), S[u].get(f"/user/{u}/manager/")
        asset = re.search(r"<script src=[\"']?([^\"' >]+\.js)", m.text)
        a = S[u].get(asset.group(1).replace(ORIGIN, "")) if asset else None
        ok = b.status_code == m.status_code == 200 and asset and asset.group(1).startswith(f"{o}/manager/") \
            and a.status_code == 200
        return ok, f"/browser/ {b.status_code}; /manager/ {m.status_code}; manager script " \
                   f"{asset.group(1) if asset else None} → {a.status_code if a else None}"

    @check(f"{u}.stac.bearer-write")
    def _():
        # A Bearer JWT next to the hub session cookie: the singleuser server first
        # tries the JWT as a hub token, then falls back to the cookie.
        cid = f"spike-frontdoor-hub-{u}"
        h = {"Authorization": f"Bearer {mint(S[u], u)}"}
        anon = S[u].post(f"/user/{u}/stac/collections", json=collection(cid))
        post = S[u].post(f"/user/{u}/stac/collections", json=collection(cid), headers=h)
        dele = S[u].delete(f"/user/{u}/stac/collections/{cid}", headers=h)
        return anon.status_code == 401 and post.status_code in (200, 201) and dele.status_code in (200, 204), \
            f"POST without JWT {anon.status_code}; with own JWT {post.status_code}; DELETE {dele.status_code}"


@check("u01.lab.upload-2mb")
def _():
    # Cookie auth on a write needs JupyterHub's XSRF token (cookie _xsrf, path /user/u01/).
    c = S["u01"]
    c.get("/user/u01/lab", follow_redirects=True)
    x = next(k.value for k in c.cookies.jar if k.name == "_xsrf" and k.path.startswith("/user/u01"))
    body = {"type": "file", "format": "text", "content": "x" * 2_000_000}
    put = c.put("/user/u01/api/contents/spike-upload.txt", json=body, headers={"X-XSRFToken": x})
    dele = c.delete("/user/u01/api/contents/spike-upload.txt", headers={"X-XSRFToken": x})
    return put.status_code in (200, 201), f"PUT 2 MB via /api/contents → {put.status_code}; DELETE {dele.status_code}"


LAPTOP = {}  # laptop tools: a hub API token the participant creates for themselves


@check("u01.laptop.raster-vector-with-hub-token")
def _():
    c = S["u01"]
    x = next(k.value for k in c.cookies.jar if k.name == "_xsrf" and k.path == "/hub/")
    r = c.post("/hub/api/users/u01/tokens", json={"note": "spike laptop", "expires_in": 900},
               headers={"X-XSRFToken": x})
    tok = LAPTOP["token"] = r.json().get("token", "")
    PW["u01-api-token"] = tok
    h = {"Authorization": f"token {tok}"}
    ra = httpx.get(f"{ORIGIN}/user/u01/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json",
                   params={"assets": "gain"}, headers=h, timeout=60)
    ve = httpx.get(f"{ORIGIN}/user/u01/vector/collections", headers=h, timeout=60)
    return r.status_code == 201 and ra.status_code == ve.status_code == 200, \
        f"POST /hub/api/users/u01/tokens (session + XSRF) → {r.status_code}; with 'Authorization: token': " \
        f"raster tilejson → {ra.status_code}, vector collections → {ve.status_code}"


@check("u01.laptop.stac-with-hub-token")
def _():
    # The hub accepts the token, then jupyter-server-proxy forwards the same
    # Authorization header, and stac-auth-proxy refuses anything but a valid JWT.
    tok, u = LAPTOP.get("token", ""), f"{ORIGIN}/user/u01/stac/collections"
    t = httpx.get(u, headers={"Authorization": f"token {tok}"}, timeout=60).status_code
    b = httpx.get(u, headers={"Authorization": f"Bearer {tok}"}, timeout=60).status_code
    q = httpx.get(u, params={"token": tok}, timeout=60).status_code
    return t == 200 or b == 200 or q == 200, \
        f"/user/u01/stac/collections with the hub token as 'Authorization: token' → {t}, " \
        f"'Authorization: Bearer' → {b}, ?token= → {q} (JupyterHub 5 ignores ?token=)"

# ---- isolation between the two stacks ----


@check("cross.u01-session-on-u02")
def _():
    rs = {p: S["u01"].get(f"/user/u02/{p}", follow_redirects=True) for p in ["lab", "stac/", "oidc/"]}
    leaks = {p: f"{r.status_code} {path(r)[:50]}" for p, r in rs.items() if r.status_code != 403}
    return not leaks, f"u01's session on /user/u02/{{lab,stac/,oidc/}} → " \
                      f"{sorted({r.status_code for r in rs.values()})}; leaks: {leaks or 'none'}"


@check("cross.u01-password-as-u02")
def _():
    r = login(client(), "u02", PW["u01"])
    return r.status_code == 403, f"POST /hub/login username=u02 password=<u01's> → {r.status_code}"


@check("cross.u01-api-token-on-u02")
def _():
    tok = PW.get("u01-api-token")
    r = httpx.get(f"{ORIGIN}/user/u02/stac/collections", headers={"Authorization": f"token {tok}"}, timeout=60)
    return bool(tok) and r.status_code in (302, 403), f"u01's hub API token on /user/u02/stac/collections → {r.status_code}"


@check("cross.u01-jwt-on-u02-stac")
def _():
    r = S["u02"].post("/user/u02/stac/collections", json=collection("spike-frontdoor-hub-cross"),
                      headers={"Authorization": f"Bearer {mint(S['u01'], 'u01')}"})
    if r.status_code in (200, 201):
        S["u02"].delete("/user/u02/stac/collections/spike-frontdoor-hub-cross",
                        headers={"Authorization": f"Bearer {mint(S['u02'], 'u02')}"})
    return r.status_code == 401, f"u01-minted stac:write JWT → POST /user/u02/stac/collections → {r.status_code}"


@check("bearer.hub-roundtrips")
def _():
    # Each request with an unknown Bearer costs one hub API lookup before the cookie
    # fallback. Time 20 reads with and without one.
    h = {"Authorization": f"Bearer {mint(S['u01'], 'u01')}"}
    def t(headers):
        t0 = time.perf_counter()
        codes = {S["u01"].get("/user/u01/stac/collections", headers=headers).status_code for _ in range(20)}
        return (time.perf_counter() - t0) / 20 * 1000, codes
    plain, c1 = t({})
    bear, c2 = t(h)
    return c1 == c2 == {200}, f"20 GET /stac/collections: cookie only {plain:.0f} ms/req, " \
                             f"cookie + Bearer {bear:.0f} ms/req (codes {c1} / {c2})"
