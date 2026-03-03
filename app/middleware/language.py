from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SUPPORTED_LANGUAGES = ["ar", "en"]
DEFAULT_LANGUAGE = "ar"


class LanguageMiddleware(BaseHTTPMiddleware):
    """
    Detects and sets request.state.lang and request.state.dir.

    Priority order:
      1. Authenticated user's preferred_language (set by auth middleware on request.state.user)
      2. "lang" cookie
      3. Accept-Language header
      4. Default: "ar"
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        lang: str | None = None

        # 1. From authenticated user stored on request.state
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "preferred_language"):
            lang = user.preferred_language

        # 2. From cookie
        if not lang:
            lang = request.cookies.get("lang")

        # 3. From Accept-Language header
        if not lang:
            accept_lang = request.headers.get("Accept-Language", "")
            if "ar" in accept_lang:
                lang = "ar"
            elif "en" in accept_lang:
                lang = "en"

        # 4. Fallback
        request.state.lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        request.state.dir = "rtl" if request.state.lang == "ar" else "ltr"

        response: Response = await call_next(request)
        return response
