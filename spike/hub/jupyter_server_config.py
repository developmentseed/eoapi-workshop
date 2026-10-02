"""Lab config under JupyterHub: only the same-origin proxy routes.

Login, port and base URL (/user/<name>/) come from jupyterhub-singleuser.
Each route is served at /user/<name>/<prefix>/ and, with absolute_url, the
backend receives that full path, so every backend's root path is
/user/{username}/<prefix> (spike/hub/values.yaml).
"""

c = get_config()  # noqa: F821

# An OOM kills the whole Lab container (cgroup v2): reap idle kernels.
c.MappingKernelManager.cull_idle_timeout = 3600
c.MappingKernelManager.cull_interval = 300

# /proxy/<host>:<port> must never reach another participant's pod.
c.ServerProxy.host_allowlist = ["localhost", "127.0.0.1"]


def route(port, absolute_url):
    return {"port": port, "absolute_url": absolute_url, "launcher_entry": {"enabled": False}}


c.ServerProxy.servers = {
    "stac": route(8084, True),
    "raster": route(8082, True),
    "vector": route(8083, True),
    "oidc": route(8085, True),
    "browser": route(8080, True),
    "manager": route(8086, False),  # serves at /, only links via PUBLIC_URL
}
