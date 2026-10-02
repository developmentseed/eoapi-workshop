"""The notebooks build browser URLs from the *_BROWSER_URL contract (no
`.replace("tipg", "localhost")` fallbacks), so the repo's docker-compose.yml must set it
too. Evaluate the URLs the notebook cells build under that file's jupyterhub env
(run in the Lab; no network). FAIL = a URL a laptop browser cannot open.

    python compose_env.py <path to the repo's docker-compose.yml>
"""

import os
import sys

import yaml

sys.dont_write_bytecode = True  # /home/jovyan/docs is the bind-mounted repo
sys.path.insert(0, "/home/jovyan/docs")
import workshop_setup as ws  # noqa: E402

env_list = yaml.safe_load(open(sys.argv[1]))["services"]["jupyterhub"]["environment"]
env = dict(e.split("=", 1) for e in env_list)

for k in [k for k in os.environ if k.endswith(("_ENDPOINT", "_BROWSER_URL", "_MANAGER_URL"))]:
    del os.environ[k]
os.environ.update(env)
e = ws.endpoints()
b = e["browser"]["browser"]
urls = {  # what the notebook cells build
    "03[11]": f"{e['stac']['browser']}/api.html",
    "04[3]": f"{e['raster']['browser']}/api.html",
    "04[29]": ws.to_browser(f"{e['raster']['server']}/external/WebMercatorQuad/map.html"),
    "05[16]": ws.to_browser(f"{e['vector']['server']}/collections/x/items"),
    "02[22]": f"{b}/collections/x" if b else f"https://radiantearth.github.io/stac-browser/#/external/{e['stac']['browser']}/collections/x",
    "06[2]": ws.to_browser(e["oidc"]["server"]),
    "08[10]": f"{b}/",
}
bad = {k: u for k, u in urls.items() if not u.startswith(("http://localhost:", "https://"))}
print(f"{'PASS' if not bad else 'FAIL'} compose-env.committed — repo docker-compose.yml jupyterhub env: "
      f"{len(urls) - len(bad)}/{len(urls)} notebook URLs open from a laptop; unreachable: {bad}")
