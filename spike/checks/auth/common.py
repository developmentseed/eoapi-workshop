"""Shared helpers for the auth checks. run.sh prepends this file to each check
script (`cat common.py laptop.py | docker exec|run ... python -`).

Secrets come from the environment (the Lab container has them) or from
spike/.env mounted read-only at /run/spike.env (throwaway containers). Every
printed line goes through redact(): no Lab token, password or JWT is printed.
"""

import html
import json
import os
import re

import httpx


def _load_env():
    env = {}
    try:
        for line in open("/run/spike.env"):
            k, _, v = line.strip().partition("=")
            if k and v:
                env[k] = v
    except OSError:
        pass
    for k in ("LAB_TOKEN", "LAB_PASSWORD", "POSTGRES_PASSWORD"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = _load_env()
TOKEN = ENV["LAB_TOKEN"]
GLAD = "glad-global-forest-change-1.11"
GLAD_ITEM = "hansen-gfc-2023-v1.11-80N-180W"
_JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
# Response text that would mean a service leaked content to an anonymous caller.
CONTENT_MARKERS = [
    "stac_version",
    "conformsTo",
    "tilejson",
    "FeatureCollection",
    '"issuer"',
    '"keys"',
    "eyJ",
    "stac-browser",
    "STAC Manager",
    "<textarea",
]


def redact(s):
    s = str(s)
    for k, v in ENV.items():
        if len(v) >= 8:
            s = s.replace(v, f"<{k}>")
    return _JWT.sub("<JWT>", s)


def report(status, name, detail):
    print(f"{status} {name} — {redact(detail)}"[:600], flush=True)


def check(name):
    """Decorator: fn() -> (ok: bool | "BLOCKED", detail). A crash is a FAIL."""

    def wrap(fn):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"[:300]
        report("BLOCKED" if ok == "BLOCKED" else "PASS" if ok else "FAIL", name, detail)
        return fn

    return wrap


def mint(
    base,
    scopes="openid profile stac:read stac:write",
    username="spike-auth",
    client=None,
    params=None,
):
    """Same request as docs/stac_auth.py get_mock_oidc_token(); returns the JWT."""
    r = (client or httpx).post(
        f"{base}/",
        data={
            "username": username,
            "scopes": scopes,
            "claims": json.dumps({"email": f"{username}@example.com"}),
        },
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    m = re.search(r'<textarea[^>]*id="token"[^>]*>(.*?)</textarea>', r.text, re.S)
    return html.unescape(m.group(1)).strip()


def bearer(jwt):
    return {"Authorization": f"Bearer {jwt}"}


def collection(cid):
    return {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": cid,
        "description": "auth spike, deleted at the end of the check",
        "license": "proprietary",
        "links": [],
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[None, None]]},
        },
    }


def blocked(r):
    """True if the Lab front door refused the request: 302 to /login, or 403,
    with no service content in the body."""
    gate = (
        r.status_code == 302 and r.headers.get("location", "").startswith("/login")
    ) or r.status_code == 403
    return gate and not any(m in r.text for m in CONTENT_MARKERS)


# Every same-origin prefix, the Lab itself and the generic jsp routes.
GATE_PATHS = {
    "stac": [
        "/stac/",
        "/stac/collections",
        "/stac/search?limit=1",
        f"/stac/collections/{GLAD}/items?limit=1",
    ],
    "raster": [
        "/raster/",
        "/raster/healthz",
        f"/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json?assets=gain",
    ],
    "vector": [
        "/vector/",
        "/vector/collections",
        "/vector/collections/features.ecoregions/items?limit=1",
    ],
    "browser": ["/browser/", "/browser/runtime-config.js"],
    "oidc": [
        "/oidc/",
        "/oidc/.well-known/openid-configuration",
        "/oidc/.well-known/jwks.json",
        "/oidc/authorize?client_id=x&response_type=code&redirect_uri=http://localhost:18888/browser/auth",
    ],
    "manager": ["/manager/", "/manager/collections"],
    "lab": [
        "/lab",
        "/lab/tree/docs",
        "/api/contents",
        "/api/kernels",
        "/api/terminals",
        "/files/docs/README.md",
        "/lab/terminals/1",
        "/api/sessions",
    ],
    "proxy": [
        "/proxy/8081/collections",
        "/proxy/absolute/8084/stac/",
        "/proxy/localhost:8085/oidc/",
    ],
}
WS = {
    "Upgrade": "websocket",
    "Connection": "Upgrade",
    "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
    "Sec-WebSocket-Version": "13",
}


def gate_checks(lab, where):
    """Check 1: no credentials -> 302 /login or 403, never content."""
    c = httpx.Client(timeout=30, follow_redirects=False)
    for prefix, paths in GATE_PATHS.items():

        @check(f"{where}.unauth.{prefix}")
        def _():
            codes = {p: c.get(lab + p) for p in paths}
            return all(blocked(r) for r in codes.values()), " ".join(
                f"{p}={r.status_code}" for p, r in codes.items()
            )

    @check(f"{where}.unauth.public-surface")
    def _():
        # What DOES answer 200 without a login: must be the login page and static files only.
        public = {
            p: c.get(lab + p)
            for p in [
                "/login",
                "/logout",
                "/api",
                "/static/lab/index.html",
                "/favicon.ico",
            ]
        }
        ok = all(
            r.status_code == 200 and not any(m in r.text for m in CONTENT_MARKERS)
            for r in public.values()
        )
        return ok, " ".join(
            f"{p}={r.status_code}" for p, r in public.items()
        ) + f"; /api body={public['/api'].text.strip()[:40]}"

    @check(f"{where}.unauth.methods")
    def _():
        out = {}
        for p in [
            "/stac/collections",
            "/oidc/",
            "/oidc/token",
            "/raster/",
            "/manager/",
        ]:
            for m in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]:
                out[f"{m} {p}"] = c.request(
                    m, lab + p, data={"username": "x", "scopes": "stac:write"}
                )
        bad = {k: r.status_code for k, r in out.items() if not blocked(r)}
        return (
            not bad,
            f"{len(out)} requests, non-GET -> 403, HEAD -> 302"
            if not bad
            else f"not blocked: {bad}",
        )

    @check(f"{where}.unauth.websocket")
    def _():
        codes = {
            p: c.get(lab + p, headers=WS).status_code
            for p in [
                "/stac/",
                "/oidc/",
                "/raster/",
                "/browser/",
                "/terminals/websocket/1",
            ]
        }
        return all(v == 403 for v in codes.values()), str(codes)

    @check(f"{where}.unauth.bad-credentials")
    def _():
        name = "username-" + re.sub(r"[^A-Za-z0-9]", "-", lab.split("//")[1])
        tries = {
            "?token=wrong": dict(params={"token": "wrong"}),
            "Authorization: token wrong": dict(
                headers={"Authorization": "token wrong"}
            ),
            "forged login cookie": dict(headers={"Cookie": f"{name}=2|1:0|10:1|x|y"}),
        }
        out = {k: c.get(lab + "/stac/collections", **kw) for k, kw in tries.items()}
        return all(blocked(r) for r in out.values()), " ".join(
            f"[{k}]={r.status_code}" for k, r in out.items()
        )
