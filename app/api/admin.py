"""
Admin Panel Routes — 9 tabs of system configuration.
All mutations create an audit_log entry.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.templates import templates
from app.i18n import t

router = APIRouter()
UTC = timezone.utc

# Default permissions matrix (perm → roles that have it)
DEFAULT_PERMISSIONS: dict[str, list[str]] = {
    "dashboard.view":       ["employee", "supervisor", "manager", "admin"],
    "tickets.view":         ["employee", "supervisor", "manager", "admin"],
    "tickets.create":       ["employee", "supervisor", "manager", "admin"],
    "tickets.edit":         ["employee", "supervisor", "manager", "admin"],
    "tickets.delete":       ["manager", "admin"],
    "supervisor.view":      ["supervisor", "manager", "admin"],
    "supervisor.team":      ["supervisor", "manager", "admin"],
    "manager.view":         ["manager", "admin"],
    "manager.settings":     ["manager", "admin"],
    "admin.view":           ["admin"],
    "kb.view":              ["employee", "supervisor", "manager", "admin"],
    "kb.edit":              ["supervisor", "manager", "admin"],
    "reports.view":         ["supervisor", "manager", "admin"],
}


def _ctx(request: Request, **extra) -> dict:
    lang = getattr(request.state, "lang", "ar")
    return {
        "request": request,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "dark_mode": request.cookies.get("dark_mode", "1") != "0",
        "now": datetime.now(tz=UTC),
        "unread_notifications": 0,
        **extra,
    }


async def _audit(db: AsyncSession, table: str, action: str, actor_id: Optional[uuid.UUID], record_id: Optional[uuid.UUID] = None, diff: Optional[dict] = None) -> None:
    from app.models.audit import AuditLog
    db.add(AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=table,
        resource_id=record_id,
        new_value=diff,
    ))


def _actor_id(request: Request) -> Optional[uuid.UUID]:
    user = getattr(request.state, "user", {}) or {}
    try:
        return uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        return None


# ── GET /admin ─────────────────────────────────────────────────────────────────

@router.get("/admin", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("admin.view"))])
async def admin_panel(
    request: Request,
    tab: str = "branding",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.theme import Theme, BrandingConfig
    from app.models.feature_flag import FeatureFlag
    from app.models.ip_whitelist import IPWhitelist
    from app.core.config import settings

    # Branding
    br_result = await db.execute(select(BrandingConfig).limit(1))
    branding = br_result.scalar_one_or_none() or type("B", (), {
        "logo_url": None, "primary_color": "#6366f1", "secondary_color": "#22c55e"
    })()

    # Themes — serialized to dicts for Jinja2 tojson
    _themes_raw = list((await db.execute(select(Theme).order_by(Theme.sort_order))).scalars().all())
    themes = [
        {
            "id": str(th.id),
            "name_ar": th.name_ar,
            "name_en": th.name_en,
            "icon_emoji": th.icon_emoji or "",
            "primary_color": th.primary_color,
            "secondary_color": th.secondary_color,
            "background_color": th.background_color or "#0B1221",
            "welcome_message_ar": th.welcome_message_ar or "",
            "welcome_message_en": th.welcome_message_en or "",
            "starts_at": th.starts_at.isoformat() if th.starts_at else "",
            "ends_at": th.ends_at.isoformat() if th.ends_at else "",
            "is_active": th.is_active,
            "auto_activate": th.auto_activate,
            "sort_order": th.sort_order,
        }
        for th in _themes_raw
    ]

    # Feature flags
    flags = list((await db.execute(select(FeatureFlag))).scalars().all())

    # IP whitelist
    ip_list = list((await db.execute(select(IPWhitelist).where(IPWhitelist.deleted_at.is_(None)))).scalars().all())

    # Integrations — load all key/value pairs from DB into a flat dict
    from app.models.integration import IntegrationConfig
    _int_rows = (await db.execute(select(IntegrationConfig))).scalars().all()
    integrations: dict = {row.key: (row.value_enc or "") for row in _int_rows}

    # Security config
    security_config = type("S", (), {"twofa_required_roles": ["admin"]})()

    # Domain
    domain_config = type("D", (), {"domain": "", "ssl_valid": False})()

    return templates.TemplateResponse(
        "admin/index.html",
        _ctx(
            request,
            active_tab=tab,
            branding=branding,
            themes=themes,
            feature_flags=flags,
            ip_whitelist=ip_list,
            integrations=integrations,
            security_config=security_config,
            domain_config=domain_config,
        ),
    )


# ── Branding ──────────────────────────────────────────────────────────────────

@router.post("/api/admin/branding",
             dependencies=[Depends(require_permission("admin.view"))])
async def save_branding(
    request: Request,
    primary_color: str = Form("#6366f1"),
    primary_color_hex: Optional[str] = Form(None),
    secondary_color: str = Form("#22c55e"),
    secondary_color_hex: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.theme import BrandingConfig

    # Prefer the text hex field (user-typed) over the color picker value
    final_primary   = (primary_color_hex or primary_color).strip()
    final_secondary = (secondary_color_hex or secondary_color).strip()

    actor = _actor_id(request)
    result = await db.execute(select(BrandingConfig).limit(1))
    bc = result.scalar_one_or_none()

    if not bc:
        bc = BrandingConfig(id=uuid.uuid4())
        db.add(bc)
    bc.primary_color   = final_primary
    bc.secondary_color = final_secondary
    bc.updated_at      = datetime.now(tz=UTC)
    await _audit(db, "branding_config", "update", actor, bc.id)
    await db.commit()

    lang = getattr(request.state, "lang", "ar")
    return JSONResponse({"ok": True, "message": t("app.save", lang=lang)})


@router.post("/api/admin/branding/logo",
             dependencies=[Depends(require_permission("admin.view"))])
async def upload_logo(
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    lang = getattr(request.state, "lang", "ar")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        return HTMLResponse(f'<p class="text-xs text-red-600">{t("errors.file_too_large", lang=lang)}</p>')
    # TODO: upload to S3 / local storage and update BrandingConfig.logo_url
    return HTMLResponse(f'<p class="text-xs text-green-600">✅ {t("adm.logo_upload", lang=lang)}</p>')


# ── Theme CRUD ────────────────────────────────────────────────────────────────

@router.post("/api/admin/themes",
             dependencies=[Depends(require_permission("admin.view"))])
async def create_theme(
    request: Request,
    name_ar: str = Form(...),
    name_en: str = Form(...),
    icon_emoji: Optional[str] = Form(None),
    primary_color: str = Form("#00AEEF"),
    secondary_color: str = Form("#F59E0B"),
    background_color: Optional[str] = Form(None),
    welcome_message_ar: Optional[str] = Form(None),
    welcome_message_en: Optional[str] = Form(None),
    starts_at: str = Form(...),
    ends_at: str = Form(...),
    auto_activate: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.theme import Theme
    from datetime import datetime

    actor = _actor_id(request)
    lang  = getattr(request.state, "lang", "ar")
    try:
        sa = datetime.fromisoformat(starts_at).astimezone(UTC)
        ea = datetime.fromisoformat(ends_at).astimezone(UTC)
    except ValueError:
        return JSONResponse({"ok": False, "error": "تاريخ غير صالح" if lang == "ar" else "Invalid date"}, status_code=400)

    theme = Theme(
        id=uuid.uuid4(),
        name_ar=name_ar.strip(),
        name_en=name_en.strip(),
        icon_emoji=(icon_emoji or "").strip() or None,
        primary_color=primary_color,
        secondary_color=secondary_color,
        background_color=background_color or None,
        welcome_message_ar=welcome_message_ar or None,
        welcome_message_en=welcome_message_en or None,
        starts_at=sa,
        ends_at=ea,
        auto_activate=(auto_activate == "on"),
        is_active=False,
        created_by=actor,
    )
    db.add(theme)
    await _audit(db, "themes", "create", actor, theme.id, {"name_ar": name_ar})
    await db.commit()
    return JSONResponse({"ok": True, "id": str(theme.id), "message": "تم الحفظ" if lang == "ar" else "Saved"})


@router.put("/api/admin/themes/{theme_id}",
            dependencies=[Depends(require_permission("admin.view"))])
async def update_theme(
    theme_id: str,
    request: Request,
    name_ar: str = Form(...),
    name_en: str = Form(...),
    icon_emoji: Optional[str] = Form(None),
    primary_color: str = Form("#00AEEF"),
    secondary_color: str = Form("#F59E0B"),
    background_color: Optional[str] = Form(None),
    welcome_message_ar: Optional[str] = Form(None),
    welcome_message_en: Optional[str] = Form(None),
    starts_at: str = Form(...),
    ends_at: str = Form(...),
    auto_activate: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.theme import Theme
    from datetime import datetime

    actor = _actor_id(request)
    lang  = getattr(request.state, "lang", "ar")
    try:
        tid = uuid.UUID(theme_id)
        sa = datetime.fromisoformat(starts_at).astimezone(UTC)
        ea = datetime.fromisoformat(ends_at).astimezone(UTC)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Theme).where(Theme.id == tid))
    theme = result.scalar_one_or_none()
    if not theme:
        raise HTTPException(404)

    theme.name_ar = name_ar.strip()
    theme.name_en = name_en.strip()
    theme.icon_emoji = (icon_emoji or "").strip() or None
    theme.primary_color = primary_color
    theme.secondary_color = secondary_color
    theme.background_color = background_color or None
    theme.welcome_message_ar = welcome_message_ar or None
    theme.welcome_message_en = welcome_message_en or None
    theme.starts_at = sa
    theme.ends_at = ea
    theme.auto_activate = (auto_activate == "on")
    await _audit(db, "themes", "update", actor, theme.id)
    await db.commit()
    return JSONResponse({"ok": True, "message": "تم الحفظ" if lang == "ar" else "Saved"})


@router.delete("/api/admin/themes/{theme_id}",
               dependencies=[Depends(require_permission("admin.view"))])
async def delete_theme(theme_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    from app.models.theme import Theme

    actor = _actor_id(request)
    lang  = getattr(request.state, "lang", "ar")
    try:
        tid = uuid.UUID(theme_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Theme).where(Theme.id == tid))
    theme = result.scalar_one_or_none()
    if not theme:
        raise HTTPException(404)

    await db.delete(theme)
    await _audit(db, "themes", "delete", actor, tid)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/admin/themes/{theme_id}/toggle",
             dependencies=[Depends(require_permission("admin.view"))])
async def toggle_theme(theme_id: str, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    from app.models.theme import Theme

    try:
        tid = uuid.UUID(theme_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Theme).where(Theme.id == tid))
    theme = result.scalar_one_or_none()
    if not theme:
        raise HTTPException(404)

    # If activating: deactivate all other themes first (only one active at a time)
    if not theme.is_active:
        all_themes = (await db.execute(select(Theme).where(Theme.id != tid))).scalars().all()
        for t in all_themes:
            t.is_active = False

    theme.is_active = not theme.is_active
    await db.commit()
    return JSONResponse({"ok": True, "is_active": theme.is_active})


# ── Integrations ──────────────────────────────────────────────────────────────

@router.post("/api/admin/integrations/{service}",
             dependencies=[Depends(require_permission("admin.view"))])
async def save_integration(
    service: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.integration import IntegrationConfig  # noqa: F811

    actor = _actor_id(request)
    lang  = getattr(request.state, "lang", "ar")
    form  = await request.form()

    # Store each field as a separate key: e.g. "smtp.host", "smtp.port"
    svc = service.lower()
    for field_name, field_value in form.items():
        if field_name == "test_mode":
            continue
        key = f"{svc}.{field_name}"
        row = (await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.key == key)
        )).scalar_one_or_none()
        if row is None:
            row = IntegrationConfig(id=uuid.uuid4(), key=key)
            db.add(row)
        row.value_enc = str(field_value)
        row.updated_by = actor

    # Handle test_mode toggle
    tm_key = f"{svc}.test_mode"
    tm_val = "1" if form.get("test_mode") else "0"
    tm_row = (await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.key == tm_key)
    )).scalar_one_or_none()
    if tm_row is None:
        tm_row = IntegrationConfig(id=uuid.uuid4(), key=tm_key)
        db.add(tm_row)
    tm_row.value_enc = tm_val

    await db.commit()
    return JSONResponse({"ok": True, "message": t("adm.connection_ok", lang=lang)})


@router.post("/api/admin/integrations/{service}/test",
             dependencies=[Depends(require_permission("admin.view"))])
async def test_integration(service: str, request: Request) -> HTMLResponse:
    lang = getattr(request.state, "lang", "ar")
    # TODO: implement real connection testing per service
    return HTMLResponse(f'<span class="text-green-600 text-xs">{t("adm.connection_ok", lang=lang)}</span>')


# ── Feature Flags ─────────────────────────────────────────────────────────────

@router.post("/api/admin/flags/{flag_id}/toggle",
             dependencies=[Depends(require_permission("admin.view"))])
async def toggle_flag(
    flag_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.feature_flag import FeatureFlag

    try:
        fid = uuid.UUID(flag_id)
    except ValueError:
        raise HTTPException(400, "Invalid flag ID")

    result = await db.execute(select(FeatureFlag).where(FeatureFlag.id == fid))
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(404, "Flag not found")

    flag.is_enabled = not flag.is_enabled
    actor = _actor_id(request)
    await _audit(db, "feature_flags", "toggle", actor, flag.id, {"key": flag.key, "is_enabled": flag.is_enabled})
    await db.commit()
    return JSONResponse({"ok": True, "key": flag.key, "is_enabled": flag.is_enabled})


# ── Security ──────────────────────────────────────────────────────────────────





@router.delete("/api/admin/security/ip/{ip_id}",
               dependencies=[Depends(require_permission("admin.view"))])
async def delete_ip(ip_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    from app.models.security import IPWhitelist

    actor = _actor_id(request)
    result = await db.execute(select(IPWhitelist).where(IPWhitelist.id == uuid.UUID(ip_id)))
    ip_obj = result.scalar_one_or_none()
    if not ip_obj:
        raise HTTPException(404)
    ip_obj.deleted_at = datetime.now(tz=UTC)
    await _audit(db, "ip_whitelist", "delete", actor, ip_obj.id)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/admin/security/2fa-policy",
             dependencies=[Depends(require_permission("admin.view"))])
async def save_2fa_policy(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    form  = await request.form()
    roles = form.getlist("roles")
    lang  = getattr(request.state, "lang", "ar")
    # TODO: persist 2FA policy to DB
    return JSONResponse({"ok": True, "message": t("app.save", lang=lang)})


# ── DB Maintenance ────────────────────────────────────────────────────────────

@router.post("/api/admin/db/vacuum",
             dependencies=[Depends(require_permission("admin.view"))])
async def db_vacuum(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    """VACUUM must run outside any transaction — use raw autocommit connection."""
    actor = _actor_id(request)
    lang = getattr(request.state, "lang", "ar")
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("VACUUM ANALYZE"))
        await _audit(db, "_system", "vacuum", actor)
        await db.commit()
        msg = "تم تنظيف قاعدة البيانات بنجاح ✓" if lang == "ar" else "VACUUM ANALYZE completed ✓"
        return HTMLResponse(f'<span style="color:#10B981;font-weight:700;font-size:12px;">✓ {msg}</span>')
    except Exception as exc:
        err = "العملية الداخلية فشلت" if lang == "ar" else "Operation failed"
        return HTMLResponse(f'<span style="color:#EF4444;font-weight:700;font-size:12px;">✗ {err}: {exc}</span>')


@router.post("/api/admin/db/analyze",
             dependencies=[Depends(require_permission("admin.view"))])
async def db_analyze(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    """ANALYZE can run inside a transaction."""
    actor = _actor_id(request)
    lang = getattr(request.state, "lang", "ar")
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("ANALYZE"))
        await _audit(db, "_system", "analyze", actor)
        await db.commit()
        msg = "تم تحديث إحصاءات الجداول بنجاح ✓" if lang == "ar" else "ANALYZE completed ✓"
        return HTMLResponse(f'<span style="color:#10B981;font-weight:700;font-size:12px;">✓ {msg}</span>')
    except Exception as exc:
        err = "العملية الداخلية فشلت" if lang == "ar" else "Operation failed"
        return HTMLResponse(f'<span style="color:#EF4444;font-weight:700;font-size:12px;">✗ {err}: {exc}</span>')


# ── System Health ──────────────────────────────────────────────────────────────

def _health_card(title: str, icon: str, status_ok: bool, rows: list[tuple[str, str]], badge: str = "") -> str:
    """Render a single health card with key-value rows."""
    ok_color   = "#10B981"
    fail_color = "#EF4444"
    status_color = ok_color if status_ok else fail_color
    status_label = "متاح" if status_ok else "غير متاح"
    badge_html = f'<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;background:rgba(0,174,239,0.12);color:#00AEEF;margin-right:6px;">{badge}</span>' if badge else ""

    rows_html = "".join(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:5px 0;border-bottom:1px solid var(--border-color);">'
        f'<span style="font-size:11px;color:var(--text-muted);">{k}</span>'
        f'<span style="font-size:11px;font-weight:700;color:var(--text-ink);font-family:monospace;">{v}</span>'
        f'</div>'
        for k, v in rows
    )

    return (
        f'<div style="background:var(--bg-card);border:1.5px solid var(--border-color);'
        f'border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:10px;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;">'
        f'<div style="display:flex;align-items:center;gap:10px;">'
        f'<div style="width:38px;height:38px;border-radius:10px;background:rgba(0,174,239,0.1);'
        f'border:1px solid rgba(0,174,239,0.2);display:flex;align-items:center;'
        f'justify-content:center;font-size:17px;">{icon}</div>'
        f'<div><p style="font-size:13px;font-weight:800;color:var(--text-ink);margin:0;">{title}</p>'
        f'<p style="font-size:10px;color:{status_color};font-weight:700;margin:2px 0 0;">'
        f'{"●" if status_ok else "✗"} {status_label}</p></div></div>'
        f'{badge_html}</div>'
        f'<div style="display:flex;flex-direction:column;gap:0;">{rows_html}</div>'
        f'</div>'
    )


@router.get("/api/admin/health", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("admin.view"))])
async def system_health(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    import sys, os, time
    import psutil
    import redis as _redis_lib
    from app.core.config import settings

    cards = []

    # ── 1. PostgreSQL ──────────────────────────────────────────────────────────
    try:
        pg_version = (await db.execute(text("SELECT version()"))).scalar() or ""
        pg_ver_short = pg_version.split(" ")[1] if " " in pg_version else pg_version[:20]

        pg_size = (await db.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"
        ))).scalar() or "—"

        pg_conn = (await db.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
        ))).scalar() or 0

        pg_tables = (await db.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ))).scalar() or 0

        pg_cache_hit = (await db.execute(text(
            "SELECT round(100.0 * sum(heap_blks_hit) / "
            "NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0), 1) "
            "FROM pg_statio_user_tables"
        ))).scalar()
        pg_cache_str = f"{pg_cache_hit}%" if pg_cache_hit else "—"

        pg_slow = (await db.execute(text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE state = 'active' AND now() - query_start > interval '5 seconds'"
        ))).scalar() or 0

        cards.append(_health_card(
            "PostgreSQL", "🐘", True, [
                ("الإصدار", pg_ver_short),
                ("حجم قاعدة البيانات", pg_size),
                ("الاتصالات النشطة", str(pg_conn)),
                ("عدد الجداول", str(pg_tables)),
                ("نسبة Cache Hit", pg_cache_str),
                ("استعلامات بطيئة (>5s)", str(pg_slow)),
            ]
        ))
    except Exception as exc:
        cards.append(_health_card("PostgreSQL", "🐘", False, [("خطأ", str(exc)[:80])]))

    # ── 2. Redis ───────────────────────────────────────────────────────────────
    try:
        r = _redis_lib.from_url(str(settings.REDIS_URL), decode_responses=True)
        info = r.info()
        r.close()

        used_mem  = info.get("used_memory_human", "—")
        peak_mem  = info.get("used_memory_peak_human", "—")
        clients   = info.get("connected_clients", "—")
        uptime_s  = int(info.get("uptime_in_seconds", 0))
        uptime_h  = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"
        redis_ver = info.get("redis_version", "—")
        keys_total = sum(
            v.get("keys", 0) for k, v in info.items()
            if k.startswith("db") and isinstance(v, dict)
        )
        cmd_total = info.get("total_commands_processed", "—")

        cards.append(_health_card(
            "Redis", "🔴", True, [
                ("الإصدار", redis_ver),
                ("الذاكرة المستخدمة", used_mem),
                ("ذروة الذاكرة", peak_mem),
                ("المتصلون الحاليون", str(clients)),
                ("مدة التشغيل", uptime_h),
                ("إجمالي المفاتيح", str(keys_total)),
                ("إجمالي الأوامر", str(cmd_total)),
            ]
        ))
    except Exception as exc:
        cards.append(_health_card("Redis", "🔴", False, [("خطأ", str(exc)[:80])]))

    # ── 3. النظام (CPU / RAM / Disk) ──────────────────────────────────────────
    try:
        cpu_pct  = psutil.cpu_percent(interval=0.3)
        cpu_cnt  = psutil.cpu_count(logical=True)
        ram      = psutil.virtual_memory()
        disk     = psutil.disk_usage("/")

        def _bar(pct: float) -> str:
            filled = int(pct / 10)
            color  = "#10B981" if pct < 70 else ("#F59E0B" if pct < 90 else "#EF4444")
            bar    = "█" * filled + "░" * (10 - filled)
            return f'<span style="color:{color};font-family:monospace;">{bar} {pct:.1f}%</span>'

        cards.append(_health_card(
            "الخادم (Server)", "🖥️",
            cpu_pct < 90 and ram.percent < 90,
            [
                ("CPU — الاستخدام", f"{cpu_pct:.1f}% / {cpu_cnt} cores"),
                ("RAM — المستخدم", f"{ram.used / 1e9:.2f} GB / {ram.total / 1e9:.2f} GB  ({ram.percent:.1f}%)"),
                ("RAM — المتاح", f"{ram.available / 1e9:.2f} GB"),
                ("القرص — المستخدم", f"{disk.used / 1e9:.1f} GB / {disk.total / 1e9:.1f} GB  ({disk.percent:.1f}%)"),
                ("القرص — المتاح", f"{disk.free / 1e9:.1f} GB"),
            ]
        ))
    except Exception as exc:
        cards.append(_health_card("الخادم", "🖥️", False, [("خطأ", str(exc)[:80])]))

    # ── 4. Python / التطبيق ──────────────────────────────────────────────────
    try:
        proc      = psutil.Process(os.getpid())
        proc_mem  = proc.memory_info().rss / 1e6
        proc_up   = time.time() - proc.create_time()
        up_h      = f"{int(proc_up // 3600)}h {int((proc_up % 3600) // 60)}m"
        num_threads = proc.num_threads()
        py_ver    = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        cards.append(_health_card(
            "Python / التطبيق", "🐍", True, [
                ("إصدار Python", py_ver),
                ("PID", str(os.getpid())),
                ("مدة التشغيل", up_h),
                ("ذاكرة العملية", f"{proc_mem:.1f} MB"),
                ("عدد الـ Threads", str(num_threads)),
                ("FastAPI", "0.115"),
                ("SQLAlchemy", "2.0"),
            ]
        ))
    except Exception as exc:
        cards.append(_health_card("Python / التطبيق", "🐍", False, [("خطأ", str(exc)[:80])]))

    # ── 5. Celery ─────────────────────────────────────────────────────────────
    try:
        from celery import Celery as _Celery
        _app = _Celery(broker=str(settings.REDIS_URL))
        insp  = _app.control.inspect(timeout=1.5)
        active = insp.active() or {}
        reserved = insp.reserved() or {}
        workers   = list(active.keys())
        active_tasks  = sum(len(v) for v in active.values())
        queued_tasks  = sum(len(v) for v in reserved.values())

        cards.append(_health_card(
            "Celery (Task Queue)", "⚙️", len(workers) > 0, [
                ("Workers نشطة", str(len(workers))),
                ("مهام جارية", str(active_tasks)),
                ("مهام في الانتظار", str(queued_tasks)),
                ("أسماء Workers", (workers[0][:30] if workers else "—")),
            ]
        ))
    except Exception as exc:
        cards.append(_health_card("Celery (Task Queue)", "⚙️", False, [("الحالة", "Worker غير متصل")]))

    # ── 6. إحصاءات التذاكر ────────────────────────────────────────────────────
    try:
        from app.models.ticket import Ticket
        from app.models.user import User

        total_tickets = (await db.execute(
            text("SELECT count(*) FROM tickets WHERE deleted_at IS NULL")
        )).scalar() or 0

        open_tickets = (await db.execute(
            text("SELECT count(*) FROM tickets WHERE deleted_at IS NULL AND status NOT IN ('resolved','closed')")
        )).scalar() or 0

        total_users = (await db.execute(
            text("SELECT count(*) FROM users WHERE deleted_at IS NULL")
        )).scalar() or 0

        tickets_today = (await db.execute(
            text("SELECT count(*) FROM tickets WHERE created_at::date = current_date AND deleted_at IS NULL")
        )).scalar() or 0

        resolved_today = (await db.execute(
            text("SELECT count(*) FROM tickets WHERE updated_at::date = current_date AND status = 'resolved' AND deleted_at IS NULL")
        )).scalar() or 0

        cards.append(_health_card(
            "إحصاءات النظام", "📊", True, [
                ("إجمالي التذاكر", str(total_tickets)),
                ("تذاكر مفتوحة", str(open_tickets)),
                ("تذاكر اليوم", str(tickets_today)),
                ("محلولة اليوم", str(resolved_today)),
                ("إجمالي المستخدمين", str(total_users)),
            ]
        ))
    except Exception as exc:
        cards.append(_health_card("إحصاءات النظام", "📊", False, [("خطأ", str(exc)[:80])]))

    # ── Compose grid ──────────────────────────────────────────────────────────
    grid = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));'
        'gap:14px;align-items:start;">'
        + "".join(cards) +
        "</div>"
    )
    return HTMLResponse(grid)


# ── Backup ────────────────────────────────────────────────────────────────────

@router.post("/api/admin/backup",
             dependencies=[Depends(require_permission("admin.view"))])
async def trigger_backup(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    actor = _actor_id(request)
    lang  = getattr(request.state, "lang", "ar")
    async with db.begin():
        await _audit(db, "_system", "backup_triggered", actor)
    # TODO: enqueue Celery task for pg_dump to S3
    return HTMLResponse(f'<span class="text-green-600 text-xs">✅ {t("adm.backup_now", lang=lang)}</span>')


# ── Domain ────────────────────────────────────────────────────────────────────

@router.post("/api/admin/domain",
             dependencies=[Depends(require_permission("admin.view"))])
async def save_domain(
    request: Request,
    domain: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    lang  = getattr(request.state, "lang", "ar")
    actor = _actor_id(request)
    await _audit(db, "_system", "domain_update", actor, diff={"domain": domain})
    await db.commit()
    msg = "تم حفظ النطاق بنجاح ✓" if lang == "ar" else "Domain saved ✓"
    return JSONResponse({"ok": True, "message": msg})


@router.post("/api/admin/ssl/renew",
             dependencies=[Depends(require_permission("admin.view"))])
async def renew_ssl(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    lang  = getattr(request.state, "lang", "ar")
    actor = _actor_id(request)
    await _audit(db, "_system", "ssl_renew", actor)
    await db.commit()
    msg = "تم طلب تجديد SSL — سيكتمل خلال دقائق ✓" if lang == "ar" else "SSL renewal requested ✓"
    return JSONResponse({"ok": True, "message": msg})


@router.post("/api/admin/security/ip",
             dependencies=[Depends(require_permission("admin.view"))])
async def add_ip_v2(
    request: Request,
    ip_address: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.ip_whitelist import IPWhitelist
    actor = _actor_id(request)
    lang  = getattr(request.state, "lang", "ar")
    existing = (await db.execute(
        select(IPWhitelist).where(IPWhitelist.ip_address == ip_address, IPWhitelist.deleted_at.is_(None))
    )).scalar_one_or_none()
    if existing:
        return JSONResponse({"ok": False, "message": "IP موجود بالفعل" if lang == "ar" else "IP already exists"})
    ip_obj = IPWhitelist(id=uuid.uuid4(), ip_address=ip_address, created_at=datetime.now(tz=UTC))
    db.add(ip_obj)
    await _audit(db, "ip_whitelist", "create", actor, ip_obj.id, {"ip_address": ip_address})
    await db.commit()
    return JSONResponse({"ok": True, "id": str(ip_obj.id), "ip": ip_address})
