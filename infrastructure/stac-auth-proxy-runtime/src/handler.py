"""AWS Lambda handler for the STAC Auth Proxy.

Temporary replacement for eoapi-cdk's bundled `stac_auth_proxy_api.handler`, which
calls `app.router.startup()` -- removed in Starlette 1.0 -- and so raises
`AttributeError: 'APIRouter' object has no attribute 'startup'` at import, making
every request 500.

Fixed upstream on developmentseed/eoapi-cdk in `fix/stac-auth-proxy-lifespan`.
Delete this whole directory, and the `lambda_function_options` override in app.py,
once that lands in a release we can pin.
"""

import asyncio
import os
from typing import Any

from mangum import Mangum
from stac_auth_proxy import create_app


def _ensure_event_loop() -> asyncio.AbstractEventLoop:
    """Return the current event loop, creating and installing one if needed."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass

    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


app = create_app()
_asgi_handler = Mangum(app, lifespan="off")


def handler(event: Any, context: Any) -> dict[str, Any]:
    """Handle AWS Lambda events with a guaranteed current event loop."""
    _ensure_event_loop()
    return _asgi_handler(event, context)


if "AWS_EXECUTION_ENV" in os.environ:
    # Run the app's lifespan startup once per container.
    #
    # stac-auth-proxy's `create_app()` wires everything through
    # `lifespan=build_lifespan(...)`, so its upstream health and conformance checks
    # live in the lifespan context, not in legacy `on_startup` handlers.
    #
    # Mangum's lifespan="auto" is not a substitute: it runs the lifespan around
    # *every* invocation, repeating those upstream checks on each request. The
    # context is left open for the container's life and held in a module-level name
    # so it is not garbage collected.
    _loop = _ensure_event_loop()
    _lifespan_ctx = app.router.lifespan_context(app)
    _loop.run_until_complete(_lifespan_ctx.__aenter__())
