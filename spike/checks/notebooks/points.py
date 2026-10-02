"""How much data 02-database loads for each default point (run in the Lab).

02[2] picks `default_lon, default_lat = get_random_point()` from workshop_setup's 100
points, and 02[14] searches earth-search for Sentinel-2 L2A within +/-2 degrees,
2025-01-01..2025-04-18. This sends that exact search (pystac-client, same bbox and
datetime) and asks the API for the match count, so we know how many rows a participant
loads, and which points give 0 items (then 02[16] `items[0]` raises IndexError).
"""

import statistics
import sys

import pystac_client
from pystac.utils import str_to_datetime
from shapely.geometry import Point

sys.dont_write_bytecode = True  # /home/jovyan/docs is the bind-mounted repo
sys.path.insert(0, "/home/jovyan/docs")
from workshop_setup import random_land_points  # noqa: E402

client = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
dt = [str_to_datetime("2025-01-01T00:00:00Z"), str_to_datetime("2025-04-18T00:00:00Z")]
counts, errors = {}, {}
for lon, lat in random_land_points:
    bbox = Point(lon, lat).buffer(2).bounds  # as 02[6]
    for attempt in (1, 2):  # one retry: earth-search sometimes drops a connection
        try:
            counts[(lon, lat)] = client.search(
                collections="sentinel-2-c1-l2a", bbox=bbox, datetime=dt, max_items=1
            ).matched()
            errors.pop((lon, lat), None)
            break
        except Exception as exc:  # noqa: BLE001 - report every failure mode
            errors[(lon, lat)] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"

zero = sorted(p for p, n in counts.items() if not n)
vals = sorted(n for n in counts.values() if n is not None)
print(f"{'PASS' if not zero and not errors else 'FAIL'} points.02-default — "
      f"{len(random_land_points)} default points: {len(zero)} give 0 items {zero}, "
      f"{len(errors)} error {list(errors.items())[:3]}")
if vals:
    q, med = statistics.quantiles(vals, n=10), statistics.median(vals)
    near = min(counts.items(), key=lambda kv: abs(kv[1] - med))
    print(f"PASS points.02-volume — items loaded per participant: min {vals[0]}, "
          f"p10 {q[0]:.0f}, median {med:.0f} (e.g. {near}), p90 {q[-1]:.0f}, "
          f"max {vals[-1]} (top 3 {sorted(counts.items(), key=lambda kv: -(kv[1] or 0))[:3]})")
