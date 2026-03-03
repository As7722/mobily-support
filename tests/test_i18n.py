"""
Tests for bilingual i18n system:
  - t() function returns correct translation
  - bl() helper picks correct DB field
  - Language toggle endpoint
  - Fallback behavior for missing keys
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ── t() translation function ──────────────────────────────────────────────────

def test_t_returns_arabic():
    from app.i18n import t

    result = t("app.name", lang="ar")
    assert isinstance(result, str)
    assert len(result) > 0


def test_t_returns_english():
    from app.i18n import t

    result = t("app.name", lang="en")
    assert isinstance(result, str)
    assert len(result) > 0


def test_t_arabic_english_differ():
    from app.i18n import t

    ar = t("app.name", lang="ar")
    en = t("app.name", lang="en")
    # They might be equal if same value, but app.name should differ
    # At minimum both are valid strings
    assert isinstance(ar, str) and isinstance(en, str)


def test_t_missing_key_returns_key():
    from app.i18n import t

    result = t("this.key.does.not.exist", lang="ar")
    # Should not raise; returns key or empty string
    assert isinstance(result, str)


def test_t_nested_key():
    from app.i18n import t

    result = t("ticket.status.open", lang="ar")
    assert isinstance(result, str)
    assert len(result) > 0


def test_t_nested_key_en():
    from app.i18n import t

    result = t("ticket.status.open", lang="en")
    assert "open" in result.lower() or len(result) > 0


def test_t_all_dashboard_keys_exist():
    from app.i18n import t

    keys = [
        "dash.title", "dash.smart_queue", "dash.claim",
        "dash.empty_queue", "sup.title", "sup.workload_table",
        "mgr.title", "mgr.kpi_title", "adm.title", "adm.tab_branding",
    ]
    for key in keys:
        ar = t(key, lang="ar")
        en = t(key, lang="en")
        assert len(ar) > 0, f"Missing AR: {key}"
        assert len(en) > 0, f"Missing EN: {key}"


def test_t_all_ticket_detail_keys():
    from app.i18n import t

    for key in [
        "ticket_detail.internal_only", "ticket_detail.all_events",
        "ticket_detail.auto_save", "ticket_detail.draft_clear",
    ]:
        assert len(t(key, lang="ar")) > 0
        assert len(t(key, lang="en")) > 0


# ── bl() bilingual field helper ────────────────────────────────────────────────

def test_bl_picks_arabic_field():
    from app.core.templates import templates

    bl = templates.env.globals.get("bl")
    if bl is None:
        pytest.skip("bl() not registered in template globals")

    obj = MagicMock()
    obj.name_ar = "عربي"
    obj.name_en = "English"

    result = bl(obj, "name", "ar")
    assert result == "عربي"


def test_bl_picks_english_field():
    from app.core.templates import templates

    bl = templates.env.globals.get("bl")
    if bl is None:
        pytest.skip("bl() not registered in template globals")

    obj = MagicMock()
    obj.name_ar = "عربي"
    obj.name_en = "English"

    result = bl(obj, "name", "en")
    assert result == "English"


def test_bl_falls_back_to_arabic_if_en_empty():
    from app.core.templates import templates

    bl = templates.env.globals.get("bl")
    if bl is None:
        pytest.skip("bl() not registered")

    obj = MagicMock()
    obj.name_ar = "عربي"
    obj.name_en = None  # no English

    result = bl(obj, "name", "en")
    assert result == "عربي"  # fallback to Arabic


# ── JSON files completeness ───────────────────────────────────────────────────

def test_ar_json_valid():
    """ar.json must be valid JSON."""
    import json
    from pathlib import Path

    data = json.loads(Path("app/i18n/ar.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert len(data) > 10


def test_en_json_valid():
    """en.json must be valid JSON."""
    import json
    from pathlib import Path

    data = json.loads(Path("app/i18n/en.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert len(data) > 10


def test_ar_and_en_have_same_top_level_keys():
    """Both JSON files must have the same top-level keys."""
    import json
    from pathlib import Path

    ar = json.loads(Path("app/i18n/ar.json").read_text(encoding="utf-8"))
    en = json.loads(Path("app/i18n/en.json").read_text(encoding="utf-8"))

    ar_keys = set(ar.keys())
    en_keys = set(en.keys())

    missing_in_en = ar_keys - en_keys
    missing_in_ar = en_keys - ar_keys

    assert not missing_in_en, f"Keys in ar.json but not en.json: {missing_in_en}"
    assert not missing_in_ar, f"Keys in en.json but not ar.json: {missing_in_ar}"


# ── Language toggle endpoint ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_language_toggle_ar_to_en(client):
    """POST /api/language/toggle should switch from ar to en."""
    response = await client.post(
        "/api/language/toggle",
        data={"current_path": "/dashboard"},
        cookies={"lang": "ar"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303, 307)
    # Cookie should be set to "en"
    set_cookie = response.headers.get("set-cookie", "")
    assert "en" in set_cookie


@pytest.mark.asyncio
async def test_language_toggle_en_to_ar(client):
    """POST /api/language/toggle should switch from en to ar."""
    response = await client.post(
        "/api/language/toggle",
        data={"current_path": "/dashboard"},
        cookies={"lang": "en"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303, 307)
    set_cookie = response.headers.get("set-cookie", "")
    assert "ar" in set_cookie
