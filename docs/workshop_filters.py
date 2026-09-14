"""
Row-level authorization filters for the eoAPI workshop.

Mounted into the stac-auth-proxy container (see `docker-compose.yml`) and referenced
via `ITEMS_FILTER_CLS` / `COLLECTIONS_FILTER_CLS`.

A filter factory is a callable that receives the request context and returns a CQL2
expression. The proxy appends that expression to list requests (so filtering happens in
the database) and validates single-record reads and all writes against it.

Policy implemented here:

    collections named `private-<tenant>-*` are visible only to a JWT identifying
    `<tenant>`; every other collection is public.

Which claim names the tenant depends on the identity provider, so it is a parameter:

    local (mock-oidc)   `owner`      -- the mock server issues whatever claims we ask for
    deployed (Cognito)  `username`   -- Cognito access tokens carry `sub`, `username`,
                                        `scope` and `client_id`, and there is no way to
                                        add an `owner` claim without a Pre Token
                                        Generation Lambda

Both are configured the same way, via `..._FILTER_KWARGS` on the proxy; see
`docker-compose.yml` for local and `infrastructure/app.py` for the deployed stack.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

PRIVATE_PREFIX = "private-"

# `owner` is interpolated into a LIKE pattern, where `%` and `_` are wildcards. Returning
# CQL2-JSON already stops the claim from being parsed as an expression, but a claim of
# "%" would still widen the pattern to match other tenants' collections. Restricting the
# claim to an identifier-safe alphabet closes that off.
SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclasses.dataclass
class TenantFilter:
    """Hide `private-<tenant>-*` records from everyone but that tenant.

    Args:
        field: record property holding the collection id. Use `"id"` when filtering
            collections and `"collection"` when filtering items.
        claim: JWT claim naming the tenant. `"owner"` for the local mock OIDC server,
            `"username"` for Cognito access tokens in the deployed stack.
    """

    field: str = "collection"
    claim: str = "owner"

    async def __call__(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build a CQL2-JSON expression for this request."""
        not_private = {
            "op": "not",
            "args": [self._like(f"{PRIVATE_PREFIX}%")],
        }

        owner = (context.get("payload") or {}).get(self.claim)
        if not owner or not SAFE_OWNER.match(str(owner)):
            # Anonymous, or a claim we refuse to trust: public records only.
            return not_private

        return {
            "op": "or",
            "args": [not_private, self._like(f"{PRIVATE_PREFIX}{owner}-%")],
        }

    def _like(self, pattern: str) -> dict[str, Any]:
        return {"op": "like", "args": [{"property": self.field}, pattern]}


def demo() -> None:
    """Self-check: `python workshop_filters.py`."""
    import asyncio

    from cql2 import Expr

    def ctx(**payload: Any) -> dict[str, Any]:
        return {
            "req": {
                "method": "GET",
                "path": "/search",
                "query_params": {},
                "path_params": {},
                "headers": {},
            },
            "payload": payload,
        }

    items = TenantFilter(field="collection")

    def matches(context: dict[str, Any], collection: str) -> bool:
        expr = Expr(asyncio.run(items(context)))
        expr.validate()
        return expr.matches({"collection": collection})

    anon = ctx()
    assert matches(anon, "public-demo")
    assert matches(anon, "sentinel-2-c1-l2a")
    assert not matches(anon, "private-alice-notes")

    alice = ctx(owner="alice")
    assert matches(alice, "public-demo")
    assert matches(alice, "private-alice-notes")
    assert not matches(alice, "private-bob-notes")

    # A wildcard claim must not widen the pattern into other tenants' collections.
    attacker = ctx(owner="%")
    assert not matches(attacker, "private-alice-notes")

    # The deployed stack points the filter at Cognito's `username` claim instead,
    # because Cognito access tokens carry no `owner`. Same policy, different claim.
    cognito = TenantFilter(field="collection", claim="username")

    def cognito_matches(context: dict[str, Any], collection: str) -> bool:
        expr = Expr(asyncio.run(cognito(context)))
        expr.validate()
        return expr.matches({"collection": collection})

    # A realistic Cognito access token payload.
    cognito_alice = ctx(
        sub="9f6c1e2a-0000-4000-8000-000000000001",
        username="alice",
        scope="stac/read stac/write",
        token_use="access",
    )
    assert cognito_matches(cognito_alice, "public-demo")
    assert cognito_matches(cognito_alice, "private-alice-notes")
    assert not cognito_matches(cognito_alice, "private-bob-notes")

    # An `owner`-shaped token is anonymous to the Cognito-configured filter, and a
    # `username`-shaped one is anonymous to the default -- the claim must match the IdP.
    assert not cognito_matches(ctx(owner="alice"), "private-alice-notes")
    assert not matches(ctx(username="alice"), "private-alice-notes")

    print("workshop_filters: all checks passed")


if __name__ == "__main__":
    demo()
