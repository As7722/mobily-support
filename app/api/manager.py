"""
Manager Dashboard + Settings + Analytics + Tickets Routes
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS, invalidate_all_permission_caches, require_permission
from app.core.redis import get_redis
from app.core.templates import templates
from app.i18n import t
from app.services.kpi import get_manager_kpis, get_sla_violations
from app.services.queue import get_smart_queue

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


# ── GET /manager (unified hub with tabs) ───────────────────────────────────────

@router.get("/manager", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_dashboard(
    request: Request,
    tab: Optional[str] = None,
    period: str = "today",
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> HTMLResponse:
    """Unified manager hub: overview tab in-page; other tabs redirect to full pages."""
    active_tab = (tab or "overview") if (tab and tab.strip()) else "overview"
    if active_tab != "overview":
        if active_tab == "audit":
            return RedirectResponse(url="/manager/settings?tab=audit", status_code=302)
        if active_tab == "scheduled_reports":
            return RedirectResponse(url="/manager/settings?tab=reports", status_code=302)
        path = "call-logs" if active_tab == "call_logs" else ("kb-categories" if active_tab == "kb_categories" else active_tab)
        return RedirectResponse(url=f"/manager/{path}", status_code=302)
    from app.models.ticket import Ticket
    from app.models.user import User
    from app.models.category import Category
    from app.models.knowledge import KnowledgeArticle
    from app.services.kpi import _period_range
    from sqlalchemy import extract
    from sqlalchemy.sql import exists as sa_exists

    kpis = await get_manager_kpis(db, redis, period)
    violations = await get_sla_violations(db, limit=5)
    queue = await get_smart_queue(db, role="manager", per_page=10)
    lang = getattr(request.state, "lang", "ar")

    # ── Top agents (scoped to period) ───────────────────────────────────────────
    p_start, p_end = _period_range(period)
    agents_q = await db.execute(
        select(
            User.id,
            User.full_name_ar,
            User.full_name_en,
            func.count(Ticket.id).label("resolved"),
            func.avg(Ticket.csat_score).label("csat"),
            func.avg(Ticket.total_time_seconds).label("avg_secs"),
        )
        .join(Ticket, Ticket.assigned_to == User.id, isouter=True)
        .where(
            Ticket.resolved_at >= p_start,
            Ticket.resolved_at < p_end,
            Ticket.status.in_(["resolved", "closed"]),
            Ticket.deleted_at.is_(None),
        )
        .group_by(User.id, User.full_name_ar, User.full_name_en)
        .order_by(func.count(Ticket.id).desc())
        .limit(10)
    )
    top_agents_raw = agents_q.all()
    max_resolved = max((r.resolved for r in top_agents_raw), default=1)
    top_agents = [
        type("A", (), {
            "full_name_ar": r.full_name_ar or "—",
            "full_name_en": r.full_name_en or r.full_name_ar or "—",
            "resolved": r.resolved,
            "csat_avg": round(float(r.csat or 0), 1) if r.csat else None,
            "avg_mins": int((r.avg_secs or 0) / 60) if r.avg_secs else None,
            "pct": int(r.resolved / max(max_resolved, 1) * 100),
        })()
        for r in top_agents_raw
    ]

    # ── Peak hours heatmap (30-day data, dow/hr/cnt) ───────────────────────────
    heat_start = datetime.now(tz=UTC) - timedelta(days=30)
    heat_q = await db.execute(
        select(
            extract("dow", Ticket.created_at).label("dow"),
            extract("hour", Ticket.created_at).label("hr"),
            func.count(Ticket.id).label("cnt"),
        )
        .where(Ticket.created_at >= heat_start, Ticket.deleted_at.is_(None))
        .group_by("dow", "hr")
    )
    heat_rows = heat_q.all()
    heat_map_dict: dict[tuple[int, int], int] = {}
    for row in heat_rows:
        heat_map_dict[(int(row.dow), int(row.hr))] = row.cnt
    peak_hours = [
        {"dow": d, "hr": h, "cnt": heat_map_dict.get((d, h), 0)}
        for d in range(7) for h in range(24)
    ]

    # ── KB gaps ────────────────────────────────────────────────────────────────
    kb_subq = (
        select(KnowledgeArticle.id)
        .where(
            KnowledgeArticle.category_id == Category.id,
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "internal",
            KnowledgeArticle.is_published.is_(True),
        )
        .correlate(Category)
    )
    cats_q = await db.execute(
        select(Category.id, Category.name_ar, Category.name_en, func.count(Ticket.id).label("cnt"))
        .join(Ticket, Ticket.category_id == Category.id, isouter=True)
        .where(Ticket.deleted_at.is_(None), ~sa_exists(kb_subq))
        .group_by(Category.id, Category.name_ar, Category.name_en)
        .having(func.count(Ticket.id) > 0)
        .order_by(func.count(Ticket.id).desc())
        .limit(10)
    )
    kb_gaps = [
        {"topic": r.name_ar, "topic_en": r.name_en, "count": r.cnt}
        for r in cats_q.all()
    ]

    return templates.TemplateResponse(
        "manager/hub.html",
        _ctx(
            request,
            active_tab=active_tab,
            kpis=kpis,
            violations=violations,
            queue=queue,
            period=period,
            top_agents=top_agents,
            peak_hours=peak_hours,
            kb_gaps=kb_gaps,
        ),
    )


# ── GET /api/manager/kpis (JSON for chart refresh) ───────────────────────────

@router.get("/api/manager/kpis",
            dependencies=[Depends(require_permission("manager.view"))])
async def kpis_json(
    request: Request,
    period: str = "today",
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    kpis = await get_manager_kpis(db, None, period)
    return JSONResponse(kpis)


# ── GET /manager/settings ──────────────────────────────────────────────────────

@router.get("/manager/users", response_class=HTMLResponse)
async def manager_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """User management page: allowed for manager and admin only. Manager cannot manage admin users."""
    import traceback
    from app.models.user import User
    from app.models.department import Department, UserDepartment

    payload = getattr(request.state, "user", None)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=t("errors.unauthorized", lang=getattr(request.state, "lang", "ar")))
    role = (payload.get("role") or "").strip().lower()
    if role not in ("manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=t("errors.permission_denied", lang=getattr(request.state, "lang", "ar")))

    try:
        users = list((await db.execute(
            select(User).where(User.deleted_at.is_(None))
            .options(selectinload(User.department))
            .order_by(User.role, User.full_name_ar)
        )).scalars().all())

        departments = list((await db.execute(
            select(Department).where(Department.deleted_at.is_(None), Department.is_active.is_(True))
            .order_by(Department.name_ar)
        )).scalars().all())

        # Load user→departments mapping (Row: 0=user_id, 1=department_id)
        result_ud = await db.execute(select(UserDepartment.user_id, UserDepartment.department_id))
        rows_ud = result_ud.all()
        user_dept_map: dict[str, list[str]] = {}
        for row in rows_ud:
            uid_str = str(row[0])
            did_str = str(row[1])
            user_dept_map.setdefault(uid_str, []).append(did_str)

        ctx = _ctx(
            request,
            users=users,
            departments=departments,
            user_dept_map=user_dept_map,
            current_role=(getattr(request.state, "user", {}) or {}).get("role", ""),
        )
        # Render now so any template error is caught below
        html = templates.env.get_template("manager/users.html").render(**ctx)
        return HTMLResponse(html)
    except Exception:
        # Show traceback so we can fix the root cause (remove after fix)
        return HTMLResponse(
            f"<pre style='white-space:pre-wrap;font-size:12px;'>manager/users error:\n{traceback.format_exc()}</pre>",
            status_code=500,
        )


@router.get("/manager/settings", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.settings"))])
async def manager_settings(
    request: Request,
    tab: str = "form_builder",
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> HTMLResponse:
    from app.models.automation import AutomationRule
    from app.models.audit import AuditLog
    from app.models.sla import SLAPolicy
    from app.models.form import FormVersion
    from app.models.notification import NotificationRule

    form_versions = list((await db.execute(
        select(FormVersion).where(FormVersion.deleted_at.is_(None)).order_by(FormVersion.created_at.desc()).limit(5)
    )).scalars().all())

    active_form = next((fv for fv in form_versions if fv.is_active), None)
    active_form_schema = {}
    if active_form and active_form.schema:
        active_form_schema = active_form.schema

    sla_policies = list((await db.execute(
        select(SLAPolicy).where(SLAPolicy.deleted_at.is_(None)).order_by(SLAPolicy.name_ar)
    )).scalars().all())

    automation_rules = list((await db.execute(
        select(AutomationRule).where(AutomationRule.deleted_at.is_(None)).order_by(AutomationRule.created_at.desc())
    )).scalars().all())

    # Exclude admin so report shows all other users (employee, supervisor, manager, portal)
    audit_logs = list((await db.execute(
        select(AuditLog)
        .options(selectinload(AuditLog.actor))
        .where(or_(AuditLog.actor_role.is_(None), AuditLog.actor_role != "admin"))
        .order_by(AuditLog.created_at.desc())
        .limit(500)
    )).scalars().all())

    notif_rules = list((await db.execute(
        select(NotificationRule).order_by(NotificationRule.event_type)
    )).scalars().all())

    from app.models.user import User
    audit_filter_users = list((await db.execute(
        select(User).where(User.is_active.is_(True), User.deleted_at.is_(None)).order_by(User.full_name_ar)
    )).scalars().all())

    # Call reason fields from Redis (multi-field format)
    from app.api.dashboard import _get_call_reason_fields
    from app.services.reports import REPORT_TYPES
    call_reason_cfg = {"fields": await _get_call_reason_fields(redis)}

    hub_tab = "audit" if tab == "audit" else ("scheduled_reports" if tab == "reports" else "settings")
    return templates.TemplateResponse(
        "manager/settings.html",
        _ctx(
            request,
            active_tab=tab,
            hub_tab=hub_tab,
            form_versions=form_versions,
            active_form_schema=active_form_schema,
            sla_policies=sla_policies,
            automation_rules=automation_rules,
            audit_logs=audit_logs,
            notif_rules=notif_rules,
            call_reason_cfg=call_reason_cfg,
            report_types=REPORT_TYPES,
            audit_filter_users=audit_filter_users,
        ),
    )


# ── GET /api/manager/audit/export (Excel) ───────────────────────────────────────

def _audit_action_label(action: str, lang: str) -> str:
    """Human-readable label for audit action codes."""
    _labels_ar = {
        "auth.login": "تسجيل دخول",
        "auth.logout": "تسجيل خروج",
        "auth.login_failed": "فشل تسجيل الدخول",
        "auth.password_reset": "إعادة تعيين كلمة المرور",
        "user.create": "إنشاء مستخدم",
        "user.update": "تحديث مستخدم",
        "user.delete": "حذف مستخدم",
        "user.role_changed": "تغيير دور المستخدم",
        "user.toggle_active": "تفعيل/إيقاف مستخدم",
        "ticket.create": "إنشاء تذكرة",
        "ticket.update": "تحديث تذكرة",
        "ticket.assign": "تعيين تذكرة",
        "ticket.status_change": "تغيير حالة تذكرة",
        "ticket.resolve": "حل تذكرة",
        "ticket.close": "إغلاق تذكرة",
        "ticket.comment": "تعليق/رد على تذكرة",
        "ticket.merge": "دمج تذاكر",
        "ticket.split": "تقسيم تذكرة",
        "ticket.escalate": "تصعيد تذكرة",
        "sla.create": "إنشاء SLA",
        "sla.update": "تحديث SLA",
        "sla.delete": "حذف SLA",
        "automation.create": "إنشاء قاعدة تشغيل تلقائي",
        "automation.update": "تحديث قاعدة تشغيل تلقائي",
        "automation.delete": "حذف قاعدة تشغيل تلقائي",
        "notification.toggle": "تفعيل/إيقاف إشعار",
        "department.create": "إنشاء قسم",
        "department.update": "تحديث قسم",
        "kb.create": "إنشاء مقالة قاعدة معرفة",
        "kb.update": "تحديث مقالة قاعدة معرفة",
        "kb.delete": "حذف مقالة قاعدة معرفة",
        "report.scheduled": "جدولة تقرير",
        "export.audit": "تصدير سجل التدقيق",
        "export.tickets": "تصدير التذاكر",
        "portal.track": "تتبع تذكرة (بورتال)",
        "portal.view": "عرض تذكرة (بورتال)",
        "portal.reply": "رد عميل (بورتال)",
        "portal.csat_submit": "تقييم CSAT (بورتال)",
        "portal.register_employee": "طلب تسجيل موظف فرع (بورتال)",
    }
    _labels_en = {
        "auth.login": "Login",
        "auth.logout": "Logout",
        "auth.login_failed": "Login failed",
        "user.create": "User created",
        "user.update": "User updated",
        "ticket.create": "Ticket created",
        "ticket.update": "Ticket updated",
        "ticket.assign": "Ticket assigned",
        "ticket.status_change": "Status changed",
        "ticket.resolve": "Ticket resolved",
        "ticket.close": "Ticket closed",
        "ticket.comment": "Comment/Reply on ticket",
        "ticket.merge": "Tickets merged",
        "ticket.split": "Ticket split",
        "ticket.escalate": "Ticket escalated",
        "sla.create": "SLA created",
        "sla.update": "SLA updated",
        "report.scheduled": "Report scheduled",
        "export.audit": "Audit export",
        "portal.track": "Track ticket (portal)",
        "portal.view": "View ticket (portal)",
        "portal.reply": "Customer reply (portal)",
        "portal.csat_submit": "CSAT submit (portal)",
        "portal.register_employee": "Register employee request (portal)",
    }
    d = _labels_ar if lang == "ar" else _labels_en
    return d.get(action, action or "—")


def _audit_resource_label(resource_type: str, lang: str) -> str:
    """Human-readable label for resource types."""
    _ar = {"tickets": "التذاكر", "users": "المستخدمون", "sla_policies": "سياسات SLA", "audit_log": "سجل التدقيق",
           "scheduled_reports": "التقارير المجدولة", "notification_rules": "قواعد الإشعارات", "departments": "الأقسام",
           "categories": "التصنيفات", "knowledge_articles": "قاعدة المعرفة", "form_versions": "إصدارات النماذج"}
    _en = {"tickets": "Tickets", "users": "Users", "sla_policies": "SLA policies", "audit_log": "Audit log",
           "scheduled_reports": "Scheduled reports", "notification_rules": "Notification rules", "departments": "Departments"}
    d = _ar if lang == "ar" else _en
    return d.get(resource_type, resource_type or "—")


def _parse_audit_date(s: Optional[str]) -> Optional[datetime]:
    """Parse YYYY-MM-DD to datetime at 00:00:00 UTC."""
    if not s or not s.strip():
        return None
    try:
        from datetime import date as date_type
        parts = s.strip().split("-")
        if len(parts) != 3:
            return None
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return datetime(y, m, d, 0, 0, 0, tzinfo=UTC)
    except (ValueError, IndexError):
        return None


@router.get("/api/manager/audit/export",
            dependencies=[Depends(require_permission("manager.settings"))])
async def export_audit_log(
    request: Request,
    resource_type: Optional[str] = None,
    action: Optional[str] = None,
    days: Optional[int] = 90,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    hour_from: Optional[int] = None,
    minute_from: Optional[int] = None,
    hour_to: Optional[int] = None,
    minute_to: Optional[int] = None,
    actor_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export audit log to Excel — enterprise-grade report with full filters (date, time, user, action, resource)."""
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        import json as _json
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    now = datetime.now(tz=UTC)
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    period_desc = ""
    days = min(max(1, days or 90), 365)

    if date_from or date_to:
        start_dt = _parse_audit_date(date_from) or _parse_audit_date(date_to) or (now - timedelta(days=90))
        end_dt = _parse_audit_date(date_to) or _parse_audit_date(date_from) or now
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        h_f = hour_from if hour_from is not None and 0 <= hour_from <= 23 else 0
        m_f = minute_from if minute_from is not None and 0 <= minute_from <= 59 else 0
        h_t = hour_to if hour_to is not None and 0 <= hour_to <= 23 else 23
        m_t = minute_to if minute_to is not None and 0 <= minute_to <= 59 else 59
        start_dt = start_dt.replace(hour=h_f, minute=m_f, second=0, microsecond=0)
        end_dt = end_dt.replace(hour=h_t, minute=m_t, second=59, microsecond=999999)
        period_desc = f"{start_dt.strftime('%Y-%m-%d %H:%M')} — {end_dt.strftime('%Y-%m-%d %H:%M')} UTC"
    else:
        start_dt = now - timedelta(days=days)
        end_dt = now
        period_desc = f"last {days} days" if lang == "en" else f"آخر {days} يوم"

    # Exclude admin so export shows all other users (employee, supervisor, manager, portal)
    q = (
        select(AuditLog)
        .options(selectinload(AuditLog.actor))
        .where(
            AuditLog.created_at >= start_dt,
            AuditLog.created_at <= end_dt,
            or_(AuditLog.actor_role.is_(None), AuditLog.actor_role != "admin"),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(50000)
    )
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if action:
        q = q.where(AuditLog.action == action)
    if actor_id:
        try:
            q = q.where(AuditLog.actor_id == uuid.UUID(actor_id))
        except (ValueError, TypeError):
            pass

    logs = list((await db.execute(q)).scalars().all())

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.EXPORT_AUDIT,
        resource_type="audit_export",
        new_value={"count": len(logs), "date_from": date_from, "date_to": date_to, "resource_type": resource_type, "action": action, "actor_id": actor_id},
    )
    await db.commit()

    wb = openpyxl.Workbook()
    header_font_white = Font(bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="00AEEF", end_color="00AEEF", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # ── Sheet 1: Cover / Summary ─────────────────────────────────────────────
    ws_cover = wb.active
    ws_cover.title = "Cover" if lang == "en" else "الغلاف"
    title = "Audit Log Report — Full Traceability" if lang == "en" else "تقرير سجل التدقيق — تتبع كامل"
    ws_cover["A1"] = title
    ws_cover["A1"].font = Font(bold=True, size=16)
    ws_cover.merge_cells("A1:D1")
    ws_cover["A2"] = f"Generated: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}" if lang == "en" else f"تاريخ التوليد: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    ws_cover["A3"] = f"Total events: {len(logs)}" if lang == "en" else f"إجمالي الأحداث: {len(logs)}"
    ws_cover["A4"] = f"Period: {period_desc}" if lang == "en" else f"الفترة: {period_desc}"
    row_cover = 5
    if date_from:
        ws_cover[f"A{row_cover}"] = f"From date: {date_from}" if lang == "en" else f"من تاريخ: {date_from}"
        row_cover += 1
    if date_to:
        ws_cover[f"A{row_cover}"] = f"To date: {date_to}" if lang == "en" else f"إلى تاريخ: {date_to}"
        row_cover += 1
    if hour_from is not None or hour_to is not None:
        m_f = f"{(minute_from or 0):02d}"
        m_t = f"{(minute_to or 59):02d}"
        t_range = f"{hour_from or 0}:{m_f} — {hour_to or 23}:{m_t}" if lang == "en" else f"{hour_from or 0}:{m_f} — {hour_to or 23}:{m_t}"
        ws_cover[f"A{row_cover}"] = f"Time range: {t_range}" if lang == "en" else f"الفترة الزمنية: {t_range}"
        row_cover += 1
    if resource_type:
        ws_cover[f"A{row_cover}"] = (f"Filter — Resource: {_audit_resource_label(resource_type, lang)}" if lang == "en"
                          else f"تصفية — المورد: {_audit_resource_label(resource_type, lang)}")
        row_cover += 1
    if action:
        ws_cover[f"A{row_cover}"] = (f"Filter — Action: {_audit_action_label(action, lang)}" if lang == "en"
                          else f"تصفية — الإجراء: {_audit_action_label(action, lang)}")
        row_cover += 1
    if actor_id:
        ws_cover[f"A{row_cover}"] = f"Filter — User ID: {actor_id}" if lang == "en" else f"تصفية — المستخدم: {actor_id}"
        row_cover += 1
    row_cover += 1
    ws_cover[f"A{row_cover}"] = "What is this report?" if lang == "en" else "ما هذا التقرير؟"
    ws_cover[f"A{row_cover}"].font = Font(bold=True, size=12)
    row_cover += 1
    ws_cover[f"A{row_cover}"] = ("Every change in the system (logins, ticket updates, settings, portal, etc.) is recorded with date, user (or IP), and details."
                      if lang == "en" else
                      "كل تغيير في النظام (تسجيل الدخول، التذاكر، الإعدادات، البورتال، إلخ) مُسجّل مع التاريخ والمستخدم (أو IP) والتفاصيل.")
    row_cover += 1
    ws_cover[f"A{row_cover}"] = ("Sheets: Data = all events; By User = count per user; By Action = count per action; Legend = codes."
                       if lang == "en" else "الأوراق: البيانات = كل الأحداث؛ حسب المستخدم = العدد لكل مستخدم؛ حسب الإجراء = العدد لكل إجراء؛ دليل الرموز.")
    row_cover += 1
    for r in range(1, row_cover + 1):
        ws_cover.row_dimensions[r].height = 22
    ws_cover.column_dimensions["A"].width = 58

    # ── Sheet 2: Summary by User ────────────────────────────────────────────
    from collections import Counter
    by_actor: Counter = Counter()
    for log in logs:
        key = str(log.actor_id) if log.actor_id else ("—" if lang == "ar" else "Guest/IP")
        by_actor[key] += 1
    ws_user = wb.create_sheet("By User" if lang == "en" else "حسب المستخدم", 1)
    ws_user["A1"] = "User / Actor" if lang == "en" else "المستخدم"
    ws_user["B1"] = "Count" if lang == "en" else "العدد"
    ws_user["A1"].font = ws_user["B1"].font = header_font_white
    ws_user["A1"].fill = ws_user["B1"].fill = header_fill
    actor_display: dict[str, str] = {}
    for log in logs:
        if log.actor_id:
            k = str(log.actor_id)
            if k not in actor_display and log.actor:
                actor_display[k] = (log.actor.full_name_ar if lang == "ar" else (log.actor.full_name_en or log.actor.full_name_ar)) or log.actor.username or k
            elif k not in actor_display:
                actor_display[k] = k
    for idx, (actor_key, count) in enumerate(sorted(by_actor.items(), key=lambda x: -x[1]), 2):
        if actor_key not in ("—", "Guest/IP"):
            display = actor_display.get(actor_key, actor_key)
        else:
            display = "— (Portal/Guest)" if lang == "en" else "— (بورتال/زائر)"
        ws_user.cell(row=idx, column=1, value=display)
        ws_user.cell(row=idx, column=2, value=count)
    ws_user.column_dimensions["A"].width = 35
    ws_user.column_dimensions["B"].width = 10

    # ── Sheet 3: Summary by Action ──────────────────────────────────────────
    by_action: Counter = Counter()
    for log in logs:
        by_action[log.action or ""] += 1
    ws_act = wb.create_sheet("By Action" if lang == "en" else "حسب الإجراء", 2)
    ws_act["A1"] = "Action (code)" if lang == "en" else "الإجراء (رمز)"
    ws_act["B1"] = "Label" if lang == "en" else "التسمية"
    ws_act["C1"] = "Count" if lang == "en" else "العدد"
    for c in ("A1", "B1", "C1"):
        ws_act[c].font = header_font_white
        ws_act[c].fill = header_fill
    for idx, (act_code, count) in enumerate(sorted(by_action.items(), key=lambda x: -x[1]), 2):
        ws_act.cell(row=idx, column=1, value=act_code or "—")
        ws_act.cell(row=idx, column=2, value=_audit_action_label(act_code, lang))
        ws_act.cell(row=idx, column=3, value=count)
    ws_act.column_dimensions["A"].width = 32
    ws_act.column_dimensions["B"].width = 28
    ws_act.column_dimensions["C"].width = 10

    # ── Sheet 4: Legend ────────────────────────────────────────────────────
    ws_leg = wb.create_sheet("Legend" if lang == "en" else "دليل الرموز", 3)
    leg_title = "Action & resource codes — quick reference" if lang == "en" else "رموز الإجراءات والموارد — مرجع سريع"
    ws_leg["A1"] = leg_title
    ws_leg["A1"].font = Font(bold=True, size=12)
    ws_leg.merge_cells("A1:C1")
    ws_leg["A2"] = "Action (code)" if lang == "en" else "الإجراء (الرمز)"
    ws_leg["B2"] = "Meaning" if lang == "en" else "المعنى"
    ws_leg["A2"].font = ws_leg["B2"].font = Font(bold=True)
    row = 3
    for code, meaning_ar in [
        ("auth.login", "تسجيل دخول"),
        ("auth.logout", "تسجيل خروج"),
        ("user.create / user.update", "إنشاء أو تحديث مستخدم"),
        ("ticket.create / ticket.update / ticket.assign", "إنشاء أو تحديث أو تعيين تذكرة"),
        ("ticket.status_change / ticket.resolve / ticket.close", "تغيير حالة أو حل أو إغلاق تذكرة"),
        ("sla.create / sla.update / sla.delete", "إنشاء أو تحديث أو حذف سياسة SLA"),
        ("report.scheduled", "جدولة تقرير"),
        ("export.audit", "تصدير سجل التدقيق"),
        ("portal.track", "تتبع تذكرة من البورتال"),
        ("portal.view", "عرض صفحة التذكرة من البورتال"),
        ("portal.reply", "رد العميل من البورتال"),
        ("portal.csat_submit", "إرسال تقييم CSAT من البورتال"),
        ("portal.register_employee", "طلب تسجيل موظف فرع من البورتال"),
    ]:
        ws_leg.cell(row=row, column=1, value=code)
        ws_leg.cell(row=row, column=2, value=meaning_ar if lang == "ar" else code.replace(".", " — "))
        row += 1
    ws_leg["A14"] = "Resource type" if lang == "en" else "نوع المورد"
    ws_leg["A14"].font = Font(bold=True)
    ws_leg["A15"] = "tickets = التذاكر" if lang == "ar" else "tickets = Tickets"
    ws_leg["A16"] = "users = المستخدمون" if lang == "ar" else "users = Users"
    ws_leg["A17"] = "sla_policies = سياسات SLA" if lang == "ar" else "sla_policies = SLA policies"
    ws_leg.column_dimensions["A"].width = 42
    ws_leg.column_dimensions["B"].width = 35

    # ── Sheet 5: Data (full log) ─────────────────────────────────────────────
    ws = wb.create_sheet("Data" if lang == "en" else "البيانات", 4)
    headers = [
        "No." if lang == "en" else "م",
        "Date & time" if lang == "en" else "التاريخ والوقت",
        "Action" if lang == "en" else "الإجراء",
        "Action (code)" if lang == "en" else "الإجراء (رمز)",
        "Resource" if lang == "en" else "المورد",
        "Resource ID" if lang == "en" else "معرف المورد",
        "User" if lang == "en" else "المستخدم",
        "Role" if lang == "en" else "الدور",
        "IP" if lang == "en" else "عنوان IP",
        "Details (summary)" if lang == "en" else "ملخص التفاصيل",
        "Full details (JSON)" if lang == "en" else "التفاصيل الكاملة",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    def _summary_detail(log) -> str:
        """Short human-readable summary of old_value/new_value."""
        if log.new_value and isinstance(log.new_value, dict):
            keys = list(log.new_value.keys())[:5]
            return ", ".join(f"{k}={log.new_value.get(k)}" for k in keys if log.new_value.get(k) is not None)
        if log.old_value and isinstance(log.old_value, dict):
            keys = list(log.old_value.keys())[:5]
            return ", ".join(f"{k}={log.old_value.get(k)}" for k in keys if log.old_value.get(k) is not None)
        return ""

    for row_idx, log in enumerate(logs, 2):
        actor_name = "—"
        if log.actor:
            actor_name = (log.actor.full_name_ar if lang == "ar" else (log.actor.full_name_en or log.actor.full_name_ar)) or log.actor.username or "—"
        else:
            actor_name = "Portal (Visitor)" if lang == "en" else "بورتال / زائر"
            if log.actor_ip:
                actor_name += f" ({log.actor_ip})"

        action_display = _audit_action_label(log.action or "", lang)
        resource_display = _audit_resource_label(log.resource_type or "", lang)
        new_str = _json.dumps(log.new_value, ensure_ascii=False) if log.new_value else ""
        old_str = _json.dumps(log.old_value, ensure_ascii=False) if log.old_value else ""
        details_full = (new_str or old_str).strip()
        if len(details_full) > 8000:
            details_full = details_full[:8000] + "..."
        summary = _summary_detail(log)

        created_str = log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else ""

        row_data = [
            row_idx - 1,
            created_str,
            action_display,
            log.action or "",
            resource_display,
            str(log.resource_id) if log.resource_id else "",
            actor_name,
            log.actor_role or "",
            str(log.actor_ip) if log.actor_ip else "",
            summary[:500] if summary else "—",
            details_full or "—",
        ]
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = min(max(10, len(str(headers[col - 1])) + 2), 45)

    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)
    body = buf.getvalue()
    filename = f"audit_log_{datetime.now(tz=UTC).strftime('%Y-%m-%d_%H%M')}.xlsx"
    return StreamingResponse(
        iter([body]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
        },
    )


# ── Notification rule toggles (manager+ only) ────────────────────────────────

@router.post("/api/manager/notif-rules/{rule_id}/toggle",
             dependencies=[Depends(require_permission("manager.settings"))])
async def toggle_notif_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.notification import NotificationRule
    result = await db.execute(select(NotificationRule).where(NotificationRule.id == uuid.UUID(rule_id)))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404)
    rule.is_active = not rule.is_active
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.NOTIFICATION_TOGGLE,
        resource_type="notification_rules",
        resource_id=rule.id,
        new_value={"rule_id": str(rule.id), "is_active": rule.is_active},
    )
    await db.commit()
    return JSONResponse({"ok": True, "is_active": rule.is_active})


@router.post("/api/manager/notif-rules/{rule_id}/toggle-sound",
             dependencies=[Depends(require_permission("manager.settings"))])
async def toggle_notif_rule_sound(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.notification import NotificationRule
    result = await db.execute(select(NotificationRule).where(NotificationRule.id == uuid.UUID(rule_id)))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404)
    # sound_enabled is not a DB column — toggle in-memory and store via channels
    current = "sound" in (rule.channels or [])
    if current:
        rule.channels = [c for c in (rule.channels or []) if c != "sound"]
    else:
        rule.channels = list(rule.channels or []) + ["sound"]
    await db.commit()
    return JSONResponse({"ok": True, "sound_enabled": not current})


@router.post("/api/manager/notif-rules/{rule_id}/sound-file",
             dependencies=[Depends(require_permission("manager.settings"))])
async def set_notif_rule_sound_file(
    rule_id: str,
    sf: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.notification import NotificationRule
    VALID = {"default", "chime", "alert", "urgent", "warning", "success", "mention"}
    if sf not in VALID:
        raise HTTPException(400)
    result = await db.execute(select(NotificationRule).where(NotificationRule.id == uuid.UUID(rule_id)))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404)
    rule.sound_file = sf
    await db.commit()
    return JSONResponse({"ok": True})


# ── POST /api/manager/sla-policy ──────────────────────────────────────────────

@router.post("/api/manager/sla-policy",
             dependencies=[Depends(require_permission("manager.settings"))])
async def upsert_sla_policy(
    request: Request,
    policy_id: Optional[str] = Form(None),
    name_ar: str = Form(...),
    name_en: Optional[str] = Form(None),
    priority: str = Form(...),
    response_minutes: int = Form(...),
    resolution_minutes: int = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.sla import SLAPolicy
    from app.models.audit import AuditLog

    user = getattr(request.state, "user", {}) or {}
    actor_id_str = user.get("sub")

    now = datetime.now(tz=UTC)
    async with db.begin():
        if policy_id:
            result = await db.execute(select(SLAPolicy).where(SLAPolicy.id == uuid.UUID(policy_id)))
            policy = result.scalar_one_or_none()
            if not policy:
                raise HTTPException(404)
        else:
            policy = SLAPolicy(id=uuid.uuid4())
            db.add(policy)

        policy.name_ar              = name_ar
        policy.name_en              = name_en or name_ar
        policy.priority             = priority
        policy.response_minutes     = response_minutes
        policy.resolution_minutes   = resolution_minutes
        policy.updated_at           = now

        # Audit log
        from app.services.audit import log, AuditAction
        actor_id = uuid.UUID(actor_id_str) if actor_id_str else None
        await log(
            db,
            AuditAction.SLA_POLICY_UPDATE if policy_id else AuditAction.SLA_POLICY_CREATE,
            actor_id=actor_id,
            resource_type="sla_policies",
            resource_id=policy.id,
            new_value={"name_ar": name_ar, "priority": priority, "response_minutes": response_minutes, "resolution_minutes": resolution_minutes},
        )

    return JSONResponse({"ok": True, "id": str(policy.id)})


# ── POST /api/manager/automation ──────────────────────────────────────────────

@router.post("/api/manager/automation",
             dependencies=[Depends(require_permission("manager.settings"))])
async def upsert_automation(
    request: Request,
    rule_id: Optional[str] = Form(None),
    name_ar: str = Form(...),
    trigger: str = Form(...),
    conditions_json: str = Form("[]"),
    actions_json: str = Form("[]"),
    is_active: str = Form("1"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    import json as _json
    from app.models.automation import AutomationRule

    now = datetime.now(tz=UTC)
    async with db.begin():
        if rule_id:
            result = await db.execute(select(AutomationRule).where(AutomationRule.id == uuid.UUID(rule_id)))
            rule = result.scalar_one_or_none()
            if not rule:
                raise HTTPException(404)
        else:
            rule = AutomationRule(id=uuid.uuid4())
            db.add(rule)

        rule.name_ar    = name_ar
        rule.trigger    = trigger
        rule.conditions = _json.loads(conditions_json)
        rule.actions    = _json.loads(actions_json)
        rule.is_active  = is_active == "1"
        rule.updated_at = now

    return JSONResponse({"ok": True, "id": str(rule.id)})


# ── DELETE /api/manager/automation/{id} ──────────────────────────────────────

@router.delete("/api/manager/automation/{rule_id}",
               dependencies=[Depends(require_permission("manager.settings"))])
async def delete_automation(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.automation import AutomationRule

    result = await db.execute(select(AutomationRule).where(AutomationRule.id == uuid.UUID(rule_id)))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404)
    async with db.begin():
        rule.deleted_at = datetime.now(tz=UTC)
    return JSONResponse({"ok": True})


# ── GET /manager/analytics ────────────────────────────────────────────────────
# Redirect to merged manager dashboard (analytics merged into /manager)

@router.get("/manager/analytics",
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_analytics(period: str = "month") -> RedirectResponse:
    return RedirectResponse(url=f"/manager?period={period}", status_code=302)


# ── GET /api/manager/analytics/kpis (partial refresh) ────────────────────────

@router.get("/api/manager/analytics/kpis", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def analytics_kpis_partial(
    request: Request,
    period: str = "month",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    kpis = await get_manager_kpis(db, None, period)
    return JSONResponse(kpis)


# ── GET /manager/tickets ──────────────────────────────────────────────────────

@router.get("/manager/tickets", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_tickets(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category_id: Optional[str] = None,
    date_range: Optional[str] = "30",
    include_archived: Optional[str] = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.ticket import Ticket
    from app.models.category import Category
    from app.models.user import User

    per_page = 25
    query = (
        select(Ticket)
        .where(Ticket.deleted_at.is_(None))
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.category),
        )
        .order_by(Ticket.created_at.desc())
    )

    # Filters
    if q:
        query = query.where(or_(
            Ticket.ticket_number.ilike(f"%{q}%"),
            Ticket.subject.ilike(f"%{q}%"),
            Ticket.description.ilike(f"%{q}%"),
            Ticket.submitter_name.ilike(f"%{q}%"),
        ))
    if status:
        query = query.where(Ticket.status == status)
    elif not include_archived:
        query = query.where(Ticket.status != "archived")
    if priority:
        query = query.where(Ticket.priority == priority)
    if category_id:
        try:
            query = query.where(Ticket.category_id == uuid.UUID(category_id))
        except ValueError:
            pass
    if date_range:
        try:
            days = int(date_range)
            cutoff = datetime.now(tz=UTC) - timedelta(days=days)
            query = query.where(Ticket.created_at >= cutoff)
        except ValueError:
            pass

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    tickets = list(result.scalars().all())

    # Categories for filter dropdown
    cats = list((await db.execute(select(Category).where(Category.deleted_at.is_(None)).order_by(Category.sort_order))).scalars().all())

    # Summary counts
    open_q = await db.execute(select(func.count()).select_from(Ticket).where(Ticket.status.in_(["new","open","pending_customer","pending_3rd"]), Ticket.deleted_at.is_(None)))
    resolved_q = await db.execute(select(func.count()).select_from(Ticket).where(Ticket.status.in_(["resolved","closed"]), Ticket.deleted_at.is_(None)))
    breached_q = await db.execute(select(func.count()).select_from(Ticket).where(Ticket.sla_breached.is_(True), Ticket.deleted_at.is_(None)))
    all_q = await db.execute(select(func.count()).select_from(Ticket).where(Ticket.deleted_at.is_(None)))

    summary = type("S", (), {
        "open": open_q.scalar() or 0,
        "resolved": resolved_q.scalar() or 0,
        "breached": breached_q.scalar() or 0,
        "total": all_q.scalar() or 0,
    })()

    return templates.TemplateResponse(
        "manager/tickets.html",
        _ctx(
            request,
            tickets=tickets,
            categories=cats,
            q=q, status=status, priority=priority,
            category_id=category_id, date_range=date_range,
            include_archived=bool(include_archived),
            page=page, total_pages=total_pages, total=total,
            summary=summary,
        ),
    )


# ── GET /api/manager/tickets/export ───────────────────────────────────────────

@router.get("/api/manager/tickets/export",
            dependencies=[Depends(require_permission("manager.view"))])
async def export_tickets(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    date_range: Optional[str] = "30",
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        import openpyxl
        import io
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.ticket import Ticket

    query = select(Ticket).where(Ticket.deleted_at.is_(None)).order_by(Ticket.created_at.desc()).limit(5000)
    if status:
        query = query.where(Ticket.status == status)
    if priority:
        query = query.where(Ticket.priority == priority)
    if date_range:
        try:
            days = int(date_range)
            cutoff = datetime.now(tz=UTC) - timedelta(days=days)
            query = query.where(Ticket.created_at >= cutoff)
        except ValueError:
            pass

    tickets = list((await db.execute(query)).scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tickets"
    ws.append(["Ticket #", "Subject", "Status", "Priority", "Channel", "Created At", "Resolved At", "SLA Breached"])
    for tk in tickets:
        ws.append([
            tk.ticket_number, tk.subject, tk.status, tk.priority, tk.channel,
            tk.created_at.strftime("%Y-%m-%d %H:%M") if tk.created_at else "",
            tk.resolved_at.strftime("%Y-%m-%d %H:%M") if tk.resolved_at else "",
            "Yes" if tk.sla_breached else "No",
        ])

    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tickets.xlsx"},
    )


# ── POST /api/manager/reports/send-now ───────────────────────────────────────

@router.post("/api/manager/reports/send-now", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("manager.view"))])
async def send_report_now(
    request: Request,
    report: str = Form(...),
    period: str = Form("month"),
) -> HTMLResponse:
    lang = getattr(request.state, "lang", "ar")
    # Trigger Celery task
    try:
        from app.worker.tasks.reports import generate_scheduled_report
        generate_scheduled_report.delay(report_type=report, period=period)
    except Exception:
        pass
    return HTMLResponse(f'<p class="text-sm text-green-600">✅ {t("report.sent_ok", lang=lang)}</p>')


# ── PATCH /api/manager/users/{id}/department (Manager ONLY) ───────────────

@router.patch("/api/manager/users/{user_id}/department", response_class=HTMLResponse,
              dependencies=[Depends(require_permission("manager.view"))])
async def assign_department(
    user_id: str,
    request: Request,
    department_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Iron Rule #4: ONLY Manager can assign an agent to a specialized department."""
    from app.models.user import User

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role not in ("manager", "admin"):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)
    if user.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can modify admin users")

    old_dept = str(user.department_id) if user.department_id else None
    new_dept = uuid.UUID(department_id) if department_id and department_id.strip() else None
    user.department_id = new_dept
    user.updated_at = datetime.now(tz=UTC)

    from app.services.audit import log, AuditAction
    await log(db, AuditAction.USER_DEPARTMENT_CHANGED,
        actor_id=uuid.UUID(actor.get("sub", "")),
        resource_type="users",
        resource_id=uid,
        new_value={"from": old_dept, "to": str(new_dept) if new_dept else None},
    )
    await db.commit()

    return HTMLResponse(f'<span class="text-xs text-green-600">✅</span>')


# ══════════════════════════════════════════════════════════════════════════════
# DEPARTMENT MANAGEMENT (Manager+)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/manager/departments", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_departments(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.department import Department, UserDepartment
    import json as _json

    departments = list((await db.execute(
        select(Department).where(Department.deleted_at.is_(None)).order_by(Department.name_ar)
    )).scalars().all())

    dept_user_counts: dict[str, int] = {}
    for d in departments:
        c = await db.execute(
            select(func.count()).select_from(UserDepartment).where(UserDepartment.department_id == d.id)
        )
        dept_user_counts[str(d.id)] = c.scalar() or 0

    departments_json = _json.dumps([{
        "id": str(d.id), "name_ar": d.name_ar, "name_en": d.name_en,
        "code": d.code, "is_active": d.is_active,
        "user_count": dept_user_counts.get(str(d.id), 0),
        "portal_fields": d.portal_fields or [],
    } for d in departments], ensure_ascii=False)

    return templates.TemplateResponse(
        "manager/departments.html",
        _ctx(request, departments_json=departments_json),
    )


@router.post("/api/manager/departments",
             dependencies=[Depends(require_permission("manager.settings"))])
async def create_department(
    request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.department import Department

    body = await request.json()
    name_ar = (body.get("name_ar") or "").strip()
    name_en = (body.get("name_en") or "").strip()
    code = (body.get("code") or "").strip()

    if not name_ar or not code:
        raise HTTPException(422, detail="Name and code required")

    existing = await db.execute(select(Department).where(Department.code == code, Department.deleted_at.is_(None)))
    if existing.scalar_one_or_none():
        raise HTTPException(409, detail="Department code already exists")

    dept = Department(
        id=uuid.uuid4(),
        name_ar=name_ar,
        name_en=name_en or name_ar,
        code=code,
        is_active=True,
        portal_fields=[],
    )
    db.add(dept)
    await db.flush()
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.DEPARTMENT_CREATE,
        resource_type="departments",
        resource_id=dept.id,
        new_value={"name_ar": name_ar, "code": code},
    )
    await db.commit()
    return JSONResponse({"ok": True, "id": str(dept.id)})


@router.put("/api/manager/departments/{dept_id}",
            dependencies=[Depends(require_permission("manager.settings"))])
async def update_department(
    dept_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.department import Department

    try:
        did = uuid.UUID(dept_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Department).where(Department.id == did, Department.deleted_at.is_(None)))
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(404)

    body = await request.json()
    old_vals = {"name_ar": dept.name_ar, "name_en": dept.name_en, "code": dept.code}
    for field in ("name_ar", "name_en", "code"):
        val = body.get(field)
        if val is not None:
            setattr(dept, field, val.strip() if isinstance(val, str) else val)
    dept.updated_at = datetime.now(tz=UTC)
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.DEPARTMENT_UPDATE,
        resource_type="departments",
        resource_id=did,
        old_value=old_vals,
        new_value={"name_ar": dept.name_ar, "name_en": dept.name_en, "code": dept.code},
    )
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/manager/departments/{dept_id}/toggle",
             dependencies=[Depends(require_permission("manager.settings"))])
async def toggle_department(
    dept_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.department import Department

    try:
        did = uuid.UUID(dept_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Department).where(Department.id == did, Department.deleted_at.is_(None)))
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(404)

    old_active = dept.is_active
    dept.is_active = not dept.is_active
    dept.updated_at = datetime.now(tz=UTC)
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.DEPARTMENT_TOGGLE,
        resource_type="departments",
        resource_id=did,
        new_value={"from": old_active, "to": dept.is_active},
    )
    await db.commit()
    return JSONResponse({"ok": True, "is_active": dept.is_active})


@router.put("/api/manager/departments/{dept_id}/fields",
            dependencies=[Depends(require_permission("manager.settings"))])
async def save_department_fields(
    dept_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.department import Department

    try:
        did = uuid.UUID(dept_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Department).where(Department.id == did, Department.deleted_at.is_(None)))
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(404)

    body = await request.json()
    fields = body.get("fields", [])
    if not isinstance(fields, list):
        raise HTTPException(422, detail="fields must be a list")

    dept.portal_fields = fields
    dept.updated_at = datetime.now(tz=UTC)
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.DEPARTMENT_FIELDS_UPDATE,
        resource_type="departments",
        resource_id=did,
        new_value={"portal_fields": fields},
    )
    await db.commit()
    return JSONResponse({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# KB CATEGORIES (قاعدة المعرفة — تصنيفات) — Manager with kb.edit
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/manager/kb-categories", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("kb.edit"))])
async def manager_kb_categories(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """List and manage KB categories (top-level: parent_id is None)."""
    from app.models.category import Category
    from app.models.knowledge import KnowledgeArticle
    import json as _json

    categories = list((await db.execute(
        select(Category)
        .where(Category.deleted_at.is_(None), Category.parent_id.is_(None))
        .order_by(Category.sort_order, Category.name_ar)
    )).scalars().all())

    article_counts: dict[str, int] = {}
    for c in categories:
        cnt = await db.scalar(
            select(func.count(KnowledgeArticle.id)).where(
                KnowledgeArticle.category_id == c.id,
                KnowledgeArticle.deleted_at.is_(None),
            )
        )
        article_counts[str(c.id)] = cnt or 0

    categories_json = _json.dumps([{
        "id": str(c.id),
        "name_ar": c.name_ar,
        "name_en": c.name_en,
        "description_ar": c.description_ar or "",
        "description_en": c.description_en or "",
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "article_count": article_counts.get(str(c.id), 0),
    } for c in categories], ensure_ascii=False)

    return templates.TemplateResponse(
        "manager/kb_categories.html",
        _ctx(request, categories_json=categories_json),
    )


@router.post("/api/manager/kb-categories",
             dependencies=[Depends(require_permission("kb.edit"))])
async def create_kb_category(
    request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.category import Category

    body = await request.json()
    name_ar = (body.get("name_ar") or "").strip()
    name_en = (body.get("name_en") or "").strip()
    description_ar = (body.get("description_ar") or "").strip() or None
    description_en = (body.get("description_en") or "").strip() or None
    sort_order = body.get("sort_order")
    if sort_order is not None and not isinstance(sort_order, int):
        try:
            sort_order = int(sort_order)
        except (TypeError, ValueError):
            sort_order = 0
    else:
        sort_order = sort_order if isinstance(sort_order, int) else 0

    if not name_ar:
        raise HTTPException(422, detail="Name (AR) required")

    cat = Category(
        id=uuid.uuid4(),
        name_ar=name_ar,
        name_en=name_en or name_ar,
        description_ar=description_ar,
        description_en=description_en,
        parent_id=None,
        sort_order=sort_order,
        is_active=True,
    )
    db.add(cat)
    await db.commit()
    return JSONResponse({"ok": True, "id": str(cat.id)})


@router.put("/api/manager/kb-categories/{category_id}",
            dependencies=[Depends(require_permission("kb.edit"))])
async def update_kb_category(
    category_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.category import Category

    try:
        cid = uuid.UUID(category_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(
        select(Category).where(Category.id == cid, Category.deleted_at.is_(None), Category.parent_id.is_(None))
    )
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404)

    body = await request.json()
    for field in ("name_ar", "name_en", "description_ar", "description_en", "sort_order", "is_active"):
        val = body.get(field)
        if val is None:
            continue
        if field == "sort_order":
            try:
                setattr(cat, field, int(val))
            except (TypeError, ValueError):
                pass
        elif field == "is_active":
            setattr(cat, field, bool(val))
        elif isinstance(val, str):
            setattr(cat, field, val.strip() if field not in ("description_ar", "description_en") else (val.strip() or None))
    cat.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


@router.delete("/api/manager/kb-categories/{category_id}",
               dependencies=[Depends(require_permission("kb.edit"))])
async def delete_kb_category(
    category_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.category import Category
    from app.models.knowledge import KnowledgeArticle

    try:
        cid = uuid.UUID(category_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(
        select(Category).where(Category.id == cid, Category.deleted_at.is_(None), Category.parent_id.is_(None))
    )
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404)

    # Unlink articles from this category (set category_id to null)
    articles_result = await db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.category_id == cid, KnowledgeArticle.deleted_at.is_(None))
    )
    for art in articles_result.scalars().all():
        art.category_id = None
        art.updated_at = datetime.now(tz=UTC)
    cat.deleted_at = datetime.now(tz=UTC)
    cat.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


@router.patch("/api/manager/users/{user_id}/departments",
              dependencies=[Depends(require_permission("manager.view"))])
async def assign_user_departments(
    user_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Assign a user to multiple departments."""
    from app.models.user import User
    from app.models.department import UserDepartment

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role not in ("manager", "admin"):
        raise HTTPException(403)

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)
    if user.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can modify admin users")

    body = await request.json()
    dept_ids = body.get("department_ids", [])

    # Clear existing assignments
    from sqlalchemy import delete
    await db.execute(delete(UserDepartment).where(UserDepartment.user_id == uid))

    # Add new assignments
    for did_str in dept_ids:
        try:
            did = uuid.UUID(did_str)
            db.add(UserDepartment(user_id=uid, department_id=did))
        except ValueError:
            continue

    # Set primary department_id to first one (or None)
    user.department_id = uuid.UUID(dept_ids[0]) if dept_ids else None
    user.updated_at = datetime.now(tz=UTC)

    from app.services.audit import log, AuditAction
    await log(db, AuditAction.USER_DEPARTMENTS_CHANGED,
        actor_id=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
        resource_type="users",
        resource_id=uid,
        new_value={"departments": dept_ids},
    )
    await db.commit()

    return HTMLResponse(f'<span class="text-xs text-green-600">✅</span>')


# ══════════════════════════════════════════════════════════════════════════════
# USER CRUD (Manager+)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/api/manager/users",
             dependencies=[Depends(require_permission("manager.settings"))])
async def create_user(
    request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.security import hash_password
    from app.models.user import User

    body = await request.json()
    username = (body.get("username") or "").strip()
    full_name_ar = (body.get("full_name_ar") or "").strip()
    role = (body.get("role") or "employee").strip()
    password = (body.get("password") or "").strip()

    if not username or not full_name_ar:
        raise HTTPException(422, detail="Username and name required")
    if not password or len(password) < 8:
        raise HTTPException(422, detail="Password required (min 8 characters)")
    if role not in ("employee", "supervisor", "manager", "admin"):
        raise HTTPException(422, detail="Invalid role")

    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can create admin users")

    existing = await db.execute(select(User).where(User.username == username, User.deleted_at.is_(None)))
    if existing.scalar_one_or_none():
        raise HTTPException(409, detail="Username already exists")

    user_obj = User(
        id=uuid.uuid4(),
        username=username,
        full_name_ar=full_name_ar,
        full_name_en=(body.get("full_name_en") or "").strip() or None,
        email=(body.get("email") or "").strip() or None,
        phone=(body.get("phone") or "").strip() or None,
        employee_id=(body.get("employee_id") or "").strip() or None,
        role=role,
        password_hash=hash_password(password),
    )
    db.add(user_obj)
    await db.flush()
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.USER_CREATE,
        resource_type="users",
        resource_id=user_obj.id,
        new_value={"username": username, "role": role, "full_name_ar": full_name_ar},
    )
    await db.commit()
    return JSONResponse({"ok": True, "id": str(user_obj.id)}, status_code=201)


@router.put("/api/manager/users/{user_id}",
            dependencies=[Depends(require_permission("manager.settings"))])
async def update_user(
    user_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if user.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can edit admin users")

    body = await request.json()
    old_vals = {f: getattr(user, f) for f in ("full_name_ar", "full_name_en", "email", "phone", "employee_id")}
    changes = {}
    for field in ("full_name_ar", "full_name_en", "email", "phone", "employee_id"):
        val = body.get(field)
        if val is not None:
            new_val = val.strip() if isinstance(val, str) else val
            setattr(user, field, new_val)
            if old_vals.get(field) != new_val:
                changes[field] = {"from": old_vals.get(field), "to": new_val}

    user.updated_at = datetime.now(tz=UTC)
    if changes:
        from app.services.audit import log_from_request, AuditAction
        await log_from_request(db, request, AuditAction.USER_UPDATE,
            resource_type="users",
            resource_id=uid,
            new_value=changes,
        )
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/manager/users/{user_id}/change-role",
             dependencies=[Depends(require_permission("manager.settings"))])
async def change_user_role(
    user_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    body = await request.json()
    new_role = (body.get("role") or "").strip()
    if new_role not in ("employee", "supervisor", "manager", "admin"):
        raise HTTPException(422, detail="Invalid role")

    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

    if user.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can change admin users")
    if new_role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can promote to admin")

    old_role = user.role
    user.role = new_role
    user.updated_at = datetime.now(tz=UTC)

    from app.services.audit import log, AuditAction
    await log(db, AuditAction.USER_ROLE_CHANGED,
        actor_id=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
        resource_type="users",
        resource_id=uid,
        new_value={"from": old_role, "to": new_role},
    )
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/manager/users/{user_id}/toggle-active",
             dependencies=[Depends(require_permission("manager.settings"))])
async def toggle_user_active(
    user_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if user.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can modify admin users")

    old_active = user.is_active
    user.is_active = not user.is_active
    user.updated_at = datetime.now(tz=UTC)
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.USER_TOGGLE_ACTIVE,
        resource_type="users",
        resource_id=uid,
        new_value={"from": old_active, "to": user.is_active},
    )
    await db.commit()
    return JSONResponse({"ok": True, "is_active": user.is_active})


@router.post("/api/manager/users/{user_id}/reset-password",
             dependencies=[Depends(require_permission("manager.settings"))])
async def reset_user_password(
    user_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.security import hash_password
    from app.models.user import User

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    body = await request.json()
    new_pass = (body.get("password") or "").strip()
    if not new_pass or len(new_pass) < 8:
        raise HTTPException(422, detail="Password required (min 8 characters)")

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if user.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can modify admin users")

    user.password_hash = hash_password(new_pass)
    user.updated_at = datetime.now(tz=UTC)
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(db, request, AuditAction.USER_PASSWORD_RESET,
        resource_type="users",
        resource_id=uid,
    )
    await db.commit()
    return JSONResponse({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSIONS MANAGEMENT (Manager+)
# ══════════════════════════════════════════════════════════════════════════════

_ALL_ROLES = ["employee", "supervisor", "manager", "admin"]
# Use single source of truth from core (enforcement uses same defaults + DB overrides)
_DEFAULT_PERMISSIONS = DEFAULT_ROLE_PERMISSIONS

_PERMISSION_GROUPS: dict[str, dict] = {
    "dashboard": {"label_ar": "لوحة التحكم",    "label_en": "Dashboard",      "perms": ["dashboard.view"]},
    "tickets":   {"label_ar": "التذاكر",         "label_en": "Tickets",        "perms": ["tickets.view", "tickets.create", "tickets.edit", "tickets.delete"]},
    "supervisor":{"label_ar": "المشرف",          "label_en": "Supervisor",     "perms": ["supervisor.view", "supervisor.team"]},
    "manager":   {"label_ar": "المدير",          "label_en": "Manager",        "perms": ["manager.view", "manager.settings"]},
    "admin":     {"label_ar": "الإدارة",         "label_en": "Admin",          "perms": ["admin.view"]},
    "kb":        {"label_ar": "قاعدة المعرفة",   "label_en": "Knowledge Base", "perms": ["kb.view", "kb.edit"]},
    "reports":   {"label_ar": "التقارير",         "label_en": "Reports",        "perms": ["reports.view"]},
}

_PERM_LABELS: dict[str, dict[str, str]] = {
    "dashboard.view":  {"ar": "عرض لوحة التحكم",       "en": "View Dashboard"},
    "tickets.view":    {"ar": "عرض التذاكر",            "en": "View Tickets"},
    "tickets.create":  {"ar": "إنشاء تذاكر",            "en": "Create Tickets"},
    "tickets.edit":    {"ar": "تعديل التذاكر",           "en": "Edit Tickets"},
    "tickets.delete":  {"ar": "حذف التذاكر",            "en": "Delete Tickets"},
    "supervisor.view": {"ar": "عرض لوحة المشرف",        "en": "View Supervisor Panel"},
    "supervisor.team": {"ar": "إدارة فريق المشرف",      "en": "Manage Supervisor Team"},
    "manager.view":    {"ar": "عرض لوحة المدير",        "en": "View Manager Panel"},
    "manager.settings":{"ar": "إعدادات المدير",         "en": "Manager Settings"},
    "admin.view":      {"ar": "عرض لوحة الإدارة",       "en": "View Admin Panel"},
    "kb.view":         {"ar": "عرض قاعدة المعرفة",      "en": "View Knowledge Base"},
    "kb.edit":         {"ar": "تعديل قاعدة المعرفة",     "en": "Edit Knowledge Base"},
    "reports.view":    {"ar": "عرض التقارير",            "en": "View Reports"},
}


@router.get("/manager/permissions", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.settings"))])
async def manager_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Permissions management page for manager+."""
    from app.models.permission import RolePermission
    import json as _json

    lang = getattr(request.state, "lang", "ar")

    # Load DB overrides
    db_perms = list((await db.execute(select(RolePermission))).scalars().all())
    db_map: dict[str, dict[str, bool]] = {}
    for rp in db_perms:
        db_map.setdefault(rp.permission_key, {})[rp.role] = rp.is_granted

    # Build effective matrix: defaults merged with DB overrides
    effective: dict[str, dict[str, bool]] = {}
    for perm_key, default_roles in _DEFAULT_PERMISSIONS.items():
        effective[perm_key] = {}
        for role in _ALL_ROLES:
            if perm_key in db_map and role in db_map[perm_key]:
                effective[perm_key][role] = db_map[perm_key][role]
            else:
                effective[perm_key][role] = role in default_roles

    groups_json = _json.dumps({
        gid: {
            "label_ar": g["label_ar"], "label_en": g["label_en"],
            "perms": [{
                "key": p,
                "label_ar": _PERM_LABELS.get(p, {}).get("ar", p),
                "label_en": _PERM_LABELS.get(p, {}).get("en", p),
                "roles": {r: effective.get(p, {}).get(r, False) for r in _ALL_ROLES},
            } for p in g["perms"]]
        } for gid, g in _PERMISSION_GROUPS.items()
    }, ensure_ascii=False)

    return templates.TemplateResponse(
        "manager/permissions.html",
        _ctx(request, groups_json=groups_json, roles=_ALL_ROLES),
    )


@router.post("/api/manager/permissions/toggle", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("manager.settings"))])
async def manager_toggle_permission(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from app.models.permission import RolePermission
    from app.core.redis import get_redis_pool

    # Accept both form (HTMX default) and JSON (e.g. when hx-vals is JSON)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
        permission = (body.get("permission") or "").strip()
        role = (body.get("role") or "").strip()
    else:
        form = await request.form()
        permission = (form.get("permission") or "").strip()
        role = (form.get("role") or "").strip()

    if not permission or not role:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="permission and role required")

    role = role.strip().lower()
    permission = permission.strip()

    try:
        result = await db.execute(
            select(RolePermission).where(
                RolePermission.role == role,
                RolePermission.permission_key == permission,
            )
        )
        rp = result.scalar_one_or_none()
        if rp:
            rp.is_granted = not rp.is_granted
        else:
            default_roles = _DEFAULT_PERMISSIONS.get(permission, [])
            is_default = role in default_roles
            rp = RolePermission(id=uuid.uuid4(), role=role, permission_key=permission, is_granted=not is_default)
            db.add(rp)

        await db.commit()
        await db.refresh(rp)

        redis = await get_redis_pool()
        await invalidate_all_permission_caches(redis)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=t("errors.server_error", lang=getattr(request.state, "lang", "ar")),
        ) from e

    checked = "checked" if rp.is_granted else ""
    vals_json = _json.dumps({"permission": permission, "role": role})
    # Attribute in single quotes so JSON double quotes are fine; escape only single quote
    vals_attr = vals_json.replace("'", "&#39;")
    return HTMLResponse(
        f'<input type="checkbox" {checked} '
        f"hx-post=\"/api/manager/permissions/toggle\" "
        f"hx-vals='{vals_attr}' "
        f'hx-target="closest td" hx-swap="innerHTML" '
        f'class="h-4 w-4 rounded cursor-pointer" style="accent-color:#00AEEF;">'
    )


@router.post("/api/manager/permissions/reset",
             dependencies=[Depends(require_permission("manager.settings"))])
async def reset_role_permissions(
    request: Request,
    role: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.permission import RolePermission
    from app.core.redis import get_redis_pool
    from sqlalchemy import delete

    lang = getattr(request.state, "lang", "ar")
    role = (role or "").strip().lower()

    await db.execute(delete(RolePermission).where(RolePermission.role == role))
    await db.commit()

    redis = await get_redis_pool()
    await invalidate_all_permission_caches(redis)

    msg = f"تم إعادة تعيين صلاحيات {role} للافتراضي" if lang == "ar" else f"Reset {role} permissions to default"
    return JSONResponse({"ok": True, "message": msg})


# ── POST /api/manager/users/{id}/force-logout (Manager ONLY) ─────────────

@router.post("/api/manager/users/{user_id}/force-logout", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("manager.view"))])
async def force_logout(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Terminate all active sessions for a user. Manager cannot force-logout admin."""
    from app.models.user import User
    from app.models.user_session import UserSession
    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role not in ("manager", "admin"):
        raise HTTPException(403)

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    target = (await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))).scalar_one_or_none()
    if target and target.role == "admin" and actor_role != "admin":
        raise HTTPException(403, detail="Only admin can force-logout admin users")

    now = datetime.now(tz=UTC)
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == uid,
            UserSession.revoked_at.is_(None),
        )
    )
    sessions = list(result.scalars().all())
    for s in sessions:
        s.revoked_at = now

    from app.core.redis import get_redis_pool
    redis = await get_redis_pool()
    await redis.delete(f"session:{uid}")

    from app.services.audit import log, AuditAction
    await log(db, AuditAction.USER_FORCE_LOGOUT,
        actor_id=uuid.UUID(actor.get("sub", "")),
        resource_type="users",
        resource_id=uid,
        new_value={"sessions_revoked": len(sessions)},
    )
    await db.flush()

    return HTMLResponse(f'<span class="text-xs text-red-600">🔒 {len(sessions)} sessions terminated</span>')


# ── GET /api/manager/cold-storage (Archived tickets >365 days) ────────────

@router.get("/api/manager/cold-storage", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def cold_storage(
    request: Request,
    q: Optional[str] = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Search archived tickets older than 365 days."""
    from app.models.ticket import Ticket

    lang = getattr(request.state, "lang", "ar")
    cutoff = datetime.now(tz=UTC) - timedelta(days=365)
    per_page = 25

    query = (
        select(Ticket)
        .where(Ticket.status == "archived", Ticket.updated_at < cutoff, Ticket.deleted_at.is_(None))
        .order_by(Ticket.created_at.desc())
    )
    if q:
        query = query.where(
            or_(
                Ticket.ticket_number.ilike(f"%{q}%"),
                Ticket.subject.ilike(f"%{q}%"),
                Ticket.submitter_name.ilike(f"%{q}%"),
            )
        )
    result = await db.execute(query.limit(per_page).offset((page - 1) * per_page))
    tickets = list(result.scalars().all())

    rows = "".join(
        f'<tr><td class="text-xs" style="color:#00AEEF;"><a href="/tickets/{t.id}" class="hover:underline font-mono">{t.ticket_number}</a></td>'
        f'<td class="text-xs" style="color:var(--text-muted);">{t.subject or "—"}</td>'
        f'<td class="text-xs" style="color:var(--text-faint);">{t.created_at.strftime("%Y-%m-%d") if t.created_at else "—"}</td></tr>'
        for t in tickets
    )
    if not rows:
        rows = f'<tr><td colspan="3" class="text-center py-6 text-xs" style="color:var(--text-faint);">{"لا توجد نتائج" if lang == "ar" else "No results"}</td></tr>'

    return HTMLResponse(f'<table class="data-table"><thead><tr><th>#</th><th>Subject</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table>')


# ── Cron expression from frequency ───────────────────────────────────────────

def _cron_for_frequency(frequency: str) -> str:
    if frequency == "daily":
        return "0 7 * * *"
    if frequency == "weekly":
        return "0 7 * * 0"
    if frequency == "monthly":
        return "0 7 1 * *"
    return "0 7 * * 0"


# ── POST /api/manager/scheduled-report ────────────────────────────────────

@router.post("/api/manager/scheduled-report", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("manager.view"))])
async def create_scheduled_report(
    request: Request,
    report_type: str = Form(...),
    frequency: str = Form("weekly"),
    format: str = Form("pdf"),
    language: str = Form("ar"),
    recipients: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Create a scheduled report; each report has its own recipient list."""
    from app.models.report import ScheduledReport
    from app.services.reports import REPORT_TYPES

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}

    if format not in ("pdf", "xlsx"):
        format = "pdf"
    if language not in ("ar", "en"):
        language = "ar"

    email_list = [e.strip() for e in recipients.replace("\n", ",").split(",") if e.strip() and "@" in e.strip()]
    if not email_list:
        raise HTTPException(422, detail="At least one valid email required")

    names = REPORT_TYPES.get(report_type, {"name_ar": report_type, "name_en": report_type})
    name_ar = names.get("name_ar", report_type)
    name_en = names.get("name_en", report_type)

    report = ScheduledReport(
        id=uuid.uuid4(),
        name_ar=name_ar,
        name_en=name_en,
        report_config={"report_type": report_type, "options": {}},
        frequency=frequency,
        cron_expr=_cron_for_frequency(frequency),
        recipients=email_list,
        format=format,
        language=language,
        is_active=True,
        created_by=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
    )
    db.add(report)

    from app.services.audit import log, AuditAction
    await log(db, AuditAction.REPORT_SCHEDULED,
        actor_id=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
        resource_type="scheduled_reports",
        resource_id=report.id,
        new_value={"report_type": report_type, "frequency": frequency, "recipients": email_list},
    )
    await db.commit()

    # Return success message; table refreshes via HX-Trigger
    return HTMLResponse(
        f'<p class="text-sm text-green-600" id="report-result">✅ {t("mgr.scheduled_report_created", lang=lang)}</p>',
        headers={"HX-Trigger": "refreshScheduledReports"},
    )


# ── GET /api/manager/reports/export ───────────────────────────────────────────

@router.get("/api/manager/reports/export",
            dependencies=[Depends(require_permission("manager.view"))])
async def export_report(
    request: Request,
    report_type: str = "kpi_summary",
    period: str = "month",
    format: str = "pdf",
    lang: str = "ar",
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> StreamingResponse:
    """Export report as PDF or XLSX; same page download (Content-Disposition: attachment)."""
    from app.services.reports import (
        REPORT_TYPES,
        gather_report_data,
        build_report_pdf,
        build_report_xlsx,
    )

    if report_type not in REPORT_TYPES and report_type != "kpi_summary":
        report_type = "kpi_summary"
    if period not in ("today", "week", "month"):
        period = "month"
    if format not in ("pdf", "xlsx"):
        format = "pdf"
    if lang not in ("ar", "en"):
        lang = getattr(request.state, "lang", "ar")

    data = await gather_report_data(db, report_type, period, redis)
    names = REPORT_TYPES.get(report_type, {"name_ar": "report", "name_en": "report"})
    safe_name = (names.get("name_en") or report_type).replace(" ", "_").lower()
    date_suffix = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    if format == "pdf":
        body = build_report_pdf(data, report_type, lang)
        if not isinstance(body, bytes):
            body = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        return Response(
            content=body,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}_{date_suffix}.pdf"',
                "Content-Length": str(len(body)),
                "Content-Type": "application/pdf",
            },
        )
    body = build_report_xlsx(data, report_type, lang)
    return StreamingResponse(
        iter([body]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_{date_suffix}.xlsx"',
            "Content-Length": str(len(body)),
        },
    )


def _scheduled_reports_table_html(reports: list, lang: str) -> str:
    """Build the scheduled reports table HTML (shared by GET list and PATCH response)."""
    rows = []
    for r in reports:
        name = r.name_ar if lang == "ar" and r.name_ar else (r.name_en or r.name_ar or str(r.id))
        recips = ", ".join((r.recipients or [])[:3])
        if (r.recipients or []) and len(r.recipients) > 3:
            recips += "…"
        last = r.last_sent_at.strftime("%Y-%m-%d %H:%M") if r.last_sent_at else "—"
        toggle_link = (
            f'<a href="#" class="text-xs text-amber-600 hover:underline" hx-patch="/api/manager/scheduled-reports/{r.id}" '
            f'hx-vals=\'{{"is_active": "false"}}\' hx-target="#scheduled-reports-table" hx-swap="outerHTML" '
            f'hx-trigger="click" hx-push-url="false">'
            f'{t("mgr.deactivate", lang=lang)}</a>'
            if r.is_active
            else
            f'<a href="#" class="text-xs text-green-600 hover:underline" hx-patch="/api/manager/scheduled-reports/{r.id}" '
            f'hx-vals=\'{{"is_active": "true"}}\' hx-target="#scheduled-reports-table" hx-swap="outerHTML" '
            f'hx-trigger="click" hx-push-url="false">'
            f'{t("mgr.activate", lang=lang)}</a>'
        )
        rows.append(
            f'<tr data-report-id="{r.id}">'
            f'<td class="text-sm">{name}</td>'
            f'<td class="text-xs">{r.report_config.get("report_type", "") if isinstance(r.report_config, dict) else ""}</td>'
            f'<td class="text-xs">{r.frequency}</td>'
            f'<td class="text-xs">{r.format}</td>'
            f'<td class="text-xs" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;">{recips}</td>'
            f'<td class="text-xs">{last}</td>'
            f'<td>{toggle_link}</td>'
            f'<td><button type="button" class="text-red-600 hover:underline report-delete" data-id="{r.id}" '
            f'hx-delete="/api/manager/scheduled-reports/{r.id}" hx-target="closest tr" hx-swap="outerHTML swap:1s">'
            f'{t("app.delete", lang=lang)}</button></td>'
            f"</tr>"
        )
    if not rows:
        rows.append(
            f'<tr><td colspan="8" class="text-center py-6 text-sm" style="color:var(--text-faint);">'
            f'{t("mgr.no_scheduled_reports", lang=lang)}</td></tr>'
        )

    table_html = (
        '<table class="w-full border-collapse text-start" id="scheduled-reports-table">'
        "<thead><tr>"
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.report_name", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.report_type", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.frequency", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.report_format", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.report_recipients", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.last_sent", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b">{t("mgr.active", lang=lang)}</th>'
        f'<th class="text-xs font-semibold p-2 border-b"></th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    return table_html


@router.get("/api/manager/scheduled-reports", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def list_scheduled_reports(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Return HTML fragment of scheduled reports table for same-page display."""
    from app.models.report import ScheduledReport

    lang = getattr(request.state, "lang", "ar")
    result = await db.execute(
        select(ScheduledReport).order_by(ScheduledReport.created_at.desc())
    )
    reports = list(result.scalars().all())
    return HTMLResponse(_scheduled_reports_table_html(reports, lang))


# ── PATCH /api/manager/scheduled-reports/{id} ────────────────────────────────

@router.patch("/api/manager/scheduled-reports/{report_id}", response_class=HTMLResponse,
              dependencies=[Depends(require_permission("manager.view"))])
async def update_scheduled_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Toggle is_active (same page). Accepts JSON or form body."""
    from app.models.report import ScheduledReport

    is_active = None
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
            is_active = body.get("is_active")
        except Exception:
            pass
    else:
        form = await request.form()
        is_active = form.get("is_active")

    result = await db.execute(select(ScheduledReport).where(ScheduledReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, detail="Report not found")
    if is_active is not None:
        report.is_active = str(is_active).lower() in ("true", "1", "on", "yes")
    await db.commit()
    # Return updated table so HTMX can replace #scheduled-reports-table
    result = await db.execute(
        select(ScheduledReport).order_by(ScheduledReport.created_at.desc())
    )
    reports = list(result.scalars().all())
    lang = getattr(request.state, "lang", "ar")
    return HTMLResponse(_scheduled_reports_table_html(reports, lang))


# ── DELETE /api/manager/scheduled-reports/{id} (soft) ────────────────────────

@router.delete("/api/manager/scheduled-reports/{report_id}", response_class=HTMLResponse,
               dependencies=[Depends(require_permission("manager.view"))])
async def delete_scheduled_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Soft-delete scheduled report; return empty so row can be removed."""
    from app.models.report import ScheduledReport

    result = await db.execute(select(ScheduledReport).where(ScheduledReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, detail="Report not found")
    await db.delete(report)
    await db.commit()
    return HTMLResponse("")


# ── Form Builder API ────────────────────────────────────────────────────────

@router.get("/api/manager/form-schema",
            dependencies=[Depends(require_permission("manager.view"))])
async def get_active_form_schema(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the active form schema for the builder to preload."""
    from app.models.form import FormVersion

    result = await db.execute(
        select(FormVersion)
        .where(FormVersion.is_active.is_(True), FormVersion.deleted_at.is_(None))
        .order_by(FormVersion.version.desc())
        .limit(1)
    )
    fv = result.scalar_one_or_none()

    # If no published schema, or schema is from old format (no sec_dept), return the built-in defaults.
    _default_schema = _get_portal_default_schema()
    if not fv:
        return JSONResponse({"version": 0, "sections": _default_schema["sections"], "fields": _default_schema["fields"]})

    schema = fv.schema or {}
    published_sections = schema.get("sections", [])
    has_new_structure = any(s.get("id") == "sec_dept" for s in published_sections)
    if not has_new_structure:
        return JSONResponse({"version": fv.version, "version_id": str(fv.id),
                             "sections": _default_schema["sections"], "fields": _default_schema["fields"]})

    return JSONResponse({
        "version": fv.version,
        "version_id": str(fv.id),
        "sections": published_sections,
        "fields": schema.get("fields", []),
        "settings": schema.get("settings", {}),
    })


def _get_portal_default_schema() -> dict:
    """Return the built-in portal form schema (matches initForm() defaults in the portal template)."""
    return {
        "sections": [
            {"id": "sec_dept",    "title_ar": "القسم ونوع المشكلة", "title_en": "Department & Issue"},
            {"id": "sec_contact", "title_ar": "بيانات التواصل",     "title_en": "Contact Info"},
            {"id": "sec_ticket",  "title_ar": "بيانات التذكرة",     "title_en": "Ticket Details"},
        ],
        "fields": [
            {"id": "f_dept", "key": "department", "type": "select",
             "label_ar": "القسم المختص", "label_en": "Department",
             "required": True, "section": "sec_dept", "system": False,
             "options": [
                 {"value": "technical_support",  "label_ar": "الدعم التقني",            "label_en": "Technical Support"},
                 {"value": "user_management",    "label_ar": "إدارة اليوزرات",           "label_en": "User Management"},
                 {"value": "device_activation",  "label_ar": "التفعيل الخاطئ للأجهزة", "label_en": "Device Activation Error"},
                 {"value": "absher",             "label_ar": "أبشر",                    "label_en": "Absher"},
             ]},
            # Technical Support
            {"id": "f_ts_pt", "key": "ts_problem_type", "type": "select",
             "label_ar": "نوع المشكلة", "label_en": "Problem Type",
             "required": True, "section": "sec_dept", "system": False,
             "conditions": [{"field": "department", "operator": "equals", "value": "technical_support"}],
             "options": [
                 {"value": "fingerprint",        "label_ar": "بصمة",          "label_en": "Fingerprint"},
                 {"value": "package_change",     "label_ar": "تغيير الباقة",  "label_en": "Package Change"},
                 {"value": "new_activation",     "label_ar": "تفعيل جديد",    "label_en": "New Activation"},
                 {"value": "ownership_transfer", "label_ar": "نقل ملكية",     "label_en": "Ownership Transfer"},
                 {"value": "other",              "label_ar": "أخرى",           "label_en": "Other"},
             ]},
            {"id": "f_ts_err", "key": "ts_error_number", "type": "text",
             "label_ar": "رقم الخطأ", "label_en": "Error Number",
             "placeholder_ar": "أدخل رقم الخطأ", "placeholder_en": "Enter error number",
             "required": True, "section": "sec_dept", "system": False, "half_width": True, "dir": "ltr",
             "conditions": [
                 {"field": "department", "operator": "equals", "value": "technical_support"},
                 {"field": "ts_problem_type", "operator": "equals", "value": "fingerprint"},
             ]},
            # User Management
            {"id": "f_um_pt", "key": "um_problem_type", "type": "select",
             "label_ar": "نوع المشكلة", "label_en": "Problem Type",
             "required": True, "section": "sec_dept", "system": False,
             "conditions": [{"field": "department", "operator": "equals", "value": "user_management"}],
             "options": [
                 {"value": "fingerprint_error", "label_ar": "خطأ بصمة",            "label_en": "Fingerprint Error"},
                 {"value": "reader",            "label_ar": "قارئ البصمة",          "label_en": "Fingerprint Reader"},
                 {"value": "system_access",     "label_ar": "مشكلة دخول لنظام",    "label_en": "System Access Issue"},
                 {"value": "user_auth",         "label_ar": "مشكلة توثيق اليوزر",  "label_en": "User Auth Issue"},
                 {"value": "other",             "label_ar": "أخرى",                 "label_en": "Other"},
             ]},
            {"id": "f_um_err", "key": "um_error_number", "type": "text",
             "label_ar": "رقم الخطأ", "label_en": "Error Number",
             "placeholder_ar": "أدخل رقم الخطأ", "placeholder_en": "Enter error number",
             "required": True, "section": "sec_dept", "system": False, "half_width": True, "dir": "ltr",
             "conditions": [
                 {"field": "department", "operator": "equals", "value": "user_management"},
                 {"field": "um_problem_type", "operator": "equals", "value": "fingerprint_error"},
             ]},
            {"id": "f_um_rd", "key": "um_reader_number", "type": "text",
             "label_ar": "رقم القارئ", "label_en": "Reader Number",
             "placeholder_ar": "أدخل رقم القارئ", "placeholder_en": "Enter reader number",
             "required": True, "section": "sec_dept", "system": False, "half_width": True, "dir": "ltr",
             "conditions": [
                 {"field": "department", "operator": "equals", "value": "user_management"},
                 {"field": "um_problem_type", "operator": "equals", "value": "reader"},
             ]},
            # Device Activation
            {"id": "f_dev_pt", "key": "device_problem_type", "type": "select",
             "label_ar": "نوع المشكلة", "label_en": "Problem Type",
             "required": True, "section": "sec_dept", "system": False,
             "conditions": [{"field": "department", "operator": "equals", "value": "device_activation"}],
             "options": [
                 {"value": "mobile", "label_ar": "تفعيل جوال بالخطأ",  "label_en": "Wrong Mobile Activation"},
                 {"value": "router", "label_ar": "تفعيل راوتر بالخطأ", "label_en": "Wrong Router Activation"},
             ]},
            {"id": "f_dev_num", "key": "device_number", "type": "text",
             "label_ar": "رقم الجهاز", "label_en": "Device Number",
             "placeholder_ar": "أدخل رقم الجهاز", "placeholder_en": "Enter device number",
             "required": True, "section": "sec_dept", "system": False, "half_width": True, "dir": "ltr",
             "conditions": [{"field": "department", "operator": "equals", "value": "device_activation"}]},
            {"id": "f_dev_type", "key": "activation_type", "type": "radio",
             "label_ar": "هل تم التفعيل بعرض أم كاش؟", "label_en": "Activation Type",
             "required": True, "section": "sec_dept", "system": False,
             "conditions": [{"field": "department", "operator": "equals", "value": "device_activation"}],
             "options": [
                 {"value": "display", "label_ar": "بعرض", "label_en": "Display"},
                 {"value": "cash",    "label_ar": "كاش",  "label_en": "Cash"},
             ]},
            # Absher
            {"id": "f_ab_pt", "key": "absher_problem_type", "type": "select",
             "label_ar": "نوع المشكلة", "label_en": "Problem Type",
             "required": True, "section": "sec_dept", "system": False,
             "conditions": [{"field": "department", "operator": "equals", "value": "absher"}],
             "options": [
                 {"value": "absher_app",        "label_ar": "مشكلة تطبيق أبشر",    "label_en": "Absher App Issue"},
                 {"value": "fingerprint_reader","label_ar": "مشكلة قارئ البصمة",   "label_en": "Fingerprint Reader Issue"},
                 {"value": "tablet_issue",      "label_ar": "مشكلة التابلت",        "label_en": "Tablet Issue"},
                 {"value": "charger_issue",     "label_ar": "مشكلة شاحن التابلت",   "label_en": "Tablet Charger Issue"},
             ]},
            {"id": "f_ab_tab", "key": "absher_tablet_number", "type": "text",
             "label_ar": "رقم التابلت", "label_en": "Tablet Number",
             "placeholder_ar": "أدخل رقم التابلت", "placeholder_en": "Enter tablet number",
             "required": True, "section": "sec_dept", "system": False, "half_width": True, "dir": "ltr",
             "conditions": [{"field": "department", "operator": "equals", "value": "absher"}]},
            # Contact Info
            {"id": "f_ct_phone", "key": "contact_phone", "type": "tel",
             "label_ar": "رقم الجوال", "label_en": "Phone Number",
             "placeholder_ar": "05XXXXXXXX", "placeholder_en": "05XXXXXXXX",
             "required": True, "section": "sec_contact", "system": False, "half_width": True, "dir": "ltr"},
            {"id": "f_ct_name", "key": "contact_name", "type": "text",
             "label_ar": "الاسم", "label_en": "Name",
             "placeholder_ar": "اسم الشخص المعني", "placeholder_en": "Contact person name",
             "required": True, "section": "sec_contact", "system": False, "half_width": True},
            # Ticket details
            {"id": "f_cust", "key": "customer_number", "type": "text",
             "label_ar": "رقم العميل / رقم الحساب", "label_en": "Customer / Account Number",
             "placeholder_ar": "أدخل رقم العميل", "placeholder_en": "Enter customer number",
             "required": False, "required_when": {"field": "department", "equals": "technical_support"},
             "section": "sec_ticket", "system": False, "half_width": True, "dir": "ltr"},
            {"id": "f_subj", "key": "subject", "type": "text",
             "label_ar": "عنوان المشكلة", "label_en": "Issue Title",
             "placeholder_ar": "عنوان مختصر للمشكلة", "placeholder_en": "Brief issue title",
             "required": True, "section": "sec_ticket", "system": True, "half_width": True},
            {"id": "f_desc", "key": "description", "type": "textarea",
             "label_ar": "وصف المشكلة", "label_en": "Problem Description",
             "placeholder_ar": "اشرح المشكلة بالتفصيل...", "placeholder_en": "Describe the issue in detail...",
             "required": True, "section": "sec_ticket", "system": True, "min_length": 10},
        ],
    }


@router.post("/api/manager/form-version",
             dependencies=[Depends(require_permission("manager.settings"))])
async def save_form_version(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Publish a new form version with full schema (sections, fields, conditions)."""
    from app.models.form import FormVersion
    import json

    lang  = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "message": "Invalid JSON"}, status_code=400)

    sections = body.get("sections", [])
    fields   = body.get("fields", [])
    settings = body.get("settings", {})

    if not isinstance(fields, list):
        return JSONResponse({"ok": False, "message": "fields must be a list"}, status_code=400)

    try:
        actor_id = uuid.UUID(actor.get("sub", ""))
    except (ValueError, AttributeError):
        actor_id = None

    try:
        from sqlalchemy import func as sqlfunc
        max_ver = (await db.execute(select(sqlfunc.max(FormVersion.version)))).scalar() or 0

        await db.execute(
            FormVersion.__table__.update().values(is_active=False).where(
                FormVersion.deleted_at.is_(None)
            )
        )

        fv = FormVersion(
            id=uuid.uuid4(),
            version=max_ver + 1,
            schema={"sections": sections, "fields": fields, "settings": settings},
            is_active=True,
            published_by=actor_id,
        )
        db.add(fv)
        await db.commit()
        return JSONResponse({
            "ok": True,
            "version": fv.version,
            "message": f"{'تم النشر بنجاح — الإصدار' if lang == 'ar' else 'Published — Version'} {fv.version}",
        })
    except Exception as exc:
        await db.rollback()
        return JSONResponse({"ok": False, "message": str(exc)[:200]}, status_code=500)


@router.get("/api/manager/form-versions",
            dependencies=[Depends(require_permission("manager.view"))])
async def list_form_versions(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List recent form versions for history/rollback."""
    from app.models.form import FormVersion

    result = await db.execute(
        select(FormVersion)
        .where(FormVersion.deleted_at.is_(None))
        .order_by(FormVersion.version.desc())
        .limit(15)
    )
    versions = []
    for fv in result.scalars().all():
        schema = fv.schema or {}
        versions.append({
            "id": str(fv.id),
            "version": fv.version,
            "is_active": fv.is_active,
            "fields_count": len(schema.get("fields", [])),
            "sections_count": len(schema.get("sections", [])),
            "created_at": fv.created_at.isoformat() if fv.created_at else None,
        })
    return JSONResponse({"versions": versions})


@router.post("/api/manager/form-versions/{version_id}/activate",
             dependencies=[Depends(require_permission("manager.settings"))])
async def activate_form_version(
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Activate a specific form version (rollback)."""
    from app.models.form import FormVersion
    lang = getattr(request.state, "lang", "ar")

    try:
        vid = uuid.UUID(version_id)
    except ValueError:
        return JSONResponse({"ok": False}, status_code=400)

    result = await db.execute(select(FormVersion).where(FormVersion.id == vid))
    fv = result.scalar_one_or_none()
    if not fv:
        return JSONResponse({"ok": False}, status_code=404)

    await db.execute(
        FormVersion.__table__.update().values(is_active=False).where(
            FormVersion.deleted_at.is_(None)
        )
    )
    fv.is_active = True
    await db.commit()

    return JSONResponse({
        "ok": True,
        "message": f"{'تم تفعيل الإصدار' if lang == 'ar' else 'Activated version'} {fv.version}",
    })


# ── GET /manager/call-logs ─────────────────────────────────────────────────────

@router.get("/manager/call-logs", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.settings"))])
async def manager_call_logs(
    request: Request,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> HTMLResponse:
    from app.models.call_log import CallLog
    from app.models.user import User

    lang = getattr(request.state, "lang", "ar")
    page_size = 30
    offset = (page - 1) * page_size

    total = await db.scalar(select(func.count(CallLog.id))) or 0
    rows = list((await db.execute(
        select(CallLog).order_by(CallLog.created_at.desc())
        .limit(page_size).offset(offset)
    )).scalars().all())

    # Enrich with user data
    logs = []
    for r in rows:
        agent = await db.get(User, r.agent_id)
        caller = await db.get(User, r.caller_user_id) if r.caller_user_id else None
        logs.append({
            "id": str(r.id),
            "agent": (agent.full_name_ar if lang == "ar" else (agent.full_name_en or agent.full_name_ar)) if agent else "—",
            "caller": (caller.full_name_ar if lang == "ar" else (caller.full_name_en or caller.full_name_ar)) if caller else "—",
            "outcome": r.outcome or "—",
            "reason_data": r.reason_data or {},
            "notes": r.notes or "",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        })

    from app.api.dashboard import _get_call_reason_fields
    fields = await _get_call_reason_fields(redis)

    ctx = _ctx(request,
               logs=logs, total=total, page=page, page_size=page_size,
               total_pages=max(1, -(-total // page_size)),
               fields=fields)
    return templates.TemplateResponse("manager/call_logs.html", ctx)
