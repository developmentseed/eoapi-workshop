"""Load generator for the footprint check.

Runs in a throwaway container that joins the Lab's network namespace
(docker run --network container:eoapi-spike-lab-1), so `localhost` is the pod
and its own CPU/memory are NOT charged to any stack container.

    python load.py <mode> <set>      mode: titiler | tipg | stac | kernel | all | inline
                                     set:  a | b (different tile centres, so the
                                           combined phase does not hit warm caches)

Prints one JSON line per sub-load. Needs LAB_TOKEN in the environment, except
`inline`, which runs the kernel's code in this process (used under a k8s-like
memory limit, outside the stack).

Routing mirrors real use:
- map tiles (titiler, tipg) go browser-style through the Lab's
  jupyter-server-proxy (localhost:18888/raster, /vector), so the Lab's own CPU
  under tile load is measured too;
- STAC searches go kernel-style straight to stac-auth-proxy (localhost:8084);
- the kernel is a real Lab kernel started through the Jupyter REST API.
"""

import json
import math
import os
import random
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import websocket

LAB = "http://localhost:18888"
TOKEN = os.environ.get("LAB_TOKEN", "")
# Header auth, not ?token=: jupyter-server-proxy would pass a query token
# through to the backend (build finding F1).
H = {"Authorization": f"token {TOKEN}"}
GLAD = "glad-global-forest-change-1.11"
CONCURRENCY = 4

# glad items cover 50-80N (100 tiles of 10x10 deg; 50-60N only west of 40W and
# east of 50E); ecoregions are global.
TITILER_CENTRES = {"a": [(-120, 55), (25, 63), (100, 60)], "b": [(-75, 52), (60, 62), (140, 62)]}
TIPG_CENTRES = {"a": [(-100, 40), (20, 0), (100, 30), (-60, -10)], "b": [(10, 50), (-120, 60), (135, -25), (30, -20)]}
# Each run shifts every centre by the same longitude offset (from FOOTPRINT_SEED),
# so a new run starts with cold titiler caches, as a fresh participant pod does.
# Re-use a seed to replay the exact same requests.
SEED = os.environ.get("FOOTPRINT_SEED", "0")
LON_SHIFT = random.Random(SEED).uniform(-30, 30)


def lonlat_to_tile(lon, lat, z):
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def tiles(centres, zooms, n, seed):
    """3x3 tiles around each centre at each zoom, shuffled (mixed zooms), first n."""
    out = set()
    for lon, lat in centres:
        lon = (lon + LON_SHIFT + 180) % 360 - 180
        for z in zooms:
            x0, y0 = lonlat_to_tile(lon, lat, z)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    x, y = x0 + dx, y0 + dy
                    if 0 <= x < 2**z and 0 <= y < 2**z:
                        out.add((z, x, y))
    out = sorted(out)
    random.Random(f"{SEED}-{seed}").shuffle(out)
    return out[:n]


def run(name, requests, headers):
    """requests: list of (method, url, json_body). Concurrency 4."""
    results = []
    lock = threading.Lock()
    client = httpx.Client(headers=headers, timeout=180)

    def one(req):
        method, url, body = req
        t = time.perf_counter()
        try:
            r = client.request(method, url, json=body)
            status, size = r.status_code, len(r.content)
        except Exception as e:  # noqa: BLE001 - record and keep going
            status, size = f"exc:{type(e).__name__}", 0
        with lock:
            results.append((status, size, time.perf_counter() - t))

    t0 = time.time()
    with ThreadPoolExecutor(CONCURRENCY) as ex:
        list(ex.map(one, requests))
    wall = time.time() - t0
    lat = sorted(r[2] for r in results)
    codes = {}
    for s, _, _ in results:
        codes[str(s)] = codes.get(str(s), 0) + 1
    out = {
        "load": name,
        "seed": SEED,
        "lon_shift": round(LON_SHIFT, 2),
        "n": len(results),
        "ok": sum(1 for s, _, _ in results if isinstance(s, int) and 200 <= s < 300),
        "codes": codes,
        "bytes": sum(r[1] for r in results),
        "wall_s": round(wall, 1),
        "p50_s": round(statistics.median(lat), 3),
        "p95_s": round(lat[int(0.95 * (len(lat) - 1))], 3),
        "max_s": round(lat[-1], 3),
        "t_start": t0,
        "t_end": t0 + wall,
    }
    print(json.dumps(out), flush=True)
    return out


def titiler(s):
    zooms = range(5, 13)
    ts = tiles(TITILER_CENTRES[s], zooms, 200, seed=s)
    q = "assets=treecover2000&rescale=0,100&colormap_name=greens"
    reqs = [
        ("GET", f"{LAB}/raster/collections/{GLAD}/tiles/WebMercatorQuad/{z}/{x}/{y}.png?{q}", None)
        for z, x, y in ts
    ]
    return run(f"titiler-{s}", reqs, H)


def tipg(s):
    ts = tiles(TIPG_CENTRES[s], range(1, 8), 100, seed=s)
    reqs = [
        ("GET", f"{LAB}/vector/collections/features.ecoregions/tiles/WebMercatorQuad/{z}/{x}/{y}", None)
        for z, x, y in ts
    ]
    return run(f"tipg-{s}", reqs, H)


def stac(s):
    rng = random.Random(f"{SEED}-stac-{s}")
    base = "http://localhost:8084/stac"
    reqs = []
    for i in range(50):
        lon, lat = rng.uniform(-180, 150), rng.uniform(50, 75)
        w = rng.choice([1, 5, 10, 30])
        bbox = [round(lon, 3), round(lat, 3), round(min(lon + w, 180), 3), round(min(lat + w / 2, 85), 3)]
        kind = i % 3
        if kind == 0:
            reqs.append(("POST", f"{base}/search", {"collections": [GLAD], "bbox": bbox, "limit": 100}))
        elif kind == 1:
            b = ",".join(map(str, bbox))
            reqs.append(("GET", f"{base}/collections/{GLAD}/items?bbox={b}&limit=100", None))
        else:
            reqs.append((
                "POST",
                f"{base}/search",
                {
                    "collections": [GLAD],
                    "bbox": bbox,
                    "datetime": "2000-01-01T00:00:00Z/2024-01-01T00:00:00Z",
                    "sortby": [{"field": "id", "direction": "desc"}],
                    "limit": 50,
                },
            ))
    # Kernel-style: no Lab token (stac-auth-proxy 401s a non-Bearer header).
    return run(f"stac-{s}", reqs, {})


# Runs INSIDE the Lab kernel. ~478 MiB uint8 window of a glad COG (notebook 04's
# cog_href), then one op that makes a same-size temporary, then hold it so the
# 2 s sampler sees the steady state.
KERNEL_CODE = r'''
import gc, json, os, sys, time
def _mem():
    d = {}
    for line in open("/proc/self/status"):
        k, v = line.split(":", 1)
        if k in ("VmRSS", "VmHWM"):
            d[k + "_MiB"] = int(v.split()[0]) // 1024
    return d
def _say(step, **kw):
    print(json.dumps({"step": step, "t": time.time(), "pid": os.getpid(), **_mem(), **kw}), flush=True)
_say("start")
# rioxarray/xarray/pandas are not in the workshop image: installed by run.sh
# into a private dir in the Lab container (the shared env is untouched).
sys.path.insert(0, "/tmp/spike-footprint-pylib")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
import numpy as np
import rioxarray
from osgeo import gdal
_say("imported", gdal_cachemax_MiB=gdal.GetCacheMax() // 2**20, rioxarray=rioxarray.__version__)
href = "https://nasa-maap-data-store.s3.us-west-2.amazonaws.com/file-staging/nasa-map/glad-global-forest-change-v1.11/Hansen_GFC-2023-v1.11_lossyear_40N_080W.tif"
t = time.time()
da = rioxarray.open_rasterio(href).isel(band=0, x=slice(0, 22400), y=slice(0, 22400)).load()
_say("loaded", seconds=round(time.time() - t, 1), shape=list(da.shape), dtype=str(da.dtype), nbytes_MiB=da.nbytes // 2**20)
n = int((da.values > 0).sum())
_say("computed", loss_pixels=n)
time.sleep(12)
_say("held")
del da
gc.collect()
_say("freed")
'''


def kernel(_s):
    c = httpx.Client(headers=H, timeout=60)
    others = [k["id"][:8] for k in c.get(f"{LAB}/api/kernels").json()]
    t0 = time.time()
    kid = c.post(f"{LAB}/api/kernels", json={"name": "python3"}).json()["id"]
    steps, error = [], None
    try:
        ws = websocket.create_connection(
            f"ws://localhost:18888/api/kernels/{kid}/channels",
            header=[f"Authorization: token {TOKEN}"],
            timeout=900,
        )
        msg_id = uuid.uuid4().hex
        ws.send(json.dumps({
            "header": {"msg_id": msg_id, "username": "spike-footprint", "session": uuid.uuid4().hex,
                       "msg_type": "execute_request", "version": "5.3"},
            "parent_header": {}, "metadata": {}, "channel": "shell", "buffers": [],
            "content": {"code": KERNEL_CODE, "silent": False, "store_history": False,
                        "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
        }))
        while True:
            m = json.loads(ws.recv())
            if m.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            t = m["msg_type"]
            if t == "stream":
                for line in m["content"]["text"].splitlines():
                    if line.startswith("{"):
                        steps.append(json.loads(line))
            elif t == "error":
                error = f"{m['content']['ename']}: {m['content']['evalue']}"
            elif t == "status" and m["content"]["execution_state"] == "idle":
                break
        ws.close()
    finally:
        c.delete(f"{LAB}/api/kernels/{kid}")
    out = {
        "load": "kernel",
        "kernel_id": kid[:8],
        "other_kernels_at_start": others,
        "error": error,
        "steps": steps,
        "peak_rss_MiB": max((s.get("VmHWM_MiB", 0) for s in steps), default=None),
        "t_start": t0,
        "t_end": time.time(),
    }
    print(json.dumps(out), flush=True)
    return out


def main():
    mode, s = sys.argv[1], sys.argv[2]
    if mode == "inline":
        exec(KERNEL_CODE, {})
        return
    fns = {"titiler": titiler, "tipg": tipg, "stac": stac, "kernel": kernel}
    if mode != "all":
        fns[mode](s)
        return
    # Everything at once: one participant with a map open while their kernel works.
    threads = [threading.Thread(target=f, args=(s,)) for f in fns.values()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
