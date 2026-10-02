"""Extra refutation probes for the own chart, through the kind ingress (verify stage).

Runs like frontdoor-own/ingress.py: a throwaway container on the `kind` docker
network, credentials from the environment, never printed.
Phase "cookie": u01's login cookie replayed on lab-u02.
Phase "write" / "read": write a collection in u01's stack, then (after run.sh
replaces the pod) check whether it is still there.
Prints: PASS|FAIL <name> — <detail>
"""

import html
import json
import os
import re
import sys

import httpx

NODE = "http://eoapi-spike-control-plane"

CID = "spike-verify-persist"


def client(u):
    return httpx.Client(
        base_url=NODE, timeout=60, headers={"Host": f"lab-{u}.spike.local:18080"}
    )


def login(u):
    c = client(u)
    c.get("/login")
    c.post(
        "/login",
        data={
            "password": os.environ[f"{u.upper()}_PASSWORD"],
            "_xsrf": c.cookies.get("_xsrf"),
        },
    )
    return c


def say(ok, name, detail):
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}", flush=True)


phase = sys.argv[1]
if phase == "cookie":
    c1 = login("u01")
    name1 = next(n for n in c1.cookies.keys() if n.startswith("username-"))
    val = c1.cookies.get(name1)
    name2 = name1.replace("lab-u01", "lab-u02")
    own = c1.get("/api/status", follow_redirects=False).status_code
    rs = {}
    for n in (name1, name2):
        r = client("u02").get(
            "/api/status", headers={"Cookie": f"{n}={val}"}, follow_redirects=False
        )
        rs[n] = r.status_code
        s = client("u02").get(
            "/stac/collections",
            headers={"Cookie": f"{n}={val}"},
            follow_redirects=False,
        )
        rs[n + " /stac"] = s.status_code
    ok = own == 200 and all(v in (302, 403) for v in rs.values())
    say(
        ok,
        "cross.u01-cookie-replayed-on-u02",
        f"u01 cookie on lab-u01 /api/status → {own}; replayed on lab-u02 (under u01's and u02's cookie names): {rs}",
    )
elif phase == "write":
    c = login("u01")
    r = c.post(
        "/oidc/",
        data={
            "username": "spike-verify",
            "scopes": "openid stac:read stac:write",
            "claims": json.dumps({"email": "v@example.com"}),
        },
    )
    tok = html.unescape(
        re.search(
            r'<textarea[^>]*id="token"[^>]*>(.*?)</textarea>', r.text, re.S
        ).group(1)
    ).strip()
    col = {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": CID,
        "description": "persistence probe",
        "license": "proprietary",
        "links": [],
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[None, None]]},
        },
    }
    p = c.post(
        "/stac/collections", json=col, headers={"Authorization": f"Bearer {tok}"}
    )
    g = c.get(f"/stac/collections/{CID}")
    w = c.put(
        "/api/contents/verify-work.txt",
        json={"type": "file", "format": "text", "content": "work"},
        headers={"X-XSRFToken": c.cookies.get("_xsrf")},
    )
    say(
        p.status_code in (200, 201)
        and g.status_code == 200
        and w.status_code in (200, 201),
        "persist.setup",
        f"u01 POST collection {CID} → {p.status_code}; GET → {g.status_code}; PUT ~/verify-work.txt → {w.status_code}",
    )
elif phase == "read":
    import time

    for _ in range(60):  # the ingress needs a moment to pick up the new pod's endpoint
        if client("u01").get("/login").status_code == 200:
            break
        time.sleep(2)
    c = login("u01")
    g = c.get(f"/stac/collections/{CID}")
    f = c.get("/api/contents/verify-work.txt")
    say(
        g.status_code == 200 and f.status_code == 200,
        "persist.pod-replacement",
        f"after the u01 pod was replaced: collection {CID} → {g.status_code}; ~/verify-work.txt → {f.status_code} "
        "(404 = the participant's DB rows and Lab files are gone)",
    )
