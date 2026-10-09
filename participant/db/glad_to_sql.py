"""Print SQL that upserts one STAC collection and its items inside the given
bboxes ("w,s,e,n") into pgstac.

Build-time only (db/Dockerfile). Same effect as pypgstac's Loader with
Methods.upsert. The collection's spatial extent becomes the union of the loaded
items, so titiler's map.html opens on them rather than on the whole world.
"""

import json
import sys
import urllib.parse
import urllib.request

src, collection, bboxes = sys.argv[1], sys.argv[2], sys.argv[3:]


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


coll = get(f"{src}/collections/{collection}")
# The source's own queryables and tilejson links would send STAC Browser to MAAP's
# API and tiler; stac-fastapi regenerates self/root/parent/items itself.
coll["links"] = [
    lk for lk in coll.get("links", []) if lk.get("rel") in ("license", "cite-as")
]
items = {}
for bbox in bboxes:
    q = {"collections": collection, "bbox": bbox, "limit": 100}
    url = f"{src}/search?{urllib.parse.urlencode(q)}"
    while url:
        page = get(url)
        items.update((f["id"], f) for f in page["features"])
        url = next((lk["href"] for lk in page["links"] if lk["rel"] == "next"), None)
items = list(items.values())
boxes = [f["bbox"] for f in items]
coll["extent"]["spatial"]["bbox"] = [
    [min(b[0] for b in boxes), min(b[1] for b in boxes)]
    + [max(b[2] for b in boxes), max(b[3] for b in boxes)]
]


def literal(obj):
    text = json.dumps(obj)
    assert "$stac$" not in text
    return f"$stac${text}$stac$::jsonb"


print("SET search_path TO pgstac, public;")
print(f"SELECT pgstac.upsert_collection({literal(coll)});")
print(f"SELECT pgstac.upsert_items({literal(items)});")
print(f"-- {collection}: collection + {len(items)} items", file=sys.stderr)
