"""
Workshop database credentials helper for 2i2c JupyterHub environment.

Usage in notebooks:
    from workshop_setup import setup
    config = setup()

    # Access database configuration
    print(config['pghost'])
    print(config['pgdatabase'])

Note: API endpoints are already configured in the environment via the start script.
"""

import os
import random
from typing import Optional

import httpx


def setup(token: Optional[str] = None):
    """
    Fetch database credentials from workshop config endpoint.

    API endpoints (STAC, Raster, Vector) are already configured in the environment
    via the start script. This function only fetches database credentials.

    If running in docker-compose (detected by existing PG* env vars), skips fetching
    and returns the existing configuration.

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
        print(f"  Host: {config['pghost']}")
        print(f"  Database: {config['pgdatabase']}")

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


# random set of 100 points from continental land masses
random_land_points = [
    [51.85, 22.78],
    [42.34, 33.96],
    [112.52, 43.12],
    [-27.49, -77.08],
    [12.8, 22.03],
    [25.5, -89.99],
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
    [82.46, -86.63],
    [141.01, -23.53],
    [12.48, 29.88],
    [103.77, 69.62],
    [133.72, 55.61],
    [41.87, 65.59],
    [148.09, -37.47],
    [44.16, 37.43],
    [87.76, 39.51],
    [113.19, 64.65],
    [-92.51, -86.57],
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
    [1.65, -89.03],
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
    [-111.18, -85.34],
    [75.9, 21.85],
    [-30.85, 77.14],
    [136.97, -84.39],
    [-43.75, -20.63],
    [21.31, -80.99],
    [-92.31, -88.19],
    [-79.02, -78.54],
    [8.1, 8.33],
    [29.55, -71.78],
    [87.92, 53.22],
    [-47.53, -16.27],
    [-41.31, -84.21],
    [118.24, -88.41],
    [-104.27, 57.77],
    [-74.63, 20.26],
    [-140.12, 60.69],
    [-53.09, -1.05],
    [-61.95, -88.61],
    [132.28, -17.58],
    [-127.24, 64.42],
    [-116.36, -86.78],
    [25.21, -20.95],
    [97.07, 40.32],
    [9.05, 5.04],
]


def get_random_point():
    """Get a random pair of coordinates from the set of random points"""
    return random.sample(random_land_points, 1)[0]
