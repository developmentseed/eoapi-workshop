"""
Workshop helpers: service URLs and database credentials.

Usage in notebooks:
    from workshop_setup import setup
    config = setup()
"""

import os
import random

import httpx

# --- URL contract -----------------------------------------------------------
# Server-side: what the kernel calls. Browser-facing: absolute prefixes (scheme
# included, may carry a path, e.g. https://lab-u01.<base>/raster); code only
# appends to them. An unset browser URL falls back to the server URL.
_SERVICES = {
    # name: (server-side var, browser-facing var)
    "stac": ("STAC_API_ENDPOINT", "STAC_API_BROWSER_URL"),
    "raster": ("TITILER_PGSTAC_API_ENDPOINT", "TITILER_BROWSER_URL"),
    "vector": ("TIPG_API_ENDPOINT", "TIPG_BROWSER_URL"),
    "oidc": ("MOCK_OIDC_ENDPOINT", "MOCK_OIDC_BROWSER_URL"),  # unset: ch. 6-8 raise
    "browser": (None, "STAC_BROWSER_URL"),
    "manager": (None, "STAC_MANAGER_URL"),
}


def endpoints() -> dict[str, dict[str, str | None]]:
    """{service: {"server": url | None, "browser": url | None}}, without trailing /."""
    out = {}
    for name, (server_var, browser_var) in _SERVICES.items():
        server = (os.getenv(server_var, "") if server_var else "").rstrip("/") or None
        browser = os.getenv(browser_var, "").rstrip("/") or server
        out[name] = {"server": server, "browser": browser}
    return out


def to_browser(url: str) -> str:
    """Swap a server-side prefix for its browser-facing one (e.g. tilejson tiles)."""
    for e in endpoints().values():
        server, browser = e["server"], e["browser"]
        if server and browser and (url == server or url.startswith(server + "/")):
            return browser + url[len(server) :]
    return url


def show_links() -> None:
    """Render this participant's clickable service links in the notebook."""
    from IPython.display import HTML, display

    labels = {
        "stac": "STAC API",
        "raster": "Raster API (titiler-pgstac)",
        "vector": "Vector API (tipg)",
        "browser": "STAC Browser",
        "manager": "STAC Manager",
    }
    items = [
        f'<li><a href="{e["browser"]}/" target="_blank">{labels[name]}</a></li>'
        for name, e in endpoints().items()
        if name in labels and e["browser"]
    ]
    display(HTML(f"<ul>{''.join(items)}</ul>"))


def workshop_user() -> str:
    return os.getenv("WORKSHOP_USER") or os.getenv("JUPYTERHUB_USER") or "workshop"


def collection_id(base: str = "sentinel-2-c1-l2a") -> str:
    """This participant's collection id, e.g. u01-sentinel-2-c1-l2a."""
    return f"{workshop_user()}-{base}"


def setup(token: str | None = None):
    """
    Fetch database credentials from workshop config endpoint.

    If the PG* variables are already set (compose, the participant pod), skips
    fetching and returns them.

    Args:
        token: Workshop access token. If None, prompts user.

    Returns:
        dict: Configuration including database credentials
    """

    # Check if we're in docker-compose runtime (all PG* vars already set)
    pg_vars = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    if all(var in os.environ for var in pg_vars):
        print("✓ Database credentials already configured")

        # Return existing configuration
        return {
            "pghost": os.environ["PGHOST"],
            "pgport": os.environ["PGPORT"],
            "pgdatabase": os.environ["PGDATABASE"],
            "pguser": os.environ["PGUSER"],
            "pgpassword": os.environ["PGPASSWORD"],
        }

    # Construct config URL
    config_url = os.environ.get(
        "CONFIG_API_ENDPOINT", "https://workshop-config.eoapi.dev"
    )

    # Get token
    if token is None:
        token = os.environ.get("WORKSHOP_TOKEN")

    if token is None:
        print(f"Fetching database credentials from: {config_url}")
        print("Enter workshop access token:")
        token = input().strip()

    # Fetch configuration
    try:
        response = httpx.get(
            config_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        response.raise_for_status()
        config = response.json()

        # Set database environment variables
        os.environ["PGHOST"] = config["pghost"]
        os.environ["PGPORT"] = config["pgport"]
        os.environ["PGDATABASE"] = config["pgdatabase"]
        os.environ["PGUSER"] = config["pguser"]
        os.environ["PGPASSWORD"] = config["pgpassword"]

        print("\n✓ Database credentials configured successfully!")

        return config

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise ValueError(
                "Invalid workshop token. Please check with your instructor."
            )
        else:
            raise RuntimeError(
                f"Failed to fetch configuration: HTTP {e.response.status_code}"
            )
    except httpx.RequestError as e:
        raise RuntimeError(f"Failed to connect to configuration endpoint: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during configuration: {str(e)}")


# random land points, each with Sentinel-2 items for notebook 02's search
# (none south of 85°S, where the search returns nothing).
random_land_points = [
    [51.85, 22.78],
    [42.34, 33.96],
    [112.52, 43.12],
    [-27.49, -77.08],
    [12.8, 22.03],
    [-48.67, -80.69],
    [-112.84, 63.05],
    [-53.68, -9.73],
    [73.01, -84.82],
    [154.16, -77.2],
    [-122.4, -78.54],
    [1.11, 15.39],
    [112.38, 62.07],
    [49.41, 11.31],
    [-65.21, -35.3],
    [-137.31, -80.57],
    [-101.84, 22.73],
    [123.2, -74.95],
    [115.02, 45.55],
    [83.67, 72.11],
    [7.26, 45.27],
    [45.91, 61.35],
    [130.99, -73.85],
    [150.74, -27.96],
    [-120.51, 73.64],
    [143.15, 70.9],
    [141.01, -23.53],
    [12.48, 29.88],
    [103.77, 69.62],
    [133.72, 55.61],
    [41.87, 65.59],
    [148.09, -37.47],
    [44.16, 37.43],
    [87.76, 39.51],
    [113.19, 64.65],
    [41.79, 66.13],
    [16.25, -82.69],
    [0.36, 33.02],
    [81.48, -75.85],
    [73.24, 25.57],
    [56.36, 53.31],
    [-101.91, -79.09],
    [144.46, -76.22],
    [82.92, 53.81],
    [0.74, 24.15],
    [135.72, -33.17],
    [-103.64, -79.66],
    [-63.6, -23.18],
    [73.93, -72.64],
    [-137.13, -78.67],
    [38.78, 33.61],
    [107.14, 38.67],
    [-98.47, 39.79],
    [-4.86, 16.17],
    [0.43, 46.71],
    [10.36, 24.8],
    [78.02, 65.32],
    [0.61, 22.84],
    [-145.02, -78.36],
    [-66.43, -39.0],
    [-20.23, 77.8],
    [105.31, -84.76],
    [-10.07, 53.55],
    [93.5, -69.97],
    [63.43, 52.8],
    [27.94, -26.25],
    [-71.36, -13.47],
    [-91.96, 76.58],
    [130.77, -83.12],
    [44.38, 7.34],
    [89.35, 38.01],
    [75.9, 21.85],
    [-30.85, 77.14],
    [136.97, -84.39],
    [-43.75, -20.63],
    [21.31, -80.99],
    [-79.02, -78.54],
    [8.1, 8.33],
    [29.55, -71.78],
    [87.92, 53.22],
    [-47.53, -16.27],
    [-41.31, -84.21],
    [-104.27, 57.77],
    [-74.63, 20.26],
    [-140.12, 60.69],
    [-53.09, -1.05],
    [132.28, -17.58],
    [-127.24, 64.42],
    [25.21, -20.95],
    [97.07, 40.32],
    [9.05, 5.04],
]


def get_random_point():
    """Get a random pair of coordinates from the set of random points"""
    return random.sample(random_land_points, 1)[0]
