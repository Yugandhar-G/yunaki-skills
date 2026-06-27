"""API key enforcement middleware.

When enabled, every `/api/` request must carry a valid `X-API-Key` header,
except the auth endpoints (`/api/auth/*`) and the root/health/docs/static
surfaces. On success the resolved user is attached to `request.state.user` so
downstream dependencies can reuse it without re-verifying.

The middleware only touches HTTP. WebSocket auth is handled inline in the route
(BaseHTTPMiddleware does not intercept the WS scope).
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from yunaki_skills.api_models import err
from yunaki_skills.auth_store import AuthStore

logger = logging.getLogger(__name__)

# Path prefixes that never require a key.
_PUBLIC_PREFIXES = ("/api/auth",)
_PUBLIC_EXACT = {"/", "/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return True
    # Anything outside the /api/ surface (static assets, ws handshake) is open;
    # protected resources all live under /api/.
    return not path.startswith("/api/")


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_store: AuthStore, enabled: bool = True):
        super().__init__(app)
        self._auth = auth_store
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next):
        # Never gate CORS preflight — it carries no auth headers by design.
        if request.method == "OPTIONS":
            return await call_next(request)
        if not self._enabled or _is_public(request.url.path):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        user = self._auth.verify_key(api_key) if api_key else None
        if user is None:
            return JSONResponse(
                status_code=401,
                content=err("Missing or invalid API key (X-API-Key header)"),
            )

        # Cache the verified user for downstream dependencies.
        request.state.user = user.model_dump()
        return await call_next(request)
