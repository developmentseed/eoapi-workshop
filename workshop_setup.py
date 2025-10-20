"""
Workshop configuration helper for 2i2c JupyterHub environment.

Usage in notebooks:
    from workshop_setup import setup
    config = setup()

    # Access configuration
    print(config['stac_api_endpoint'])
    print(config['pghost'])
"""

import json
import os
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def setup(project_id: Optional[str] = None, token: Optional[str] = None):
    """
    Set up workshop environment by fetching configuration from Lambda.

    Args:
        project_id: Workshop project ID. If None, reads from WORKSHOP_PROJECT_ID env var
                   or prompts user.
        token: Workshop access token. If None, prompts user.

    Returns:
        dict: Configuration including database credentials and API endpoints
    """
    # Get project_id
    if project_id is None:
        project_id = os.environ.get("WORKSHOP_PROJECT_ID")

    if project_id is None:
        print("Enter workshop project ID (or press Enter for 'eoapiworkshop'):")
        project_id = input().strip() or "eoapiworkshop"

    # Construct config URL
    config_url = f"https://config.{project_id}.eoapi.dev"

    # Get token
    if token is None:
        token = os.environ.get("WORKSHOP_TOKEN")

    if token is None:
        print(f"\nFetching configuration from: {config_url}")
        print("Enter workshop access token:")
        token = input().strip()

    # Fetch configuration
    try:
        request = Request(config_url)
        request.add_header("Authorization", f"Bearer {token}")

        with urlopen(request, timeout=10) as response:
            config = json.loads(response.read().decode())

        # Set environment variables for compatibility with existing code
        os.environ["PGHOST"] = config["pghost"]
        os.environ["PGPORT"] = config["pgport"]
        os.environ["PGDATABASE"] = config["pgdatabase"]
        os.environ["PGUSER"] = config["pguser"]
        os.environ["PGPASSWORD"] = config["pgpassword"]
        os.environ["STAC_API_ENDPOINT"] = config["stac_api_endpoint"]
        os.environ["TITILER_PGSTAC_API_ENDPOINT"] = config[
            "titiler_pgstac_api_endpoint"
        ]
        os.environ["TIPG_API_ENDPOINT"] = config["tipg_api_endpoint"]

        print("\n✓ Workshop environment configured successfully!")
        print(f"  STAC API: {config['stac_api_endpoint']}")
        print(f"  Raster API: {config['titiler_pgstac_api_endpoint']}")
        print(f"  Vector API: {config['tipg_api_endpoint']}")

        return config

    except HTTPError as e:
        if e.code == 401:
            raise ValueError(
                "Invalid workshop token. Please check with your instructor."
            )
        else:
            raise RuntimeError(f"Failed to fetch configuration: HTTP {e.code}")
    except URLError as e:
        raise RuntimeError(f"Failed to connect to configuration endpoint: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during configuration: {str(e)}")


# Convenience: auto-setup on import if running in interactive environment
if __name__ != "__main__":
    # Check if we're in a Jupyter notebook
    try:
        get_ipython()  # This will exist in Jupyter/IPython
        # Only auto-setup if not already configured
        if "PGHOST" not in os.environ and "WORKSHOP_PROJECT_ID" in os.environ:
            setup()
    except NameError:
        # Not in Jupyter, don't auto-setup
        pass
