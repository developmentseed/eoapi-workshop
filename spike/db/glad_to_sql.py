"""Print SQL that upserts one STAC collection and its first N items into pgstac.

Build-time only (db/Dockerfile). Mirrors the chart's features-loader-job
stac-loader, which used pypgstac's Loader with Methods.upsert.
"""

import json
import sys
import urllib.request

src, collection, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


coll = get(f"{src}/collections/{collection}")
# The source's own queryables and tilejson links would send STAC Browser to MAAP's
# API and tiler; stac-fastapi regenerates self/root/parent/items itself.
coll["links"] = [l for l in coll.get("links", []) if l.get("rel") in ("license", "cite-as")]
items = get(f"{src}/search?collections={collection}&limit={limit}")["features"]


def literal(obj):
    text = json.dumps(obj)
    assert "$stac$" not in text
    return f"$stac${text}$stac$::jsonb"


print("SET search_path TO pgstac, public;")
print(f"SELECT pgstac.upsert_collection({literal(coll)});")
print(f"SELECT pgstac.upsert_items({literal(items)});")
print(f"-- {collection}: collection + {len(items)} items", file=sys.stderr)
