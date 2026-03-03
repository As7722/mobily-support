"""
ThemeMiddleware — detects the current active seasonal theme and attaches it
to request.state so every template can inject its CSS variables.

Activation is MANUAL ONLY:
  Only themes with is_active=True are applied — no auto-scheduling logic.

Timezone: Asia/Riyadh (UTC+3) — official Saudi Arabia standard time.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

RIYADH_TZ = ZoneInfo("Asia/Riyadh")

# CSS variable overrides generated from a theme row
_THEME_CSS_TPL = """
:root {{
  --theme-primary:   {primary};
  --theme-secondary: {secondary};
  --theme-bg:        {bg};
  --cyan:            {primary};
  --cyan-hover:      {primary}cc;
  --cyan-glow:       {primary}33;
  --cyan-border:     {primary}55;
}}
"""


class ThemeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.active_theme = None
        request.state.theme_css = ""

        # Skip static files / health
        path = request.url.path
        if path.startswith("/static") or path == "/health":
            return await call_next(request)

        try:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models.theme import Theme

            async with AsyncSessionLocal() as db:
                # Manual activation ONLY — is_active=True set by admin
                theme = (await db.execute(
                    select(Theme)
                    .where(Theme.is_active.is_(True))
                    .order_by(Theme.sort_order)
                    .limit(1)
                )).scalar_one_or_none()

                if theme:
                    request.state.active_theme = theme
                    bg = theme.background_color or "#0B1221"
                    request.state.theme_css = _THEME_CSS_TPL.format(
                        primary=theme.primary_color,
                        secondary=theme.secondary_color,
                        bg=bg,
                    )
        except Exception:
            pass  # Never break the request due to theme lookup failure

        return await call_next(request)
