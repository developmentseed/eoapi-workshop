"""Another pod's view: a throwaway container on the compose network, NOT in the
participant's netns. Host `lab` = the participant pod IP. Holds no Lab
credential. Prepended with common.py.
"""

import socket

POD = "lab"

# ---- 1. through the front door: the Lab login holds ----
gate_checks(f"http://{POD}:18888", "offpod")

# ---- 6/7. around the front door: every backend binds 127.0.0.1, so nothing answers ----
PORTS = {"postgres": 5432, "stac-browser": 8080, "stac-fastapi": 8081, "titiler-pgstac": 8082,
         "tipg": 8083, "stac-auth-proxy": 8084, "mock-oidc": 8085, "stac-manager": 8086}


@check("offpod.tcp-reachable")
def _():
    open_ = []
    for name, port in PORTS.items():
        with socket.socket() as s:
            s.settimeout(2)
            if s.connect_ex((POD, port)) == 0:
                open_.append(f"{name}:{port}")
    return not open_, f"reachable without any credential: {open_}" if open_ else "only the Lab answers"


def refused(fn):
    """Inner decorator: a refused connection (loopback bind) is the pass."""
    def run():
        try:
            return fn()
        except httpx.ConnectError as e:
            return True, f"connection refused ({type(e).__name__}): loopback bind"
    return run


@check("offpod.oidc-mint-direct")
@refused
def _():
    jwt = mint(f"http://{POD}:8085/oidc", username="spike-auth-offpod")
    return False, f"POST http://{POD}:8085/oidc/ minted a stac:write JWT ({len(jwt)} chars) with no Lab login"


@check("offpod.write-via-auth-proxy")
@refused
def _():
    jwt = mint(f"http://{POD}:8085/oidc", username="spike-auth-offpod")
    cid = "spike-auth-offpod-proxy"
    base = f"http://{POD}:8084/stac"
    httpx.delete(f"{base}/collections/{cid}", headers=bearer(jwt), timeout=30)
    post = httpx.post(f"{base}/collections", json=collection(cid), headers=bearer(jwt), timeout=30)
    dele = httpx.delete(f"{base}/collections/{cid}", headers=bearer(jwt), timeout=30)
    return post.status_code not in (200, 201), \
        f"self-minted JWT -> POST {base}/collections={post.status_code}, DELETE={dele.status_code} ({cid})"


@check("offpod.write-stac-fastapi-no-token")
@refused
def _():
    cid = "spike-auth-offpod-direct"
    base = f"http://{POD}:8081"
    httpx.delete(f"{base}/collections/{cid}", timeout=30)
    post = httpx.post(f"{base}/collections", json=collection(cid), timeout=30)
    dele = httpx.delete(f"{base}/collections/{cid}", timeout=30)
    return post.status_code not in (200, 201), \
        f"no token at all -> POST {base}/collections={post.status_code}, DELETE={dele.status_code} ({cid})"
