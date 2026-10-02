"""HTTP-level checks behind the browser findings (no browser needed).

Runs in a container sharing the Lab's network namespace (run.sh).
  python probes.py              checks against the running stack
  python probes.py --fix 18982  also checks the throwaway stac-auth-proxy on :18982
                                whose upstream is stac-fastapi started with
                                `--root-path /stac` (proposed fix; run.sh starts both)

Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>
Data it creates (and deletes): collection spike-browser-apps-rootpath.
"""

import http.client
import json
import sys
import time
import urllib.parse

GLAD = "glad-global-forest-change-1.11"
ITEM = "hansen-gfc-2023-v1.11-80N-180W"
FIX_ID = "spike-browser-apps-rootpath"
LIVE = (
    8084  # stac-auth-proxy as deployed (ROOT_PATH=/stac, upstream stac-fastapi :8081)
)


def report(status, name, detail):
    print(f"{status} {name} — {detail}", flush=True)


def call(
    port, method, path, host="localhost:18888", body=None, headers=None, form=None
):
    c = http.client.HTTPConnection("localhost", port, timeout=60)
    h = {"Host": host, **(headers or {})}
    if body is not None:
        body = json.dumps(body)
        h["Content-Type"] = "application/json"
    if form is not None:
        body = urllib.parse.urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def mint(scopes="openid profile stac:read stac:write"):
    """Same call notebooks 06-08 make (mock-oidc POST /), direct inside the pod."""
    s, _, d = call(
        8085,
        "POST",
        "/oidc/",
        host="localhost:8085",
        headers={"Accept": "application/json"},
        form={"username": "spike-browser-apps", "scopes": scopes, "claims": "{}"},
    )
    assert s == 200, f"mint -> {s}"
    return json.loads(d)["token"]


def collection(cid):
    return {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": cid,
        "title": "Spike root-path probe",
        "description": "Created by spike/checks/browser-apps/probes.py; deleted at once.",
        "license": "CC-BY-4.0",
        "links": [],
        "extent": {
            "spatial": {"bbox": [[-10.0, 40.0, 10.0, 50.0]]},
            "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]},
        },
    }


# ---------------------------------------------------------------- as deployed
def as_deployed():
    out = []
    for port, method, path in [
        (8081, "POST", "/collections/"),
        (LIVE, "POST", "/stac/collections/"),
        (LIVE, "GET", "/stac/collections/"),
    ]:
        s, h, _ = call(port, method, path, body={} if method == "POST" else None)
        out.append((port, method, path, s, h.get("location")))
    proxied = [o for o in out if o[0] == LIVE]
    ok = all(
        o[3] in (307, 308)
        and urllib.parse.urlsplit(o[4] or "").path.startswith("/stac/")
        for o in proxied
    )
    report(
        "PASS" if ok else "FAIL",
        "stac.trailing-slash-redirect-keeps-prefix",
        "; ".join(f"{m} :{p}{pa} -> {s} Location={loc}" for p, m, pa, s, loc in out)
        + (
            ""
            if ok
            else ". stac-fastapi (Starlette redirect_slashes) builds Location without /stac "
            "and stac-auth-proxy v1.2.0 rewrites links in JSON bodies only, not Location headers; "
            "the browser then POSTs to the Lab's own /collections"
        ),
    )

    ids = {
        p: json.loads(call(LIVE, "GET", p)[2]).get("$id")
        for p in ("/stac/queryables", f"/stac/collections/{GLAD}/queryables")
    }
    ok = all((v or "").startswith("http://localhost:18888/stac/") for v in ids.values())
    report(
        "PASS" if ok else "FAIL",
        "stac.queryables-id-keeps-prefix",
        f"JSON-schema $id: {ids}"
        + (
            ""
            if ok
            else " (same cause: stac-fastapi does not know its /stac "
            "prefix; harmless today, the schemas have no relative $ref)"
        ),
    )

    s1, _, _ = call(8081, "OPTIONS", "/")
    s2, _, _ = call(LIVE, "OPTIONS", "/stac/")
    report(
        "PASS" if s1 == s2 == 405 else "FAIL",
        "browser.options-405-is-upstream",
        f"OPTIONS stac-fastapi :8081/ -> {s1}, stac-auth-proxy :8084/stac/ -> {s2}: STAC Browser's "
        "permission probe 405s at the API itself, not at the Lab front door",
    )


# ------------------------------------------------------- proposed fix (--root-path)
def wait_ready(port):
    t0 = time.time()
    while time.time() - t0 < 180:
        try:
            if call(port, "GET", "/stac/")[0] == 200:
                return round(time.time() - t0)
        except OSError:
            pass
        time.sleep(2)
    return None


def links(doc):
    """Every href under any `links` array, with its rel, in document order."""
    found = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "links" and isinstance(v, list):
                found += [
                    (lk.get("rel"), lk.get("href"), lk.get("method"))
                    for lk in v
                    if isinstance(lk, dict)
                ]
            else:
                found += links(v)
    elif isinstance(doc, list):
        for v in doc:
            found += links(v)
    return found


def fixed(port):
    ready = wait_ready(port)
    if ready is None:
        report(
            "BLOCKED",
            "fix.root-path",
            f"throwaway stac-auth-proxy :{port} never answered /stac/",
        )
        return

    s, h, _ = call(port, "POST", "/stac/collections/", body={})
    s2, h2, _ = call(port, "GET", "/stac/collections/")
    want = "http://localhost:18888/stac/collections"
    ok = h.get("location") == want and h2.get("location") == want
    report(
        "PASS" if ok else "FAIL",
        "fix.root-path.redirect-keeps-prefix",
        f"stac-fastapi --root-path /stac behind a ROOT_PATH=/stac proxy: POST /stac/collections/ -> {s} "
        f"Location={h.get('location')}; GET -> {s2} Location={h2.get('location')}",
    )

    paths = [
        "/stac/",
        "/stac/conformance",
        f"/stac/collections/{GLAD}",
        f"/stac/collections/{GLAD}/items?limit=2",
        f"/stac/collections/{GLAD}/items/{ITEM}",
        f"/stac/search?collections={GLAD}&limit=2",
        "/stac/queryables",
        f"/stac/collections/{GLAD}/queryables",
        "/stac/api",
    ]
    n_links, diffs, corrected = 0, [], 0
    for host in (
        "localhost:18888",
        "localhost:8084",
    ):  # browser via the Lab; kernel in the pod
        for p in paths:
            a, b = call(LIVE, "GET", p, host=host), call(port, "GET", p, host=host)
            ja, jb = json.loads(a[2]), json.loads(b[2])
            n_links += len(links(ja))
            # Expected change: the queryables $id gains the /stac prefix it lacks today.
            if (
                isinstance(ja, dict)
                and isinstance(jb, dict)
                and ja.get("$id") != jb.get("$id")
            ):
                if (jb.get("$id") or "") == (ja.get("$id") or "").replace(
                    f"http://{host}/", f"http://{host}/stac/", 1
                ):
                    corrected += 1
                    ja = ja | {"$id": jb["$id"]}
            if a[0] != b[0] or ja != jb:
                la, lb = links(ja), links(jb)
                first = next(((x, y) for x, y in zip(la, lb) if x != y), None)
                diffs.append(
                    f"{host}{p}: status {a[0]}/{b[0]}, first link diff {first}"
                    if la != lb
                    else f"{host}{p}: status {a[0]}/{b[0]}, body differs outside links"
                )
    report(
        "PASS" if not diffs and n_links else "FAIL",
        "fix.root-path.responses-unchanged",
        (
            f"{len(paths)} GET paths x 2 Host headers: bodies (incl. {n_links} links, OpenAPI) identical "
            f"to the running proxy, except {corrected} queryables $id that now carry /stac (corrected)"
        )
        if not diffs
        else f"{len(diffs)} difference(s): {diffs[:3]}",
    )

    tok = {"Authorization": f"Bearer {mint()}"}
    steps = []
    call(
        port, "DELETE", f"/stac/collections/{FIX_ID}", headers=tok
    )  # leftover from an earlier run
    s, h, _ = call(
        port, "POST", "/stac/collections/", body=collection(FIX_ID), headers=tok
    )
    steps.append(f"POST /stac/collections/ -> {s}")
    loc = urllib.parse.urlsplit(h.get("location", "")).path
    s, _, _ = call(
        port, "POST", loc, body=collection(FIX_ID), headers=tok
    )  # what fetch() does on a 307
    steps.append(f"POST {loc} -> {s}")
    created = s == 201
    doc = collection(FIX_ID) | {"title": "Spike root-path probe (edited)"}
    s, _, _ = call(port, "PUT", f"/stac/collections/{FIX_ID}", body=doc, headers=tok)
    steps.append(f"PUT -> {s}")
    edited = s == 200
    s, _, _ = call(port, "DELETE", f"/stac/collections/{FIX_ID}", headers=tok)
    steps.append(f"DELETE -> {s}")
    gone = call(LIVE, "GET", f"/stac/collections/{FIX_ID}")[0] == 404
    report(
        "PASS" if created and edited and gone else "FAIL",
        "fix.root-path.write-flow",
        f"Bearer token with stac:write, trailing-slash create as stac-manager sends it: "
        f"{' | '.join(steps)}; gone afterwards={gone}",
    )


if __name__ == "__main__":
    try:
        as_deployed()
    except Exception as e:  # noqa: BLE001
        report("FAIL", "probes.as-deployed", f"{type(e).__name__}: {e}")
    if "--fix" in sys.argv:
        try:
            fixed(int(sys.argv[sys.argv.index("--fix") + 1]))
        except Exception as e:  # noqa: BLE001
            report("FAIL", "fix.root-path", f"{type(e).__name__}: {e}")
