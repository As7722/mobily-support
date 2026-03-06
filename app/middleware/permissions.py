"""
Middleware that sets request.state.effective_permissions for the current user.
Templates use this to show/hide nav items (e.g. لوحة المشرف, لوحة المدير) by actual permissions.

Important: This middleware must be added BEFORE AuthMiddleware in main.py so that Auth runs
first (Starlette runs last-added middleware first). Then request.state.user is set when we run.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths that skip permission loading (no user or static)
_SKIP_PATHS = ("/login", "/portal", "/static/", "/health", "/favicon.ico", "/api/auth/")


def _should_skip(path: str) -> bool:
    return any(path.startswith(p) for p in _SKIP_PATHS) or path == "/"


class PermissionsMiddleware(BaseHTTPMiddleware):
    """
    After auth, if request.state.user is set, compute effective permissions (DB + defaults)
    and set request.state.effective_permissions (list of permission keys) so templates
    can show/hide buttons by permission instead of by role.
    Never raises: on any error sets effective_permissions = [] so the app keeps working.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        # Always set so templates never see missing attribute
        try:
            request.state.effective_permissions = []
        except Exception:
            pass

        try:
            if _should_skip(request.url.path):
                return await call_next(request)

            user = getattr(request.state, "user", None)
            if not user or not isinstance(user, dict):
                return await call_next(request)

            role = (user.get("role") or "").strip().lower()
            if not role:
                return await call_next(request)

            from app.core.database import AsyncSessionLocal
            from app.core.permissions import get_effective_permissions_for_role, get_default_permissions_for_role

            async with AsyncSessionLocal() as db:
                granted = await get_effective_permissions_for_role(role, db)
                request.state.effective_permissions = list(granted)
        except Exception as e:
            logger.warning("PermissionsMiddleware: could not load permissions: %s", e, exc_info=True)
            try:
                # احتياطي: صلاحيات افتراضية حسب الدور حتى تظهر الأزرار
                request.state.effective_permissions = list(get_default_permissions_for_role(role))
            except Exception:
                request.state.effective_permissions = []

        return await call_next(request)
