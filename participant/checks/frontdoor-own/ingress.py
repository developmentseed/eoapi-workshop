"""Checks through the kind ingress, as a browser on the host would see them.

Runs in a throwaway container on the `kind` docker network (run.sh). Every
request goes to the node's port 80 (published on the host as 127.0.0.1:18080)
with `Host: lab-uNN.participant.local:18080`, the exact Host a browser sends.
Credentials come from the environment (U01_PASSWORD, U01_TOKEN, ...) and are
never printed. Prints: PASS|FAIL <name> — <detail>
"""

import html
import json
import os
import re

import httpx

NODE = "http://eoapi-participant-control-plane"
USERS = ["u01", "u02"]
GLAD = "glad-global-forest-change-1.11"
GLAD_ITEM = "hansen-gfc-2023-v1.11-80N-180W"
SECRETS = [os.environ[f"{u.upper()}_{k}"] for u in USERS for k in ("PASSWORD", "TOKEN")]
JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")


def redact(s):
    for v in SECRETS:
        s = s.replace(v, "<secret>")
    return JWT.sub("<jwt>", s)


def check(name):
    def wrap(fn):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"[:300]
        print(redact(f"{'PASS' if ok else 'FAIL'} {name} — {detail}"), flush=True)

    return wrap


def origin(u):
    return f"http://lab-{u}.participant.local:18080"


def client(u):
    return httpx.Client(
        base_url=NODE, timeout=60, headers={"Host": f"lab-{u}.participant.local:18080"}
    )


def secret(u, k):
    return os.environ[f"{u.upper()}_{k}"]


def login(c, password):
    c.get("/login")
    return c.post(
        "/login",
        data={"password": password, "_xsrf": c.cookies.get("_xsrf")},
        follow_redirects=False,
    )


def mint(c):
    r = c.post(
        "/oidc/",
        data={
            "username": "kind-check",
            "scopes": "openid stac:read stac:write",
            "claims": json.dumps({"email": "check@example.com"}),
        },
    )
    r.raise_for_status()
    m = re.search(r'<textarea[^>]*id="token"[^>]*>(.*?)</textarea>', r.text, re.S)
    return html.unescape(m.group(1)).strip()


S = {u: client(u) for u in USERS}  # logged-in sessions, filled by login checks

for u in USERS:
    o = origin(u)

    @check(f"{u}.anonymous-blocked")
    def _():
        rs = {
            p: client(u).get(p, follow_redirects=False)
            for p in [
                "/stac/",
                "/raster/healthz",
                "/vector/",
                "/oidc/.well-known/jwks.json",
                "/browser/",
                "/manager/",
            ]
        }
        bad = {
            p: r.status_code
            for p, r in rs.items()
            if not (r.status_code == 302 and "/login" in r.headers.get("location", ""))
            and r.status_code != 403
        }
        return (
            not bad,
            f"6 prefixes without login → 302 /login or 403; leaks: {bad or 'none'}",
        )

    @check(f"{u}.login.wrong-password")
    def _():
        r = login(client(u), "not-the-password")
        return (
            r.status_code != 302,
            f"POST /login wrong password → {r.status_code} (no redirect)",
        )

    @check(f"{u}.login.password")
    def _():
        r = login(S[u], secret(u, "PASSWORD"))
        st = S[u].get("/api/status")
        return (
            r.status_code == 302 and st.status_code == 200,
            f"POST /login → {r.status_code} {r.headers.get('location')}; /api/status with cookie → {st.status_code}",
        )

    @check(f"{u}.login.token")
    def _():
        r = client(u).get("/api/status", params={"token": secret(u, "TOKEN")})
        return r.status_code == 200, f"/api/status?token=<own token> → {r.status_code}"

    @check(f"{u}.stac")
    def _():
        land = S[u].get("/stac/").json()
        self_ = next(lk["href"] for lk in land["links"] if lk["rel"] == "self")
        cols = [c["id"] for c in S[u].get("/stac/collections").json()["collections"]]
        n = S[u].get(f"/stac/collections/{GLAD}/items", params={"limit": 100}).json()
        ok = (
            self_.startswith(f"{o}/stac") and GLAD in cols and len(n["features"]) == 100
        )
        return ok, f"self={self_}; collections={cols}; glad items={len(n['features'])}"

    @check(f"{u}.raster")
    def _():
        h = S[u].get("/raster/healthz")
        tj = S[u].get(
            f"/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json",
            params={"assets": "gain"},
        )
        tile = tj.json()["tiles"][0] if tj.status_code == 200 else tj.text[:120]
        return h.status_code == 200 and tile.startswith(
            f"{o}/raster/"
        ), f"healthz {h.status_code}; tilejson {tj.status_code} tiles[0]={tile}"

    @check(f"{u}.vector")
    def _():
        j = S[u].get("/vector/collections").json()
        ids = [c["id"] for c in j["collections"]]
        f = S[u].get(
            "/vector/collections/features.ecoregions/items", params={"limit": 1}
        )
        nm = f.json().get("numberMatched")
        return (
            "features.ecoregions" in ids and nm and nm > 0,
            f"collections={ids}; ecoregions numberMatched={nm}",
        )

    @check(f"{u}.oidc-browser-manager")
    def _():
        iss = S[u].get("/oidc/.well-known/openid-configuration").json()["issuer"]
        b, m = S[u].get("/browser/"), S[u].get("/manager/")
        return (
            iss == f"{o}/oidc" and b.status_code == m.status_code == 200,
            f"issuer={iss}; /browser/ {b.status_code}; /manager/ {m.status_code}",
        )

    @check(f"{u}.stac.bearer-write")
    def _():
        cid = f"kind-check-{u}"
        col = {
            "type": "Collection",
            "stac_version": "1.0.0",
            "id": cid,
            "description": "frontdoor check",
            "license": "proprietary",
            "links": [],
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]},
            },
        }
        h = {"Authorization": f"Bearer {mint(S[u])}"}
        anon = S[u].post("/stac/collections", json=col)
        post = S[u].post("/stac/collections", json=col, headers=h)
        dele = S[u].delete(f"/stac/collections/{cid}", headers=h)
        return (
            anon.status_code == 401
            and post.status_code in (200, 201)
            and dele.status_code in (200, 204),
            f"POST without JWT {anon.status_code}; with own JWT {post.status_code}; DELETE {dele.status_code}",
        )


@check("u01.lab.upload-2mb")
def _():
    # ingress-nginx's default proxy-body-size (1m) would 413 this; values.yaml sets 64m.
    c, h = client("u01"), {"Authorization": f"token {secret('u01', 'TOKEN')}"}
    body = {"type": "file", "format": "text", "content": "x" * 2_000_000}
    put = c.put("/api/contents/upload-test.txt", json=body, headers=h)
    dele = c.delete("/api/contents/upload-test.txt", headers=h)
    return put.status_code in (
        200,
        201,
    ), f"PUT 2 MB via /api/contents → {put.status_code}; DELETE {dele.status_code}"


# ---- isolation between the two stacks ----


@check("cross.u01-password-on-u02")
def _():
    c = client("u02")
    r = login(c, secret("u01", "PASSWORD"))
    st = c.get("/api/status", follow_redirects=False)
    return (
        r.status_code != 302 and st.status_code == 403,
        f"POST lab-u02/login with u01's password → {r.status_code}; /api/status → {st.status_code}",
    )


@check("cross.u01-token-on-u02")
def _():
    r = client("u02").get("/api/status", params={"token": secret("u01", "TOKEN")})
    s = client("u02").get(
        "/stac/", params={"token": secret("u01", "TOKEN")}, follow_redirects=False
    )
    return (
        r.status_code == 403 and s.status_code in (302, 403),
        f"lab-u02 /api/status?token=<u01 token> → {r.status_code}; /stac/?token=<u01 token> → {s.status_code}",
    )


@check("cross.u01-jwt-on-u02-stac")
def _():
    col = {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": "kind-check-cross",
        "description": "must be refused",
        "license": "proprietary",
        "links": [],
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[None, None]]},
        },
    }
    r = S["u02"].post(
        "/stac/collections",
        json=col,
        headers={"Authorization": f"Bearer {mint(S['u01'])}"},
    )
    if r.status_code in (200, 201):
        S["u02"].delete(
            "/stac/collections/kind-check-cross",
            headers={"Authorization": f"Bearer {mint(S['u02'])}"},
        )
    return (
        r.status_code == 401,
        f"u01-minted stac:write JWT → POST lab-u02/stac/collections → {r.status_code}",
    )
