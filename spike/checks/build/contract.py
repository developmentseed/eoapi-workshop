"""docs/workshop_setup.py URL contract, evaluated in the Lab's real environment
(runs inside the lab container, cwd-independent: docs is mounted at
/home/jovyan/docs). Prints PASS|FAIL lines.
"""

import sys

import httpx

sys.path.insert(0, "/home/jovyan/docs")
import workshop_setup as ws  # noqa: E402

LAB = "http://localhost:18888"
GLAD = "glad-global-forest-change-1.11"
e = ws.endpoints()


def report(ok, name, detail):
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}")


want = {
    "stac": ("http://localhost:8084/stac", f"{LAB}/stac"),
    "raster": ("http://localhost:8082/raster", f"{LAB}/raster"),
    "vector": ("http://localhost:8083/vector", f"{LAB}/vector"),
    "oidc": ("http://localhost:8085/oidc", f"{LAB}/oidc"),
    "browser": (None, f"{LAB}/browser"),
    "manager": (None, f"{LAB}/manager"),
}
got = {k: (v["server"], v["browser"]) for k, v in e.items()}
report(got == want, "contract.endpoints", str(got))

# Server-side tilejson -> to_browser() must give a browser URL under the Lab.
item = httpx.get(
    f"{e['stac']['server']}/collections/{GLAD}/items", params={"limit": 1}
).json()["features"][0]
tj = httpx.get(
    f"{e['raster']['server']}/collections/{GLAD}/items/{item['id']}/WebMercatorQuad/tilejson.json",
    params={"assets": next(iter(item["assets"]))},
).json()
server_tiles = tj["tiles"][0]
browser_tiles = ws.to_browser(server_tiles)
report(
    server_tiles.startswith(e["raster"]["server"] + "/")
    and browser_tiles.startswith(f"{LAB}/raster/"),
    "contract.to_browser",
    f"{server_tiles[:60]}… -> {browser_tiles[:60]}…",
)
report(
    ws.to_browser("https://example.com/x") == "https://example.com/x",
    "contract.to_browser-passthrough",
    "foreign URL unchanged",
)
report(
    ws.collection_id() == "u01-sentinel-2-c1-l2a",
    "contract.collection_id",
    ws.collection_id(),
)
