from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = ["ar", "en"]
DEFAULT_LANGUAGE = "ar"

_I18N_DIR = Path(__file__).parent


@lru_cache(maxsize=2)
def load_translations(lang: str) -> dict[str, Any]:
    path = _I18N_DIR / f"{lang}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """
    Translate a dot-notation key.

    Examples:
        t("ticket.status.open", lang="ar")  → "قيد المعالجة"
        t("ticket.status.open", lang="en")  → "In Progress"
        t("form.success", lang="ar", ticket_number="TKT-001")
    """
    resolved_lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    translations = load_translations(resolved_lang)

    value: Any = translations
    for k in key.split("."):
        if isinstance(value, dict):
            value = value.get(k, key)
        else:
            return key

    if isinstance(value, str):
        return value.format(**kwargs) if kwargs else value
    return key
