from __future__ import annotations

import datetime

from starlette.templating import Jinja2Templates

from app.i18n import t as translate_func
from app.utils.formatters import format_date, format_number


def _bilingual(obj: object, field: str, lang: str) -> str:
    """
    Pick the correct language column from a SQLAlchemy model instance.
    bl(category, "name", "ar") → category.name_ar, falls back to _ar.
    """
    value = getattr(obj, f"{field}_{lang}", None)
    if not value:
        value = getattr(obj, f"{field}_ar", "")
    return value or ""


def _create_templates() -> Jinja2Templates:
    tpl = Jinja2Templates(directory="app/templates")

    env = tpl.env
    env.autoescape = True
    env.auto_reload = True

    # Translation + bilingual field helpers (available in every template)
    env.globals["t"] = translate_func
    env.globals["bl"] = _bilingual
    env.globals["SUPPORTED_LANGUAGES"] = ["ar", "en"]

    # Date / number formatters
    env.globals["format_date"] = format_date
    env.globals["format_number"] = format_number

    # Expose current UTC datetime so templates can use {{ now.year }}
    env.globals["now"] = datetime.datetime.utcnow

    return tpl


templates = _create_templates()
