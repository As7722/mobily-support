"""
Employee Profile Routes — /profile
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.templates import templates
from app.i18n import t

router = APIRouter()
UTC = timezone.utc


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


# ── GET /profile ──────────────────────────────────────────────────────────────

@router.get("/profile", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("dashboard.view"))])
async def profile_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.user import User
    from app.models.ticket import Ticket
    from app.models.gamification import UserBadge, GamificationBadge, LeaderboardSnapshot

    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)

    user_id_str = user_payload.get("sub")
    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(401)

    # Load full user object
    user_result = await db.execute(select(User).where(User.id == user_id))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(404)

    # KPI stats (this month)
    from datetime import date
    month_start = datetime.now(tz=UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    resolved_q = await db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.assigned_to == user_id,
            Ticket.status.in_(["resolved", "closed"]),
            Ticket.created_at >= month_start,
            Ticket.deleted_at.is_(None),
        )
    )
    resolved_count = resolved_q.scalar() or 0

    # Average resolution time
    avg_res_q = await db.execute(
        select(func.avg(
            func.extract("epoch", Ticket.resolved_at - Ticket.created_at) / 3600
        )).where(
            Ticket.assigned_to == user_id,
            Ticket.resolved_at.is_not(None),
            Ticket.created_at >= month_start,
            Ticket.deleted_at.is_(None),
        )
    )
    avg_resolution_h = round(avg_res_q.scalar() or 0, 1)

    # CSAT average
    csat_q = await db.execute(
        select(func.avg(Ticket.csat_score)).where(
            Ticket.assigned_to == user_id,
            Ticket.csat_score.is_not(None),
            Ticket.created_at >= month_start,
        )
    )
    csat_avg = round(csat_q.scalar() or 0, 1)

    # SLA compliance
    total_q = await db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.assigned_to == user_id,
            Ticket.sla_deadline.is_not(None),
            Ticket.created_at >= month_start,
            Ticket.deleted_at.is_(None),
        )
    )
    total_with_sla = total_q.scalar() or 0

    breached_q = await db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.assigned_to == user_id,
            Ticket.sla_breached.is_(True),
            Ticket.created_at >= month_start,
            Ticket.deleted_at.is_(None),
        )
    )
    breached_count = breached_q.scalar() or 0
    sla_pct = round((1 - breached_count / total_with_sla) * 100, 1) if total_with_sla > 0 else 100.0

    kpis = type("KPIs", (), {
        "resolved_count": resolved_count,
        "avg_resolution_h": avg_resolution_h,
        "csat_avg": csat_avg,
        "sla_pct": sla_pct,
    })()

    # Badges (with GamificationBadge joined)
    try:
        badges_result = await db.execute(
            select(UserBadge)
            .where(UserBadge.user_id == user_id)
            .options(selectinload(UserBadge.badge))
            .order_by(UserBadge.awarded_at.desc())
            .limit(20)
        )
        badges = list(badges_result.scalars().all())
        # Attach awarded_count as a convenience attribute
        badge_counts: dict[str, int] = {}
        for ub in badges:
            key = str(ub.badge_id)
            badge_counts[key] = badge_counts.get(key, 0) + 1
        for ub in badges:
            ub.awarded_count = badge_counts.get(str(ub.badge_id), 1)
        # De-duplicate by badge_id (keep one per badge with count)
        seen: set[str] = set()
        unique_badges = []
        for ub in badges:
            k = str(ub.badge_id)
            if k not in seen:
                seen.add(k)
                unique_badges.append(ub)
        badges = unique_badges
    except Exception:
        badges = []

    # Leaderboard rank (current month snapshot)
    leaderboard_rank = None
    try:
        rank_q = await db.execute(
            select(LeaderboardSnapshot.rank).where(
                LeaderboardSnapshot.user_id == user_id,
                LeaderboardSnapshot.period_type == "monthly",
            ).order_by(LeaderboardSnapshot.created_at.desc()).limit(1)
        )
        leaderboard_rank = rank_q.scalar()
    except Exception:
        pass

    return templates.TemplateResponse(
        "profile/index.html",
        _ctx(
            request,
            user_obj=user_obj,
            kpis=kpis,
            badges=badges,
            leaderboard_rank=leaderboard_rank,
        ),
    )


# ── POST /api/profile/update ──────────────────────────────────────────────────

@router.post("/api/profile/update", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    full_name_ar: str = Form(...),
    full_name_en: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.user import User

    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)

    try:
        user_id = uuid.UUID(user_payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    result = await db.execute(select(User).where(User.id == user_id))
    user_obj = result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(404)

    user_obj.full_name_ar = full_name_ar.strip()
    if full_name_en is not None:
        user_obj.full_name_en = full_name_en.strip() or None
    if phone is not None:
        user_obj.phone = phone.strip() or None
    user_obj.updated_at = datetime.now(tz=UTC)
    await db.flush()

    lang = getattr(request.state, "lang", "ar")
    return HTMLResponse(
        f'<p class="text-xs text-green-600 dark:text-green-400">✅ {t("app.saved", lang=lang)}</p>'
    )


# ── GET /profile/2fa/setup ───────────────────────────────────────────────────

@router.get("/profile/2fa/setup", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("dashboard.view"))])
async def twofa_setup_page(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    from app.models.user import User
    import pyotp, qrcode, base64
    from io import BytesIO

    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)
    try:
        user_id = uuid.UUID(user_payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    result = await db.execute(select(User).where(User.id == user_id))
    user_obj = result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(404)

    # Generate secret if not set
    if not user_obj.totp_secret:
        user_obj.totp_secret = pyotp.random_base32()
        await db.commit()

    totp = pyotp.TOTP(user_obj.totp_secret)
    uri  = totp.provisioning_uri(
        name=user_obj.email or user_obj.username,
        issuer_name="Mobily Support"
    )
    # Generate QR code as base64
    qr = qrcode.make(uri)
    buf = BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return templates.TemplateResponse(
        "profile/2fa_setup.html",
        _ctx(request, user_obj=user_obj, qr_b64=qr_b64, secret=user_obj.totp_secret),
    )


@router.post("/api/profile/2fa/verify", response_class=JSONResponse)
async def twofa_verify(
    request: Request,
    code: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User
    import pyotp

    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)
    try:
        user_id = uuid.UUID(user_payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    result = await db.execute(select(User).where(User.id == user_id))
    user_obj = result.scalar_one_or_none()
    if not user_obj or not user_obj.totp_secret:
        raise HTTPException(404)

    lang = getattr(request.state, "lang", "ar")
    totp = pyotp.TOTP(user_obj.totp_secret)
    if totp.verify(code.strip()):
        user_obj.totp_enabled = True
        user_obj.updated_at = datetime.now(tz=UTC)
        await db.commit()
        return JSONResponse({"ok": True, "message": "تم تفعيل المصادقة الثنائية بنجاح" if lang == "ar" else "2FA enabled successfully"})

    return JSONResponse({"ok": False, "error": "الرمز غير صحيح أو انتهت صلاحيته" if lang == "ar" else "Invalid or expired code"}, status_code=400)


@router.post("/api/profile/2fa/disable", response_class=JSONResponse)
async def twofa_disable(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User

    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)
    try:
        user_id = uuid.UUID(user_payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    result = await db.execute(select(User).where(User.id == user_id))
    user_obj = result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(404)

    lang = getattr(request.state, "lang", "ar")
    user_obj.totp_enabled = False
    user_obj.totp_secret = None
    user_obj.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True, "message": "تم إلغاء تفعيل المصادقة الثنائية" if lang == "ar" else "2FA disabled"})


# ── GET /profile/password ────────────────────────────────────────────────────

@router.get("/profile/password", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("dashboard.view"))])
async def password_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "profile/password.html",
        _ctx(request),
    )


# ── POST /api/profile/password ────────────────────────────────────────────────

@router.post("/api/profile/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User
    import argon2
    from argon2 import PasswordHasher

    lang = getattr(request.state, "lang", "ar")
    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)

    try:
        user_id = uuid.UUID(user_payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    if new_password != confirm_password:
        return JSONResponse(
            {"ok": False, "error": "كلمتا المرور غير متطابقتين" if lang == "ar" else "Passwords do not match"},
            status_code=400,
        )

    if len(new_password) < 8:
        return JSONResponse(
            {"ok": False, "error": "كلمة المرور يجب أن تكون 8 أحرف على الأقل" if lang == "ar" else "Password must be at least 8 characters"},
            status_code=400,
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user_obj = result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(404)

    ph = PasswordHasher()
    try:
        ph.verify(user_obj.password_hash, current_password)
    except argon2.exceptions.VerifyMismatchError:
        return JSONResponse(
            {"ok": False, "error": "كلمة المرور الحالية غير صحيحة" if lang == "ar" else "Current password is incorrect"},
            status_code=400,
        )

    user_obj.password_hash = ph.hash(new_password)
    user_obj.updated_at = datetime.now(tz=UTC)
    await db.commit()

    return JSONResponse({"ok": True, "message": "تم تغيير كلمة المرور بنجاح" if lang == "ar" else "Password changed successfully"})


# ── POST /api/profile/notifications ───────────────────────────────────────────

@router.post("/api/profile/notifications")
async def update_notifications(
    request: Request,
    email_on_assign: Optional[str] = Form(None),
    sms_on_sla: Optional[str] = Form(None),
    email_daily: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User

    user_payload = getattr(request.state, "user", None)
    if not user_payload:
        raise HTTPException(401)

    try:
        user_id = uuid.UUID(user_payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    result = await db.execute(select(User).where(User.id == user_id))
    user_obj = result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(404)

    user_obj.notify_email_assign = email_on_assign == "on"
    user_obj.notify_sms_sla = sms_on_sla == "on"
    user_obj.notify_email_daily = email_daily == "on"
    user_obj.updated_at = datetime.now(tz=UTC)
    await db.commit()

    lang = getattr(request.state, "lang", "ar")
    return JSONResponse({"ok": True, "message": t("app.saved", lang=lang)})
