"""Time the glad mosaic tiles the titiler map.html IFrame asks for, straight at titiler
(no browser, no Lab proxy), to separate titiler's own cost from host load.
Runs in the Lab's network namespace (run.sh). Prints one PASS/FAIL line.
"""

import time
import urllib.request

Q = "assets=lossyear&colormap_name=viridis&rescale=0%2C23"
BASE = "http://localhost:8082/raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad"
out = []
for z, x, y in [
    (0, 0, 0),
    (0, 0, 0),
    (3, 1, 2),
]:  # world view twice (cache?), then a zoomed-in tile
    t0 = time.time()
    try:
        with urllib.request.urlopen(f"{BASE}/{z}/{x}/{y}?{Q}", timeout=300) as r:
            r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    out.append(f"{z}/{x}/{y} -> {status} in {time.time() - t0:.1f} s")
first, again = (float(o.rsplit(" in ", 1)[1][:-2]) for o in out[:2])
note = (
    "first request was cold"
    if first > 3 * again + 1
    else "cache already warm from an earlier request: this run did not measure the cold cost"
)
print(
    f"{'PASS' if first < 30 else 'FAIL'} iframe.raster-world-tile-latency — direct to titiler-pgstac "
    f"(MOSAIC_CONCURRENCY=1, 100 glad items): {'; '.join(out)} ({note})",
    flush=True,
)
