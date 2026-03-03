from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.core.security import decode_token

CSRF_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
CSRF_EXEMPT_PATHS = (
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/language/toggle",
    "/api/tickets/submit",
    "/api/portal/",
)

# Paths that skip JWT validation entirely
PUBLIC_PATH_PREFIXES = (
    "/portal",
    "/ticket/",
    "/csat/",
    "/login",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/language/toggle",
    "/api/tickets/submit",
    "/api/portal/",
    "/health",
    "/static/",
    "/favicon.ico",
)

# HTML pages that should redirect to /login on 401 (not return JSON)
HTML_PAGE_PREFIXES = (
    "/dashboard",
    "/admin",
    "/supervisor",
    "/manager",
    "/kb",
    "/tickets",
    "/reports",
    "/settings",
    "/notifications",
)


def _is_public(path: str) -> bool:
    return any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES)


def _is_html_page(path: str) -> bool:
    """Returns True for browser HTML page routes (not API endpoints)."""
    return any(path.startswith(p) for p in HTML_PAGE_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Extracts and validates JWT from HttpOnly cookie or Authorization header.
    Also verifies the token JTI is still active in Redis (revocation support).
    Sets request.state.user to the decoded JWT payload dict on success.
    Redirects unauthenticated browser requests to /login instead of 401 JSON.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request.state.user = None

        path = request.url.path

        # Public paths — skip auth entirely
        if _is_public(path):
            return await call_next(request)

        token: str | None = None

        # 1. HttpOnly cookie (preferred — browser)
        token = request.cookies.get("access_token")

        # 2. Authorization: Bearer header (API / Swagger clients)
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.removeprefix("Bearer ").strip()

        if token:
            try:
                payload = decode_token(token)

                from app.core.redis import get_redis_pool
                jti = payload.get("jti")
                if jti:
                    redis = await get_redis_pool()
                    jti_valid = await redis.exists(f"jti:{jti}")
                    if jti_valid:
                        request.state.user = payload

            except Exception:
                request.state.user = None

        # If unauthenticated on an HTML page → redirect to /login
        if request.state.user is None and _is_html_page(path):
            return RedirectResponse(url=f"/login?next={path}", status_code=302)

        # CSRF protection: X-CSRF-Token header must match csrf_token cookie
        if (request.state.user
                and request.method not in CSRF_SAFE_METHODS
                and not _is_public(path)
                and not any(path.startswith(p) for p in CSRF_EXEMPT_PATHS)):
            cookie_token = request.cookies.get("csrf_token", "")
            header_token = request.headers.get("X-CSRF-Token", "")
            if not cookie_token or not header_token or cookie_token != header_token:
                return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)

        response: Response = await call_next(request)
        return response
