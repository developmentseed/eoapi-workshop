"""
Helpers for authenticated STAC transaction requests in the local docker-compose stack.

Requires MOCK_OIDC_ENDPOINT and STAC_API_ENDPOINT (stac-auth-proxy).
"""

from __future__ import annotations

import html
import json
import os
import re

import httpx

_TOKEN_PATTERN = re.compile(
    r'<textarea[^>]*id="token"[^>]*>(.*?)</textarea>', re.S
)


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
    oidc_endpoint: str | None = None,
    timeout: float = 10.0,
) -> str:
    """Request a bearer token from the mock OIDC server."""
    oidc_endpoint = oidc_endpoint or mock_oidc_endpoint()
    if not oidc_endpoint:
        raise RuntimeError("MOCK_OIDC_ENDPOINT is not configured")

    response = httpx.post(
        f"{oidc_endpoint.rstrip('/')}/",
        data={
            "username": username,
            "scopes": scopes,
            "claims": json.dumps({"email": f"{username}@example.com"}),
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
