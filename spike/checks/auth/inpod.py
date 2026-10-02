"""Runs INSIDE the Lab container (the pod netns), like a notebook kernel.
Prepended with common.py.
"""

import glob
import socket
import struct
import sys
import time

LAB = "http://localhost:18888"
T = {"token": TOKEN}

# ---- 5. notebook-style server-side writes: docs/stac_auth.py, Bearer, no Lab login ----
sys.path.insert(0, "/home/jovyan/docs")
import stac_auth  # noqa: E402

CID = "spike-auth-inpod"


@check("inpod.write.notebook-helpers")
def _():
    stac, oidc = stac_auth.require_local_auth_stack()
    jwt = stac_auth.get_mock_oidc_token("spike-auth-inpod")
    h = stac_auth.auth_headers(jwt)
    c = httpx.Client(timeout=30)
    c.delete(f"{stac}/collections/{CID}", headers=h)  # leftovers from an aborted run
    item = {
        "type": "Feature", "stac_version": "1.0.0", "id": f"{CID}-item", "collection": CID,
        "geometry": {"type": "Point", "coordinates": [0, 0]}, "bbox": [0, 0, 0, 0],
        "properties": {"datetime": "2026-10-01T00:00:00Z"}, "links": [], "assets": {},
    }
    steps = {
        "POST collection": c.post(f"{stac}/collections", json=collection(CID), headers=h),
        "POST item": c.post(f"{stac}/collections/{CID}/items", json=item, headers=h),
        "GET item (anon)": c.get(f"{stac}/collections/{CID}/items/{CID}-item"),
        "DELETE item": c.delete(f"{stac}/collections/{CID}/items/{CID}-item", headers=h),
        "DELETE collection": c.delete(f"{stac}/collections/{CID}", headers=h),
    }
    codes = {k: r.status_code for k, r in steps.items()}
    return all(v in (200, 201, 204) for v in codes.values()), f"STAC_API_ENDPOINT={stac} {codes}"


@check("inpod.write.refusals")
def _():
    stac, _ = stac_auth.require_local_auth_stack()
    ro = stac_auth.get_mock_oidc_token("spike-auth-inpod", scopes="openid profile stac:read")
    body = collection(f"{CID}-refused")
    anon = httpx.post(f"{stac}/collections", json=body, timeout=30).status_code
    read_only = httpx.post(f"{stac}/collections", json=body, headers=stac_auth.auth_headers(ro),
                           timeout=30).status_code
    return anon == 401 and read_only == 403, f"anonymous={anon} stac:read-only Bearer={read_only}"


# ---- 7. who listens where in the pod netns ----
SERVICES = {5432: "postgres", 8080: "stac-browser", 8081: "stac-fastapi", 8082: "titiler-pgstac",
            8083: "tipg", 8084: "stac-auth-proxy", 8085: "mock-oidc", 8086: "stac-manager",
            18888: "lab (jupyter-server)"}


def listeners():
    owners = {}  # socket inode -> cmdline, for processes in THIS container (the Lab)
    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            target = os.readlink(fd)
            if target.startswith("socket:["):
                pid = fd.split("/")[2]
                owners[target[8:-1]] = open(f"/proc/{pid}/cmdline").read().replace("\0", " ")[:70]
        except OSError:
            pass
    out = []
    for path, fam in (("/proc/net/tcp", socket.AF_INET), ("/proc/net/tcp6", socket.AF_INET6)):
        for line in open(path).readlines()[1:]:
            f = line.split()
            if f[3] != "0A":  # LISTEN
                continue
            hexip, hexport = f[1].split(":")
            raw = bytes.fromhex(hexip)
            raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
            out.append((socket.inet_ntop(fam, raw), int(hexport, 16), owners.get(f[9])))
    return sorted(out, key=lambda x: x[1])


for ip, port, owner in listeners():
    loopback = ip.startswith("127.") or ip == "::1"
    who = SERVICES.get(port) or owner or "unknown (another container's process)"
    if port == 18888:
        report("PASS", f"sockets.{ip}:{port}", f"{who}: the front door, must accept the ingress")
    elif ip == "127.0.0.11":
        report("PASS", f"sockets.{ip}:{port}", "Docker's embedded DNS (compose only, absent on k8s)")
    elif loopback:
        report("PASS", f"sockets.{ip}:{port}", f"loopback only: {who}")
    else:
        report("FAIL", f"sockets.{ip}:{port}",
               f"{who} binds all interfaces: reachable from any other pod unless a NetworkPolicy blocks it")


# ---- 8. Lab login cookie flags behind a TLS-terminating proxy ----
def login_cookie(r):
    return next((v for v in r.headers.get_list("set-cookie") if v.startswith("username-")), "")


def flags(cookie):
    """Cookie attributes, with Expires shown as days from now."""
    from email.utils import parsedate_to_datetime

    out = []
    for p in (p.strip() for p in cookie.split(";")[1:]):
        if p.lower().startswith("expires="):
            days = (parsedate_to_datetime(p.split("=", 1)[1]).timestamp() - time.time()) / 86400
            p = f"Expires=+{days:.1f}d"
        out.append(p)
    return out


def short_lived(f):
    """lab/jupyter_server_config.py cookie_options: expires_days=2, not tornado's 30."""
    return any(p.startswith("Expires=+") and float(p[9:-1]) <= 2.01 for p in f)


XFP = {"X-Forwarded-Proto": "https"}


@check("cookie.token-login.xfp-https")
def _():
    f = flags(login_cookie(httpx.get(f"{LAB}/stac/", params=T, headers=XFP, timeout=30)))
    return {"HttpOnly", "Secure", "Path=/", "SameSite=Lax"} <= set(f) and short_lived(f), f"flags={f}"


@check("cookie.token-login.plain-http")
def _():
    f = flags(login_cookie(httpx.get(f"{LAB}/stac/", params=T, timeout=30)))
    return "Secure" not in f and "HttpOnly" in f, f"flags={f} (no X-Forwarded-Proto -> no Secure, as expected)"


@check("cookie.password-login.xfp-https")
def _():
    s = httpx.Client(timeout=30, headers=XFP)
    xsrf_cookie = next(v for v in s.get(f"{LAB}/login").headers.get_list("set-cookie") if v.startswith("_xsrf"))
    r = s.post(f"{LAB}/login", data={"password": ENV["LAB_PASSWORD"], "_xsrf": s.cookies.get("_xsrf")},
               follow_redirects=False)
    f = flags(login_cookie(r))
    return r.status_code == 302 and {"HttpOnly", "Secure", "Path=/", "SameSite=Lax"} <= set(f) and short_lived(f), \
        f"login={r.status_code} cookie flags={f}; _xsrf cookie flags={flags(xsrf_cookie)} " \
        "(no Secure/HttpOnly on _xsrf: a CSRF nonce JS must read, not a credential)"


@check("xfp.links-https")
def _():
    # jsp copies X-Forwarded-Proto to the backends; uvicorn trusts it (FORWARDED_ALLOW_IPS=*).
    c = httpx.Client(timeout=60, headers=XFP)
    stac = [l["href"] for l in c.get(f"{LAB}/stac/", params=T).json()["links"] if "18888" in l["href"]]
    vec = [l["href"] for l in c.get(f"{LAB}/vector/collections", params=T).json()["links"] if "18888" in l["href"]]
    tiles = c.get(f"{LAB}/raster/collections/{GLAD}/items/{GLAD_ITEM}/WebMercatorQuad/tilejson.json",
                  params={**T, "assets": "gain"}).json()["tiles"]
    oidc = c.get(f"{LAB}/oidc/.well-known/openid-configuration", params=T).json()
    https = all(h.startswith("https://") for h in stac + vec + tiles + [oidc["authorization_endpoint"]])
    return https, f"stac/vector/raster/oidc endpoints all https={https}; " \
        f"oidc issuer={oidc['issuer']} (fixed by the ISSUER env, not the request)"
