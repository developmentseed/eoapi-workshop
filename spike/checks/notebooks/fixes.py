"""Notebook edits (applied to docs/, spike/evidence/fix.md) and the classification of
every errored cell.

FIXES:      {notebook: [{"cell": index, "expect": the text before the edit, "source": new}]}
            whole-cell replacements, tested on copies first (evidence/notebooks.md); the
            `docs` phase now checks they are still in docs/. Cell indexes are 0-based, as
            in nbformat and the `cell.<phase>.<nb>[i]` check names.
MD_REPLACE: {(notebook, cell): (old passage, new passage)} for markdown kept otherwise.
LINKS:      cells of 06/07/08 the `fixed` phase runs on their own, without the STAC
            writes (06-08 write data and run once, in the `writes` phase).
CLASSES: (phase or "*", notebook, cell) -> (class, note); class letters as in report.py.
"""

FIXES = {
    "00-introduction": [
        {  # (a) compose ports in static text become plain text; the reader's own links render below
            "cell": 19,
            "expect": "- **STAC API** (stac-auth-proxy): <http://localhost:8084>",
            "source": """### 5.1 Local Development with Docker

This workshop includes a Docker Compose setup for running a full eoAPI stack and JupyterHub locally. See the [README](../README.md#local-development) for Docker installation and GitHub Container Registry authentication.

```bash
git clone https://github.com/developmentseed/eoapi-workshop.git
cd eoapi-workshop
docker compose up
```

This starts the following services on `localhost`:

- pgstac (PostgreSQL): port 5439
- **STAC API** (stac-auth-proxy): port 8084 — primary entry point; reads are public, writes require authentication
- stac-fastapi-pgstac: port 8081 — upstream API (debugging only)
- mock-oidc-server: port 8085
- titiler-pgstac: port 8082
- tipg: port 8083
- stac-browser: port 8080
- stac-manager: port 8086 — web UI for authenticated STAC edits
- JupyterHub: port 8888 — run these notebooks interactively

Open JupyterHub and work through the notebooks in `/docs`. Chapter 3 covers read-only STAC API access; [chapter 6](./06-stac_transactions_auth.ipynb) exercises authenticated transactions.

The pgstac database is accessible via `psql` on port 5439:
```bash
psql postgresql://username:password@localhost:5439/postgis
```

In the hosted workshop you already have your own stack: the cell at the end of this page lists its links.""",
        },
        {  # (a) the empty last cell renders this participant's own links
            "cell": 23,
            "expect": "",
            "source": """# Your own eoAPI stack. Every link opens behind your Lab login.
from workshop_setup import show_links

show_links()""",
        },
    ],
    "02-database": [
        {  # (c)
            "cell": 0,
            "expect": "- You will be using the `username` value to create a unique STAC collection",
            "source": """# 2. The Database: pgstac

**pgstac** is a PostgreSQL extension that enables STAC metadata management in a PostgreSQL database.
eoAPI is useful to many organizations because the other components are configured to work seamlessly with STAC metadata that is stored in your pgstac database.

**pypgstac** is a Python package for interacting with a pgstac database. You will learn how to use pypgstac to perform the following operations on a pgstac database:
1. Generate STAC collection record
2. Add the record to the `collections` table with `Loader.load_collections`
3. Generate STAC item records
4. Add new records to the `items` table with `Loader.load_items`
5. Delete an item from the `items` table

For production deployments your STAC metadata generation and ingestion workflow will probably not take place in a notebook but the basic steps will be the same!

Fill in the input boxes below to get started with your own personal Sentinel-2 STAC collection!
- Your collection id comes from your workshop user name (`collection_id()` in `workshop_setup.py`), so it is unique to you
- Set a location that is special to you in the lat/lon field - this will determine the spatial extent of your STAC collection
- You will need to enter the database credentials here in order to post data to the database in this notebook.""",
        },
        {  # (c)
            "cell": 3,
            "expect": "Now you can chose a unique username and a location",
            "source": "Now you can choose a location from which you will generate your own personal Sentinel-2 STAC Collection. Feel free to use the default values, but if you are interested in looking at some satellite imagery from a particular place, this is your chance to pick one!",
        },
        {  # (c) no username widget
            "cell": 4,
            "expect": "username_input = widgets.Text(",
            "source": """import os

import ipywidgets as widgets
from IPython.display import display

lat_input = widgets.BoundedFloatText(
    value=default_lat,
    min=-90,
    max=90,
    placeholder="enter the latitude of your hometown",
    description="latitude:",
    disabled=False,
)
lon_input = widgets.BoundedFloatText(
    value=default_lon,
    min=-180,
    max=180,
    placeholder="enter the longitude of your hometown",
    description="longitude:",
    disabled=False,
)

# Display the widgets
display(lat_input)
display(lon_input)""",
        },
        {  # (c) collection id from the helper
            "cell": 6,
            "expect": 'collection_id = f"{username_input.value}-sentinel-2-c1-l2a"',
            "source": """import pystac_client
from pystac import Collection, Extent, SpatialExtent, TemporalExtent
from pystac.utils import str_to_datetime
from pypgstac.db import PgstacDB
from pypgstac.load import Loader, Methods
from shapely.geometry import Point

import workshop_setup

stac_api_endpoint = os.getenv("STAC_API_ENDPOINT")

collection_id = workshop_setup.collection_id()  # e.g. u01-sentinel-2-c1-l2a
bbox = Point(lon_input.value, lat_input.value).buffer(2).bounds

temporal_extent = [
    str_to_datetime("2025-01-01T00:00:00Z"),
    str_to_datetime("2025-04-18T00:00:00Z"),
]

my_collection = Collection(
    id=collection_id,
    description=f"{workshop_setup.workshop_user()}'s personal Sentinel-2 L2A collection",
    extent=Extent(
        spatial=SpatialExtent([[*bbox]]),
        temporal=TemporalExtent([temporal_extent]),
    ),
)
my_collection""",
        },
        {  # (a) this stack's STAC Browser, history-mode deep link
            "cell": 22,
            "expect": 'stac_browser_endpoint = os.getenv("STAC_BROWSER_ENDPOINT")',
            "source": """from IPython.display import IFrame
from workshop_setup import endpoints

# Use the stack's own STAC Browser (its catalog is already this STAC API); without
# one, fall back to the public STAC Browser in external mode.
urls = endpoints()
if urls["browser"]["browser"]:
    browser_url = f"{urls['browser']['browser']}/collections/{my_collection.id}"
else:
    browser_url = f"https://radiantearth.github.io/stac-browser/#/external/{urls['stac']['browser']}/collections/{my_collection.id}"

print(browser_url)
IFrame(
    browser_url,
    1200,
    800,
)""",
        },
        {  # hygiene from the plan: scope the DELETE to this collection
            "cell": 24,
            "expect": "cur.execute(f\"DELETE FROM items where id = '{items[-1].id}';\")",
            "source": """with db.connect() as conn:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM items WHERE id = %s AND collection = %s;",
        (items[-1].id, my_collection.id),
    )
    cur.close()
    conn.commit()""",
        },
    ],
    "03-stac_fastapi_pgstac": [
        {  # (a) print the URL the participant can open
            "cell": 2,
            "expect": "print(stac_api_endpoint)",
            "source": """import json
import os

import httpx
from workshop_setup import to_browser

stac_api_endpoint = os.getenv("STAC_API_ENDPOINT")

conformance_response = httpx.get(f"{stac_api_endpoint}/conformance").json()

print(to_browser(stac_api_endpoint))
print(json.dumps(conformance_response, indent=2))""",
        },
        {  # (a) no replace() heuristic
            "cell": 11,
            "expect": 'stac_api_endpoint.replace("stac-auth-proxy:8000", "localhost:8084")',
            "source": """from IPython.display import IFrame
from workshop_setup import endpoints

local_stac_api_endpoint = endpoints()["stac"]["browser"]
api_docs = (
    f"{local_stac_api_endpoint}/api.html#/default/Get_Collections_collections_get"
)
print(api_docs)

IFrame(
    api_docs,
    1200,
    800,
)""",
        },
        {  # (c)
            "cell": 13,
            "expect": "go back to make a username",
            "source": "Your collection id comes from your workshop user name (chapter 2 created it). If you skipped chapter 2, run it first.",
        },
        {  # (c) no username widget
            "cell": 14,
            "expect": "username_input = widgets.Text(",
            "source": """from IPython.display import display
from workshop_setup import collection_id, workshop_user

print(f"user: {workshop_user()}  collection: {collection_id()}")""",
        },
        {  # (c)
            "cell": 15,
            "expect": "filter=f\"id LIKE '%{username_input.value}%'\"",
            "source": """# using pystac-client: every collection whose id starts with your user name
my_collection_search = client.collection_search(
    filter=f"id LIKE '{workshop_user()}-%'"
)

results = my_collection_search.collection_list()

my_collection = next(c for c in results if c.id == collection_id())
display(my_collection)""",
        },
        {  # (c)
            "cell": 17,
            "expect": "params={\"filter\": f\"id LIKE '%{username_input.value}%'\"}",
            "source": """# using http client
print(
    json.dumps(
        httpx.get(
            f"{stac_api_endpoint}/collections",
            params={"filter": f"id LIKE '{workshop_user()}-%'"},
        ).json(),
        indent=2,
    )
)""",
        },
        {  # (e) stac-auth-proxy 1.2.0 turns %2B into a raw "+" (a space upstream): use Z
            "cell": 23,
            "expect": "datetime_string = datetime(2025, 1, 4, tzinfo=UTC).isoformat()",
            "source": """# "Z", not "+00:00": the auth proxy re-sends the query unencoded and a "+" arrives as a space
datetime_string = datetime(2025, 1, 4, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

item_search_request = httpx.get(
    f"{stac_api_endpoint}/search",
    params={
        "collections": my_collection.id,
        "datetime": f"{datetime_string}/..",  # open interval from 2025-01-04 forward
        "limit": 1,  # one result per page for brevity in this example
    },
)

print(json.dumps(item_search_request.json(), indent=2))""",
        },
        {  # (e) same proxy bug
            "cell": 28,
            "expect": "datetime_string = datetime(2025, 1, 4, tzinfo=UTC).isoformat()",
            "source": """datetime_string = datetime(2025, 1, 4, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

item_search_request = httpx.get(
    f"{stac_api_endpoint}/collections/{my_collection.id}/items",
    params={
        "datetime": f"{datetime_string}/..",  # open interval from 2025-01-04 forward
        "limit": 1000,
        "filter": "eo:cloud_cover < 10",  # less than 10% cloud cover
    },
)
response = item_search_request.json()
print(f"found {len(response['features'])} items")""",
        },
    ],
    "04-titiler_pgstac": [
        {  # (c) no username widget
            "cell": 1,
            "expect": "username_input = widgets.Text(",
            "source": """import workshop_setup

print(f"your collection: {workshop_setup.collection_id()}")""",
        },
        {  # (a) endpoints() instead of env + replace()
            "cell": 3,
            "expect": 'titiler_pgstac_endpoint.replace("titiler-pgstac", "localhost")',
            "source": """import os

from IPython.display import IFrame, Image
from workshop_setup import endpoints, to_browser

# what the kernel calls, and what your browser loads (IFrames, maps)
titiler_pgstac_endpoint = endpoints()["raster"]["server"]
titiler_browser_endpoint = endpoints()["raster"]["browser"]
api_docs = f"{titiler_browser_endpoint}/api.html"
print(api_docs)

IFrame(
    api_docs,
    1200,
    800,
)""",
        },
        {  # (c)
            "cell": 5,
            "expect": 'collection_id = f"{username_input.value}-sentinel-2-c1-l2a"',
            "source": """import json
from urllib.parse import urlencode

import httpx

collection_id = workshop_setup.collection_id()

params = (
    ("assets", "red"),
    ("assets", "green"),
    ("assets", "blue"),
    ("color_formula", "Gamma RGB 3.0 Saturation 1.2 Sigmoidal RGB 15 0.35"),
)""",
        },
        {  # (e) titiler-pgstac 3.2.0 (rio-tiler 9): expressions name bands b1..bN, in `assets` order
            "cell": 17,
            "expect": '("expression", "(nir - red) / (nir + red)")',
            "source": """params = (
    ("assets", "nir"),  # b1
    ("assets", "red"),  # b2
    ("asset_as_band", "True"),
    ("expression", "(b1 - b2) / (b1 + b2)"),
    ("colormap_name", "viridis"),
    ("rescale", "-0.5,1"),
)

IFrame(
    f"{titiler_browser_endpoint}/searches/{search_id}/WebMercatorQuad/map.html?{urlencode(params, doseq=True)}",
    1200,
    800,
)""",
        },
        {  # (a)
            "cell": 29,
            "expect": "str(map_request.url).replace(titiler_pgstac_endpoint, titiler_browser_endpoint)",
            "source": """map_request = httpx.get(
    f"{titiler_pgstac_endpoint}/external/WebMercatorQuad/map.html",
    params={
        "url": cog_href,
        "maxsize": 2048,
        "colormap": json.dumps({i: rgb for i, rgb in colormap.items()}),
    },
    timeout=None,
)


IFrame(
    to_browser(str(map_request.url)),
    1200,
    800,
)""",
        },
        {  # (a)
            "cell": 31,
            "expect": "str(map_request.url).replace(titiler_pgstac_endpoint, titiler_browser_endpoint)",
            "source": """map_request = httpx.get(
    f"{titiler_pgstac_endpoint}/collections/glad-global-forest-change-1.11/WebMercatorQuad/map.html",
    params={
        "assets": "lossyear",
        "colormap": json.dumps({i: rgb for i, rgb in colormap.items()}),
    },
    timeout=None,
)


IFrame(
    to_browser(str(map_request.url)),
    1200,
    800,
)""",
        },
    ],
    "05-tipg": [
        {  # (a)
            "cell": 3,
            "expect": 'tipg_endpoint.replace(\n    "tipg", "localhost"\n)',
            "source": """import json

import httpx
from workshop_setup import endpoints, to_browser

# what the kernel calls, and what your browser loads (IFrames, maps)
tipg_endpoint = endpoints()["vector"]["server"]
tipg_browser_endpoint = endpoints()["vector"]["browser"]

collections_request = httpx.get(f"{tipg_endpoint}/collections")

print(json.dumps(collections_request.json(), indent=2))""",
        },
        {  # (a)
            "cell": 16,
            "expect": "str(bbox_filtered_request.url).replace(tipg_endpoint, tipg_browser_endpoint)",
            "source": """from IPython.display import IFrame

bbox_filtered_request = httpx.get(
    f"{tipg_endpoint}/collections/{collection_id}/items",
    params={
        "bbox": "-77,39,-76,40",
        "f": "html",
    },
)

IFrame(
    to_browser(str(bbox_filtered_request.url)),
    width=1200,
    height=800,
)""",
        },
        {  # (a)
            "cell": 25,
            "expect": "str(viewer_request.url).replace(tipg_endpoint, tipg_browser_endpoint)",
            "source": """viewer_request = httpx.get(
    f"{tipg_endpoint}/collections/{collection_id}/tiles/WebMercatorQuad/map.html",
)

IFrame(
    to_browser(str(viewer_request.url)),
    width=1200,
    height=800,
)""",
        },
        {  # (a)
            "cell": 27,
            "expect": "str(filtered_viewer_request.url).replace(tipg_endpoint, tipg_browser_endpoint)",
            "source": """filtered_viewer_request = httpx.get(
    f"{tipg_endpoint}/collections/{collection_id}/tiles/WebMercatorQuad/map.html",
    params={
        "na_l2name": "MEDITERRANEAN CALIFORNIA",
    },
)

IFrame(
    to_browser(str(filtered_viewer_request.url)),
    width=1200,
    height=800,
)""",
        },
    ],
    "06-stac_transactions_auth": [
        {  # (a) print the URLs a participant can open
            "cell": 2,
            "expect": 'print(f"STAC API:  {stac_api_endpoint}")',
            "source": """import json
import time

import httpx

from stac_auth import auth_headers, get_mock_oidc_token, require_local_auth_stack
from workshop_setup import to_browser

stac_api_endpoint, mock_oidc_endpoint = require_local_auth_stack()

write_token = get_mock_oidc_token()
write_headers = auth_headers(write_token)

print(f"STAC API:  {to_browser(stac_api_endpoint)}")
print(f"Mock OIDC: {to_browser(mock_oidc_endpoint)}")
print(f"Token (truncated): {write_token[:16]}...")""",
        },
    ],
    "07-row_level_auth": [
        {  # (a)
            "cell": 7,
            "expect": 'print(f"STAC API: {stac_api_endpoint}")',
            "source": """import time

import httpx

from stac_auth import auth_headers, get_mock_oidc_token, require_local_auth_stack
from workshop_setup import to_browser

stac_api_endpoint, mock_oidc_endpoint = require_local_auth_stack()

alice = auth_headers(get_mock_oidc_token("alice", claims={"owner": "alice"}))
bob = auth_headers(get_mock_oidc_token("bob", claims={"owner": "bob"}))
anonymous = {}

print(f"STAC API: {to_browser(stac_api_endpoint)}")
print("Tokens issued for: alice, bob")""",
        },
    ],
    "08-stac_browser_auth": [
        {  # (a) the walkthrough points at "your STAC Browser", linked by the next cell
            "cell": 9,
            "expect": "open\n<http://localhost:8080> in a separate tab",
            "source": """## 8.4 Walkthrough: watch the catalog change

This part is hands-on in your browser. Run the cell below for a live frame, or open the
STAC Browser link it prints in a separate tab (a real tab is easier — the OIDC redirect
navigates away and back).

**Step 1 — anonymous.** Open your STAC Browser. You should see `public-demo` and the
collections from earlier chapters. Neither private collection is listed. Not greyed out, not
"access denied" — simply absent, because pgSTAC never returned them.

**Step 2 — log in as alice.** Click **Login** (top right). STAC Browser redirects to the
mock identity server, which shows a small login form. Enter:

- **Username:** `alice`
- **Claims:** `{"owner": "alice"}`

Submit. You land back on STAC Browser's `/auth` page, which hands the code to STAC Browser,
which exchanges it for a token and re-fetches the catalog.

**Step 3 — look again.** `private-alice-notebook` is now in the list. Same URL, same
endpoint, different rows — the `owner` claim in your token changed what pgSTAC returned.
`private-bob-notebook` is still missing.

**Step 4 — be bob.** Log out, log back in as `bob` with claims `{"owner": "bob"}`. The two
private collections swap places.

**Step 5 — try to cheat.** While logged in as bob, open the "Step 5" link the cell below
prints (alice's private collection). You get a not-found error, not a permission error.
Guessing the id gains nothing.""",
        },
        {  # (a)/(b) no hard-coded compose port
            "cell": 10,
            "expect": 'IFrame("http://localhost:8080", width="100%", height=600)',
            "source": """from IPython.display import IFrame
from workshop_setup import endpoints

stac_browser = endpoints()["browser"]["browser"]
print(f"Your STAC Browser: {stac_browser}/")
print(f"Step 5 link:       {stac_browser}/collections/{alice_id}")

IFrame(f"{stac_browser}/", width="100%", height=600)""",
        },
    ],
}

# Markdown edits that keep the original text and change one passage: (old, new).
MD_REPLACE = {
    ("03-stac_fastapi_pgstac", 1): (
        "In this workshop stack, the STAC API is exposed through stac-auth-proxy at `http://localhost:8084`.",
        "In this workshop stack, the STAC API is exposed through stac-auth-proxy (`STAC_API_ENDPOINT`; `http://localhost:8084` in docker compose).",
    ),
    ("04-titiler_pgstac", 0): (
        "Start by entering the username you picked when defining your personal Sentinel-2 L2A collection in [chapter 2](02-database.ipynb):",
        "Your personal Sentinel-2 L2A collection from [chapter 2](02-database.ipynb) is named after your workshop user name:",
    ),
    ("06-stac_transactions_auth", 0): (
        "<b>Note:</b> This chapter needs the local docker-compose auth stack (it reads <code>MOCK_OIDC_ENDPOINT</code>). It will not run against the hosted workshop deployment.",
        "<b>Note:</b> This chapter needs a stack with the mock identity provider (it reads <code>MOCK_OIDC_ENDPOINT</code>): the local docker-compose stack, or your own stack in the hosted workshop.",
    ),
    ("07-row_level_auth", 0): (
        "<b>Note:</b> This chapter needs the local docker-compose auth stack. It will not run against\nthe hosted workshop deployment.",
        "<b>Note:</b> This chapter needs a stack with the mock identity provider: the local\ndocker-compose stack, or your own stack in the hosted workshop.",
    ),
    ("08-stac_browser_auth", 0): (
        "<b>Note:</b> This chapter needs the local docker-compose stack. It will not run against the\nhosted workshop deployment.",
        "<b>Note:</b> This chapter needs a stack with STAC Browser and the mock identity provider:\nthe local docker-compose stack, or your own stack in the hosted workshop.",
    ),
    ("08-stac_browser_auth", 4): (
        "- **The redirect URI is not configurable.** STAC Browser always uses\n  `<its own origin>/auth`, so `http://localhost:8080/auth`. Your identity provider must\n  allow that exact URL. (The mock server accepts any redirect URI; a real one will not.)",
        "- **The redirect URI is not configurable.** STAC Browser always uses\n  `<its own origin><pathPrefix>auth`: `http://localhost:8080/auth` in compose, and\n  `<your Lab URL>/browser/auth` in the hosted workshop, where STAC Browser is served under\n  `/browser/`. Your identity provider must allow that exact URL. (The mock server accepts\n  any redirect URI; a real one will not.)",
    ),
    ("08-stac_browser_auth", 11): (
        "or by clearing site\ndata for <code>localhost:8080</code>.",
        "or by clearing site\ndata for STAC Browser's origin (in the hosted workshop that is your Lab's origin, so\nclearing it also logs you out of the Lab: prefer the private window).",
    ),
    ("08-stac_browser_auth", 17): (
        "- STAC Browser's redirect URI is fixed at `<origin>/auth`; register it with your identity\n  provider.",
        "- STAC Browser's redirect URI is fixed at `<origin><pathPrefix>auth`; register it with your\n  identity provider.",
    ),
}

# Cells of 06/07/08 the `fixed` phase runs on their own (no STAC writes in them).
LINKS = [("06-stac_transactions_auth", 2), ("07-row_level_auth", 7), ("08-stac_browser_auth", 10)]
LINKS_PRELUDE = 'alice_id = "private-alice-notebook"  # set by cell 6 in the full notebook 08'

_c = "username widget is empty when run headless; per-user stack: use collection_id()"
CLASSES = {
    # as-is, nobody typed a username: 03 filters LIKE '%%' and picks whatever comes first
    ("asis", "03-stac_fastapi_pgstac", 21): ("c", "LIKE '%%' picked the wrong collection (no items >= 2025-01-04); " + _c),
    ("asis", "03-stac_fastapi_pgstac", 26): ("c", "same wrong collection, no items with eo:cloud_cover; " + _c),
    ("asis", "04-titiler_pgstac", 7): ("c", "collection '-sentinel-2-c1-l2a' (empty username) not found; " + _c),
    ("asis", "04-titiler_pgstac", 12): ("c", "cascade from [7]: the collection does not exist; " + _c),
    ("asis", "04-titiler_pgstac", 14): ("c", "cascade from [12]"),
    ("asis", "04-titiler_pgstac", 17): ("c", "cascade from [12]"),
    # a default point with no Sentinel-2 items (9 of the 100 in workshop_setup; points.py)
    ("zeropoint", "02-database", 16): (
        "e", "default point (25.5, -89.99) -> earth-search returns 0 items -> items[0]; 9/100 default "
        "points do this, exactly the 9 south of 85S (points.py); drop them from random_land_points"),
    ("zeropoint", "02-database", 24): ("e", "cascade from [16]: items[-1] of an empty list"),
    ("zeropoint", "02-database", 26): ("e", "cascade from [16]: items[-1] of an empty list"),
    # any phase: stac-auth-proxy 1.2.0 + row-level filter re-sends the query string unencoded
    ("*", "03-stac_fastapi_pgstac", 23): (
        "e", "stac-auth-proxy 1.2.0 filter injection (utils/filters.py dict_to_query_string) re-sends the query "
        "unencoded: %2B -> '+' -> space -> 'Invalid RFC3339'; direct stac-fastapi returns 200; same config in compose"),
    ("*", "03-stac_fastapi_pgstac", 28): ("e", "same proxy bug as [23]: the 400 body has no 'features'"),
    ("*", "03-stac_fastapi_pgstac", 30): ("e", "cascade from [28]"),
    ("*", "03-stac_fastapi_pgstac", 32): ("e", "cascade from [28]"),
    # url.* / tile.* failures (same lookup)
    ("asis", "04-titiler_pgstac", 9): ("c", "map of '-sentinel-2-c1-l2a' (empty username): 404"),
    ("*", "04-titiler_pgstac", 17): (
        "e", "titiler-pgstac 3.2.0 / rio-tiler 9.4.4 names bands b1..bN: '(nir - red)' -> 400 on every tile, "
        "also direct on :8082, so the NDVI map is blank; '(b1 - b2) / (b1 + b2)' -> 200"),
    ("*", "02-database", 22): (
        "a", "reads STAC_BROWSER_ENDPOINT (renamed STAC_BROWSER_URL), so falls back to the public STAC Browser "
        "pointed at the kernel-side http://localhost:8084/stac; use endpoints()"),
    ("*", "03-stac_fastapi_pgstac", 2): ("a", "kernel-side URL printed; JupyterLab linkifies it, the click goes nowhere; print to_browser()"),
    ("*", "06-stac_transactions_auth", 2): ("a", "kernel-side URLs printed; print to_browser()"),
    ("*", "07-row_level_auth", 7): ("a", "kernel-side URL printed; print to_browser()"),
    ("*", "08-stac_browser_auth", 10): ("a", "IFrame hard-codes compose's http://localhost:8080; use endpoints()['browser']['browser']"),
}
