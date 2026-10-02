"""Smoke checks for one participant stack. Runs INSIDE the lab container, so
`localhost` is the shared network namespace (the "pod") and
http://localhost:18888 is the same URL a browser on the host uses.

Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>
"""

import html
import os
import re

import httpx
import psycopg

LAB = "http://localhost:18888"
TOKEN = os.environ["LAB_TOKEN"]
GLAD = "glad-global-forest-change-1.11"


def report(ok, name, detail):
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}", flush=True)


def check(name):
    def wrap(fn):
        try:
            ok, detail = fn()
        except Exception as e:  # a crash is a FAIL with the reason
            ok, detail = False, f"{type(e).__name__}: {e}"[:300]
        report(ok, name, detail)
        return fn

    return wrap


c = httpx.Client(timeout=30)
t = {"token": TOKEN}


def hrefs(doc):
    return [link["href"] for link in doc.get("links", [])]


# ---------- data baked into the DB image ----------
@check("db.ecoregions")
def _():
    with psycopg.connect("") as conn:
        n = conn.execute("select count(*) from features.ecoregions").fetchone()[0]
    return n > 0, f"features.ecoregions rows={n}"


@check("db.glad")
def _():
    with psycopg.connect("") as conn:
        n = conn.execute(
            "select count(*) from pgstac.items where collection=%s", [GLAD]
        ).fetchone()[0]
        has = conn.execute(
            "select count(*) from pgstac.collections where id=%s", [GLAD]
        ).fetchone()[0]
    return has == 1 and n == 100, f"collection={has} items={n}"


@check("db.fixed-compose-user-gone")
def _():
    try:
        psycopg.connect(
            "host=localhost user=username password=password dbname=postgis"
        ).close()
        return False, "compose's fixed username/password still logs in"
    except psycopg.OperationalError as e:
        return "does not exist" in str(e), str(e).strip().splitlines()[-1][-60:]


# ---------- each service directly on localhost:<port> ----------
@check("direct.stac-fastapi:8081")
def _():
    r = c.get("http://localhost:8081/collections")
    ids = [x["id"] for x in r.json()["collections"]]
    return r.status_code == 200 and GLAD in ids, f"{r.status_code} collections={ids}"


@check("direct.stac-auth-proxy:8084/stac")
def _():
    r = c.get("http://localhost:8084/stac/")
    self_ = [h for h in hrefs(r.json()) if h.endswith("/stac/") or h.endswith("/stac")]
    return r.status_code == 200 and bool(
        self_
    ), f"{r.status_code} root links e.g. {self_[:1]}"


@check("direct.stac-auth-proxy:8084-without-prefix-404")
def _():
    r = c.get("http://localhost:8084/collections")
    return r.status_code == 404, f"{r.status_code} (ROOT_PATH must be in the path)"


@check("direct.titiler:8082/raster")
def _():
    a = c.get("http://localhost:8082/raster/healthz").status_code
    b = c.get("http://localhost:8082/healthz").status_code
    return a == 200 and b == 200, f"prefixed={a} unprefixed={b}"


@check("direct.tipg:8083/vector")
def _():
    r = c.get("http://localhost:8083/vector/collections")
    ids = [x["id"] for x in r.json()["collections"]]
    return (
        r.status_code == 200 and "features.ecoregions" in ids,
        f"{r.status_code} {ids}",
    )


@check("direct.mock-oidc:8085/oidc")
def _():
    r = c.get("http://localhost:8085/oidc/.well-known/openid-configuration")
    j = r.json()
    return (
        r.status_code == 200 and j["issuer"] == f"{LAB}/oidc",
        f"{r.status_code} issuer={j['issuer']} jwks={j['jwks_uri']}",
    )


@check("direct.stac-browser:8080/browser")
def _():
    r = c.get("http://localhost:8080/browser/")
    cfg = c.get("http://localhost:8080/browser/runtime-config.js").text
    ok = (
        r.status_code == 200
        and '<base href="/browser/"' in r.text
        and f"{LAB}/stac/" in cfg
    )
    return (
        ok,
        f"{r.status_code} base=/browser/ catalogUrl in runtime-config={f'{LAB}/stac/' in cfg}",
    )


@check("direct.stac-manager:8086")
def _():
    r = c.get("http://localhost:8086/")
    return (
        r.status_code == 200 and f"{LAB}/manager" in r.text,
        f"{r.status_code} PUBLIC_URL substituted={f'{LAB}/manager' in r.text}",
    )


# ---------- the Lab login gates every prefix ----------
@check("proxy.token-once-then-cookie")
def _():
    # Laptop tools (skeptic finding 4): ?token= once, then the Lab cookie.
    s = httpx.Client(timeout=30)
    first = s.get(f"{LAB}/stac/", params=t).status_code
    then = s.get(f"{LAB}/stac/collections", follow_redirects=False).status_code
    return (
        first == 200 and then == 200,
        f"?token= -> {first}; no token, same client -> {then}",
    )


@check("proxy.no-token-blocked")
def _():
    codes = {
        p: c.get(f"{LAB}/{p}/", follow_redirects=False).status_code
        for p in ["stac", "raster", "vector", "oidc", "browser", "manager"]
    }
    return all(v in (302, 403) for v in codes.values()), str(codes)


@check("proxy.wrong-token-blocked")
def _():
    r = c.get(f"{LAB}/stac/", params={"token": "nope"}, follow_redirects=False)
    return r.status_code in (302, 403), f"{r.status_code}"


@check("proxy.host-allowlist")
def _():
    r = c.get(f"{LAB}/proxy/example.com:80/", params=t, follow_redirects=False)
    return r.status_code == 403, f"/proxy/example.com:80/ -> {r.status_code}"


@check("login.password-form")
def _():
    s = httpx.Client(timeout=30)
    s.get(f"{LAB}/login")
    xsrf = s.cookies.get("_xsrf")
    bad = s.post(
        f"{LAB}/login",
        data={"password": "wrong", "_xsrf": xsrf},
        follow_redirects=False,
    )
    good = s.post(
        f"{LAB}/login",
        data={"password": os.environ["LAB_PASSWORD"], "_xsrf": xsrf},
        follow_redirects=False,
    )
    stac = s.get(f"{LAB}/stac/collections", follow_redirects=False)
    return (
        bad.status_code != 302 and good.status_code == 302 and stac.status_code == 200,
        f"wrong={bad.status_code} right={good.status_code} then /stac/collections via cookie={stac.status_code}",
    )


# ---------- each prefix through jupyter-server-proxy, with ?token= ----------
@check("proxy.stac")
def _():
    r = c.get(f"{LAB}/stac/collections/{GLAD}", params=t)
    hs = hrefs(r.json())
    ok = r.status_code == 200 and all(
        h.startswith(f"{LAB}/stac/") for h in hs if "localhost" in h
    )
    return ok, f"{r.status_code} self={[h for h in hs if h.endswith(GLAD)][:1]}"


@check("proxy.raster.tilejson")
def _():
    item = c.get(
        f"http://localhost:8081/collections/{GLAD}/items", params={"limit": 1}
    ).json()["features"][0]
    asset = next(iter(item["assets"]))
    r = c.get(
        f"{LAB}/raster/collections/{GLAD}/items/{item['id']}/WebMercatorQuad/tilejson.json",
        params={**t, "assets": asset},
    )
    tiles = r.json().get("tiles", [""])[0] if r.status_code == 200 else r.text[:150]
    return r.status_code == 200 and tiles.startswith(
        f"{LAB}/raster/"
    ), f"{r.status_code} tiles={tiles[:110]}"


@check("proxy.vector")
def _():
    r = c.get(
        f"{LAB}/vector/collections/features.ecoregions/items", params={**t, "limit": 1}
    )
    j = r.json()
    hs = hrefs(j)
    return (
        r.status_code == 200
        and len(j["features"]) == 1
        and all(h.startswith(f"{LAB}/vector/") for h in hs),
        f"{r.status_code} features={len(j['features'])} link e.g. {hs[:1]}",
    )


@check("proxy.oidc")
def _():
    r = c.get(f"{LAB}/oidc/.well-known/openid-configuration", params=t)
    j = r.json()
    return (
        r.status_code == 200 and j["authorization_endpoint"] == f"{LAB}/oidc/authorize",
        f"{r.status_code} authorization_endpoint={j['authorization_endpoint']}",
    )


@check("proxy.browser")
def _():
    r = c.get(f"{LAB}/browser/", params=t)
    deep = c.get(f"{LAB}/browser/collections/{GLAD}", params=t)
    return (
        r.status_code == 200
        and "stac-browser-base" in r.text
        and deep.status_code == 200,
        f"index={r.status_code} deep-link={deep.status_code}",
    )


@check("proxy.manager")
def _():
    r = c.get(f"{LAB}/manager/", params=t)
    srcs = re.findall(r"""(?:src|href)=["']?([^"' >]+\.(?:js|css))""", r.text)
    a = c.get(srcs[0], params=t).status_code if srcs else None
    deep = c.get(f"{LAB}/manager/collections", params=t)
    return (
        r.status_code == 200 and a == 200,
        f"index={r.status_code} asset {srcs[:1]} -> {a}; deep-link status={deep.status_code} (http-server 404.html fallback, body is the app={'<div id' in deep.text or 'root' in deep.text})",
    )


# ---------- writes: Bearer token through the proxy, mock-oidc per stack ----------
def mint(base):
    # Same request as docs/stac_auth.py get_mock_oidc_token().
    r = c.post(
        f"{base}/",
        data={
            "username": "u01",
            "scopes": "openid profile stac:read stac:write",
            "claims": "{}",
        },
        params=t if base.startswith(LAB) else None,
    )
    r.raise_for_status()
    m = re.search(r'<textarea[^>]*id="token"[^>]*>(.*?)</textarea>', r.text, re.S)
    return html.unescape(m.group(1)).strip()


COLL = {
    "type": "Collection",
    "stac_version": "1.0.0",
    "id": "spike-smoke",
    "description": "smoke",
    "license": "proprietary",
    "links": [],
    "extent": {
        "spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [[None, None]]},
    },
}


@check("write.server-side")
def _():
    jwt = mint("http://localhost:8085/oidc")
    h = {"Authorization": f"Bearer {jwt}"}
    anon = c.post("http://localhost:8084/stac/collections", json=COLL).status_code
    post = c.post(
        "http://localhost:8084/stac/collections", json=COLL, headers=h
    ).status_code
    dele = c.delete(
        "http://localhost:8084/stac/collections/spike-smoke", headers=h
    ).status_code
    return anon == 401 and post in (200, 201) and dele in (
        200,
        204,
    ), f"anon={anon} bearer POST={post} DELETE={dele}"


@check("write.through-proxy")
def _():
    jwt = mint(f"{LAB}/oidc")  # mint via the browser-facing URL too
    h = {"Authorization": f"Bearer {jwt}"}
    anon = c.post(f"{LAB}/stac/collections", json=COLL, params=t).status_code
    post = c.post(f"{LAB}/stac/collections", json=COLL, params=t, headers=h).status_code
    get = c.get(f"{LAB}/stac/collections/spike-smoke", params=t).status_code
    dele = c.delete(
        f"{LAB}/stac/collections/spike-smoke", params=t, headers=h
    ).status_code
    return (
        anon == 401 and post in (200, 201) and get == 200 and dele in (200, 204),
        f"anon={anon} bearer POST={post} GET={get} DELETE={dele} (POST/DELETE pass Jupyter's XSRF check)",
    )


@check("proxy.token-not-echoed")
def _():
    # jupyter-server-proxy forwards the query string, ?token= included.
    leaks = []
    for p in [
        "stac/search?limit=1",
        "stac/collections",
        "vector/collections?limit=1",
        "raster/collections",
    ]:
        sep = "&" if "?" in p else "?"
        body = c.get(f"{LAB}/{p}{sep}token={TOKEN}").text
        if TOKEN in body:
            leaks.append(p)
    return (
        not leaks,
        f"Lab token appears in response body of: {leaks}" if leaks else "no echo",
    )
