from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

router = APIRouter()

SUPPORTED = {"ar", "en"}
DEFAULT = "ar"


@router.post("/api/language/toggle")
async def toggle_language(request: Request) -> Response:
    """Toggle language and redirect back to referrer (or portal)."""
    current_lang = getattr(request.state, "lang", DEFAULT)
    new_lang = "en" if current_lang == "ar" else "ar"

    form = await request.form()
    redirect_to = form.get("current_path") or request.headers.get("referer") or "/portal"
    redirect_to = str(redirect_to).strip()
    # Prevent open redirect: must start with single "/" and not "//"
    if not redirect_to.startswith("/") or redirect_to.startswith("//"):
        redirect_to = "/portal"

    response = RedirectResponse(url=redirect_to, status_code=303)
    response.set_cookie(
        key="lang",
        value=new_lang,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        httponly=False,
    )
    return response
