"""Lab = the participant's front door: login + same-origin proxy to every service.

Needs LAB_PASSWORD and LAB_TOKEN in the environment (spike/.env locally, a
Secret in the chart). Services listen on localhost inside the shared network
namespace (the pod); jupyter-server-proxy exposes each one at /<name>/.
"""

import os

from jupyter_server.auth import passwd

c = get_config()  # noqa: F821

c.ServerApp.ip = "0.0.0.0"
c.ServerApp.port = 18888
c.ServerApp.open_browser = False
# Behind TLS-terminating ingress: honour X-Forwarded-Proto so the login cookie
# gets Secure and redirects stay https.
c.ServerApp.trust_xheaders = True

# One login: the password form; the token works too (form, ?token= or header).
c.PasswordIdentityProvider.hashed_password = passwd(os.environ["LAB_PASSWORD"])
c.PasswordIdentityProvider.allow_password_change = False
c.IdentityProvider.token = os.environ["LAB_TOKEN"]
# Explicit SameSite (Safari has no Lax default; Lax still sends the cookie on the
# OIDC redirect back to /browser/auth), and a login that ends with the workshop
# instead of tornado's 30 days (evidence/auth.md).
c.IdentityProvider.cookie_options = {"samesite": "Lax", "expires_days": 2}

# An OOM kills the whole Lab container (cgroup v2): reap idle kernels.
c.MappingKernelManager.cull_idle_timeout = 3600
c.MappingKernelManager.cull_interval = 300

# /proxy/<host>:<port> must never reach another participant's pod.
c.ServerProxy.host_allowlist = ["localhost", "127.0.0.1"]


def route(port, absolute_url):
    # No `command`: the service is already running in its own container.
    return {
        "port": port,
        "absolute_url": absolute_url,
        "launcher_entry": {"enabled": False},
    }


# absolute_url=True forwards /<name>/... unchanged: apps configured with that
# root path. False strips it: apps that serve at / and only *link* via the prefix.
c.ServerProxy.servers = {
    "stac": route(8084, True),  # stac-auth-proxy ROOT_PATH=/stac (404s without it)
    "raster": route(8082, True),  # TITILER_PGSTAC_API_ROOT_PATH=/raster
    "vector": route(8083, True),  # TIPG_ROOT_PATH=/vector
    "oidc": route(8085, True),  # mock-oidc root_path from ISSUER path /oidc
    "browser": route(8080, True),  # stac-browser nginx `location /browser/`
    "manager": route(8086, False),  # stac-manager http-server serves at /
}
