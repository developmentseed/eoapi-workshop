"""
Helpers for authenticated STAC requests against the workshop's auth stack.

The local docker-compose stack is the default: `get_mock_oidc_token` needs
MOCK_OIDC_ENDPOINT and STAC_API_ENDPOINT (stac-auth-proxy).

`deployed_auth` and `get_cognito_token` are the hosted equivalents, for running the
read-side of chapter 7 against the deployed proxy without docker. They cannot do writes:
the deployed STAC API has the transaction extension disabled on purpose.
"""

from __future__ import annotations

import html
import json
import os
import re

import httpx

_TOKEN_PATTERN = re.compile(r'<textarea[^>]*id="token"[^>]*>(.*?)</textarea>', re.S)


def stac_endpoint() -> str:
    return os.getenv("STAC_API_ENDPOINT") or os.getenv("STAC_AUTH_PROXY_ENDPOINT", "")


def mock_oidc_endpoint() -> str | None:
    return os.getenv("MOCK_OIDC_ENDPOINT")


def require_local_auth_stack() -> tuple[str, str]:
    """Return (stac_endpoint, mock_oidc_endpoint) or raise."""
    stac = stac_endpoint()
    oidc = mock_oidc_endpoint()
    if not stac or not oidc:
        raise RuntimeError(
            "This notebook requires the docker-compose auth stack. "
            "Set STAC_API_ENDPOINT and MOCK_OIDC_ENDPOINT "
            "(run `docker compose up`)."
        )
    return stac, oidc


def get_mock_oidc_token(
    username: str = "test-user",
    scopes: str = "openid profile stac:read stac:write",
    *,
    claims: dict | None = None,
    oidc_endpoint: str | None = None,
    timeout: float = 10.0,
) -> str:
    """Request a bearer token from the mock OIDC server.

    Args:
        claims: extra claims to embed in the token, merged over the default `email`
            claim. Chapter 7 uses this to set the `owner` claim that drives row-level
            filtering.
    """
    oidc_endpoint = oidc_endpoint or mock_oidc_endpoint()
    if not oidc_endpoint:
        raise RuntimeError("MOCK_OIDC_ENDPOINT is not configured")

    response = httpx.post(
        f"{oidc_endpoint.rstrip('/')}/",
        data={
            "username": username,
            "scopes": scopes,
            "claims": json.dumps(
                {"email": f"{username}@example.com", **(claims or {})}
            ),
        },
        timeout=timeout,
    )
    response.raise_for_status()

    match = _TOKEN_PATTERN.search(response.text)
    if not match:
        raise RuntimeError("Mock OIDC response did not include a token")

    return html.unescape(match.group(1)).strip()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def deployed_auth(
    workshop_token: str,
    config_url: str | None = None,
    timeout: float = 20.0,
) -> dict[str, str]:
    """Look up the deployed proxy endpoint and Cognito details.

    Args:
        workshop_token: the bearer token for the config endpoint, the same one
            `workshop_setup.setup()` asks for.

    Returns a dict with `stac_endpoint`, `client_id`, `region` and `password`.
    """
    config_url = config_url or os.getenv(
        "CONFIG_API_ENDPOINT", "https://workshop-config.eoapi.dev"
    )
    response = httpx.get(
        config_url,
        headers=auth_headers(workshop_token),
        timeout=timeout,
    )
    response.raise_for_status()
    config = response.json()

    discovery = config.get("oidc_discovery_url", "")
    # https://cognito-idp.<region>.amazonaws.com/<pool>/.well-known/...
    region = discovery.split("://", 1)[-1].split(".")[1] if discovery else ""

    missing = [
        key
        for key, value in {
            "stac_auth_proxy_endpoint": config.get("stac_auth_proxy_endpoint"),
            "oidc_client_id": config.get("oidc_client_id"),
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"The config endpoint did not return {missing}. "
            "The deployment may predate the Cognito auth proxy."
        )

    return {
        "stac_endpoint": config["stac_auth_proxy_endpoint"],
        "client_id": config["oidc_client_id"],
        "region": region,
        "password": config.get("workshop_user_password", ""),
    }


def get_cognito_token(
    username: str,
    password: str,
    client_id: str,
    region: str,
    timeout: float = 20.0,
) -> str:
    """Return a Cognito access token for `username`, without a browser redirect.

    Uses `USER_PASSWORD_AUTH`, which the workshop's app client enables for exactly this
    reason. The resulting token carries the `username` claim the row-level filter reads,
    but *not* the `stac/write` scope, so it can read the catalog and never write to it.
    """
    response = httpx.post(
        f"https://cognito-idp.{region}.amazonaws.com/",
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        },
        json={
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": client_id,
            "AuthParameters": {"USERNAME": username, "PASSWORD": password},
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Cognito rejected the sign-in: {response.text}")

    return response.json()["AuthenticationResult"]["AccessToken"]
