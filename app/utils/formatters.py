from __future__ import annotations

from datetime import datetime

from babel import Locale
from babel import dates as babel_dates
from babel import numbers as babel_numbers


def format_date(dt: datetime | None, lang: str = "ar") -> str:
    """Format a datetime object using locale-aware Babel formatting."""
    if dt is None:
        return ""
    locale = Locale.parse("ar_SA" if lang == "ar" else "en_US")
    return babel_dates.format_datetime(dt, locale=locale, format="short")


def format_number(n: int | float, lang: str = "ar") -> str:
    """Format a number using locale-aware Babel formatting (Western numerals for both)."""
    locale = Locale.parse("ar_SA" if lang == "ar" else "en_US")
    return babel_numbers.format_number(n, locale=locale)


def format_duration_minutes(minutes: int, lang: str = "ar") -> str:
    """Human-readable duration: e.g. '1h 30m' or '١ ساعة ٣٠ دقيقة'."""
    hours = minutes // 60
    mins = minutes % 60
    if lang == "ar":
        if hours and mins:
            return f"{hours} ساعة {mins} دقيقة"
        if hours:
            return f"{hours} ساعة"
        return f"{mins} دقيقة"
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"
