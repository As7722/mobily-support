"""
Manager Dashboard + Settings + Analytics + Tickets Routes
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission
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


# ── GET /manager ───────────────────────────────────────────────────────────────

@router.get("/manager", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_dashboard(
    request: Request,
    period: str = "today",
    db: AsyncSession = Depends(get_db),
    redis=None,
) -> HTMLResponse:
    from app.core.redis import get_redis
    kpis      = await get_manager_kpis(db, redis, period)
    violations = await get_sla_violations(db, limit=5)
    queue     = await get_smart_queue(db, role="manager", per_page=10)

    return templates.TemplateResponse(
        "manager/index.html",
        _ctx(request, kpis=kpis, violations=violations, queue=queue, period=period),
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

@router.get("/manager/users", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Manager-only user management page: full user CRUD + department assignment."""
    from app.models.user import User
    from app.models.department import Department, UserDepartment

    users = list((await db.execute(
        select(User).where(User.deleted_at.is_(None))
        .options(selectinload(User.department))
        .order_by(User.role, User.full_name_ar)
    )).scalars().all())

    departments = list((await db.execute(
        select(Department).where(Department.deleted_at.is_(None), Department.is_active.is_(True))
        .order_by(Department.name_ar)
    )).scalars().all())

    # Load user→departments mapping
    all_ud = list((await db.execute(select(UserDepartment))).all())
    user_dept_map: dict[str, list[str]] = {}
    for ud in all_ud:
        uid_str = str(ud.user_id)
        did_str = str(ud.department_id)
        user_dept_map.setdefault(uid_str, []).append(did_str)

    return templates.TemplateResponse(
        "manager/users.html",
        _ctx(request, users=users, departments=departments, user_dept_map=user_dept_map,
             current_role=(getattr(request.state, "user", {}) or {}).get("role", "")),
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

    audit_logs = list((await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)
    )).scalars().all())

    notif_rules = list((await db.execute(
        select(NotificationRule).order_by(NotificationRule.event_type)
    )).scalars().all())

    # Call reason fields from Redis (multi-field format)
    from app.api.dashboard import _get_call_reason_fields
    call_reason_cfg = {"fields": await _get_call_reason_fields(redis)}

    return templates.TemplateResponse(
        "manager/settings.html",
        _ctx(
            request,
            active_tab=tab,
            form_versions=form_versions,
            active_form_schema=active_form_schema,
            sla_policies=sla_policies,
            automation_rules=automation_rules,
            audit_logs=audit_logs,
            notif_rules=notif_rules,
            call_reason_cfg=call_reason_cfg,
        ),
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
        db.add(AuditLog(
            id=uuid.uuid4(),
            table_name="sla_policies",
            record_id=policy.id,
            action="update" if policy_id else "create",
            changed_by=uuid.UUID(actor_id_str) if actor_id_str else None,
            created_at=now,
        ))

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

@router.get("/manager/analytics", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def manager_analytics(
    request: Request,
    period: str = "month",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from app.models.ticket import Ticket
    from app.models.user import User
    from app.models.category import Category

    lang = getattr(request.state, "lang", "ar")
    kpis = await get_manager_kpis(db, None, period)

    # ── Top agents (scoped to period) ──────────────────────────────────────
    from app.services.kpi import _period_range
    p_start, p_end = _period_range(period)
    agents_q = await db.execute(
        select(
            User.id,
            User.full_name_ar,
            User.full_name_en,
            func.count(Ticket.id).label("resolved"),
            func.avg(Ticket.csat_score).label("csat"),
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
            "name_ar": r.full_name_ar or "—",
            "name_en": r.full_name_en or r.full_name_ar or "—",
            "resolved": r.resolved,
            "csat": round(float(r.csat or 0), 1),
            "pct": int(r.resolved / max(max_resolved, 1) * 100),
        })()
        for r in top_agents_raw
    ]

    # ── Peak-hour heatmap (real data from DB) ──────────────────────────────
    from sqlalchemy import extract
    from app.services.kpi import _period_range as _pr
    # Use last-30-days heatmap data for meaningful volume
    from datetime import timedelta as _td
    heat_start = datetime.now(tz=UTC) - _td(days=30)
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
    # dow: 0=Sunday … 6=Saturday; show Sun–Thu (workdays)
    day_names_ar = {0: "الأحد", 1: "الاثنين", 2: "الثلاثاء", 3: "الأربعاء", 4: "الخميس"}
    day_names_en = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu"}
    day_names = day_names_ar if lang == "ar" else day_names_en
    # Build a dict (dow, hr) → count
    heat_map_dict: dict[tuple[int, int], int] = {}
    for row in heat_rows:
        heat_map_dict[(int(row.dow), int(row.hr))] = row.cnt
    heatmap = [
        {
            "day": day_names[d],
            "hours": [heat_map_dict.get((d, h), 0) for h in range(8, 18)],
        }
        for d in range(5)
    ]
    heatmap_max = max((v for row in heatmap for v in row["hours"]), default=1) or 1

    # ── KB gap analysis: categories with tickets but NO KB articles ────────
    from app.models.knowledge import KnowledgeArticle
    from sqlalchemy import exists as sa_exists

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
        .where(
            Ticket.deleted_at.is_(None),
            ~sa_exists(kb_subq),
        )
        .group_by(Category.id, Category.name_ar, Category.name_en)
        .having(func.count(Ticket.id) > 0)
        .order_by(func.count(Ticket.id).desc())
        .limit(10)
    )
    kb_gaps = [
        {"topic": r.name_ar, "topic_en": r.name_en, "count": r.cnt}
        for r in cats_q.all()
    ]

    # ── analytics_json for ApexCharts ─────────────────────────────────────
    trend = kpis.get("trend", [])
    channel_breakdown = kpis.get("channel_breakdown", {})
    analytics_json = {
        "trend_dates":     [d["date"] for d in trend],
        "trend_resolved":  [d["resolved"] for d in trend],
        "trend_submitted": [d["created"] for d in trend],
        "channel_counts": [
            channel_breakdown.get("portal", 0),
            channel_breakdown.get("whatsapp", 0),
            channel_breakdown.get("email", 0),
            channel_breakdown.get("phone", 0),
        ],
        "channel_labels": ["Portal", "WhatsApp", "Email", "Phone"],
    }

    # ── Build KPI display object (correct field mapping) ──────────────────
    avg_mins = kpis.get("avg_resolution_mins", 0) or 0
    avg_res_display = (
        f"{round(avg_mins / 60, 1)}h" if avg_mins >= 60
        else f"{avg_mins}m"
    )
    avg_csat_val = kpis.get("avg_csat") or 0

    kpis_obj = type("K", (), {
        "total":              kpis.get("total_tickets", 0),
        "total_tickets":      kpis.get("total_tickets", 0),
        "resolved":           kpis.get("resolved_tickets", 0),
        "resolved_tickets":   kpis.get("resolved_tickets", 0),
        "sla_pct":            kpis.get("sla_compliance_pct", 0),
        "sla_compliance_pct": kpis.get("sla_compliance_pct", 0),
        "avg_resolution":     avg_res_display,
        "avg_resolution_mins": kpis.get("avg_resolution_mins", 0) or 0,
        "csat":               round(float(avg_csat_val), 1),
        "fcr_pct":            kpis.get("fcr_pct", 0),
        "reopen_pct":         kpis.get("reopen_pct", 0),
        "open_count":         kpis.get("open_tickets", 0),
        "channel_breakdown":  channel_breakdown,
        "total_change": None, "resolved_change": None, "sla_change": None,
        "resolution_change": None, "res_change": None,
        "csat_change": None,  "fcr_change": None, "reopen_change": None,
    })()

    peak_hours = [
        {"hour": h, "count": heat_map_dict.get((d, h), 0)}
        for h in range(8, 18)
        for d in range(5)
    ]
    peak_hours_agg: list[dict] = []
    for h in range(8, 18):
        total = sum(heat_map_dict.get((d, h), 0) for d in range(5))
        peak_hours_agg.append({"hour": f"{h}:00", "count": total})

    return templates.TemplateResponse(
        "manager/analytics.html",
        _ctx(
            request,
            period=period,
            kpis=kpis_obj,
            top_agents=top_agents,
            heatmap=heatmap,
            heatmap_max=heatmap_max,
            kb_gaps=kb_gaps,
            analytics_json=analytics_json,
            trend=trend,
            peak_hours=peak_hours_agg,
        ),
    )


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
    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}
    if actor.get("role") not in ("manager", "admin"):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

    old_dept = str(user.department_id) if user.department_id else None
    new_dept = uuid.UUID(department_id) if department_id and department_id.strip() else None
    user.department_id = new_dept
    user.updated_at = datetime.now(tz=UTC)

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_id=uuid.UUID(actor.get("sub", "")),
        action="user.department_changed",
        target_type="user",
        target_id=uid,
        changes={"from": old_dept, "to": str(new_dept) if new_dept else None},
    ))
    await db.flush()

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
    for field in ("name_ar", "name_en", "code"):
        val = body.get(field)
        if val is not None:
            setattr(dept, field, val.strip() if isinstance(val, str) else val)
    dept.updated_at = datetime.now(tz=UTC)
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

    dept.is_active = not dept.is_active
    dept.updated_at = datetime.now(tz=UTC)
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
    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}
    if actor.get("role") not in ("manager", "admin"):
        raise HTTPException(403)

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    body = await request.json()
    dept_ids = body.get("department_ids", [])

    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

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

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_id=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
        action="user.departments_changed",
        target_type="user",
        target_id=uid,
        changes={"departments": dept_ids},
    ))
    await db.flush()

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
    if role == "admin" and actor.get("role") != "admin":
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
    if user.role == "admin" and actor.get("role") != "admin":
        raise HTTPException(403, detail="Only admin can edit admin users")

    body = await request.json()
    for field in ("full_name_ar", "full_name_en", "email", "phone", "employee_id"):
        val = body.get(field)
        if val is not None:
            setattr(user, field, val.strip() if isinstance(val, str) else val)

    user.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/manager/users/{user_id}/change-role",
             dependencies=[Depends(require_permission("manager.settings"))])
async def change_user_role(
    user_id: str, request: Request, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User
    from app.models.audit import AuditLog

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

    body = await request.json()
    new_role = (body.get("role") or "").strip()
    if new_role not in ("employee", "supervisor", "manager", "admin"):
        raise HTTPException(422, detail="Invalid role")

    actor = getattr(request.state, "user", {}) or {}
    result = await db.execute(select(User).where(User.id == uid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)

    if user.role == "admin" and actor.get("role") != "admin":
        raise HTTPException(403, detail="Only admin can change admin users")
    if new_role == "admin" and actor.get("role") != "admin":
        raise HTTPException(403, detail="Only admin can promote to admin")

    old_role = user.role
    user.role = new_role
    user.updated_at = datetime.now(tz=UTC)

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_id=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
        action="user.role_changed",
        target_type="user",
        target_id=uid,
        changes={"from": old_role, "to": new_role},
    ))
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
    if user.role == "admin" and actor.get("role") != "admin":
        raise HTTPException(403, detail="Only admin can modify admin users")

    user.is_active = not user.is_active
    user.updated_at = datetime.now(tz=UTC)
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
    if user.role == "admin" and actor.get("role") != "admin":
        raise HTTPException(403, detail="Only admin can modify admin users")

    user.password_hash = hash_password(new_pass)
    user.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSIONS MANAGEMENT (Manager+)
# ══════════════════════════════════════════════════════════════════════════════

_ALL_ROLES = ["employee", "supervisor", "manager", "admin"]

_DEFAULT_PERMISSIONS: dict[str, list[str]] = {
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
    permission: str = Form(...),
    role: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.permission import RolePermission
    from app.core.permissions import invalidate_permission_cache
    from app.core.redis import get_redis_pool

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

    redis = await get_redis_pool()
    await invalidate_permission_cache(role, redis)

    checked = "checked" if rp.is_granted else ""
    return HTMLResponse(
        f'<input type="checkbox" {checked} '
        f'hx-post="/api/manager/permissions/toggle" '
        f'hx-vals=\'{{"permission":"{permission}","role":"{role}"}}\' '
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
    from app.core.permissions import invalidate_permission_cache
    from app.core.redis import get_redis_pool
    from sqlalchemy import delete

    lang = getattr(request.state, "lang", "ar")

    await db.execute(delete(RolePermission).where(RolePermission.role == role))
    await db.commit()

    redis = await get_redis_pool()
    await invalidate_permission_cache(role, redis)

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
    """Terminate all active sessions for a user."""
    from app.models.user_session import UserSession
    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}
    if actor.get("role") not in ("manager", "admin"):
        raise HTTPException(403)

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400)

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

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_id=uuid.UUID(actor.get("sub", "")),
        action="user.force_logout",
        target_type="user",
        target_id=uid,
        changes={"sessions_revoked": len(sessions)},
    ))
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


# ── POST /api/manager/scheduled-report ────────────────────────────────────

@router.post("/api/manager/scheduled-report", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("manager.view"))])
async def create_scheduled_report(
    request: Request,
    report_type: str = Form(...),
    frequency: str = Form("weekly"),
    recipients: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Create a scheduled report with any valid email recipients."""
    from app.models.report import ScheduledReport
    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}

    email_list = [e.strip() for e in recipients.split(",") if "@" in e.strip()]
    if not email_list:
        raise HTTPException(422, detail="At least one valid email required")

    report = ScheduledReport(
        id=uuid.uuid4(),
        name=f"{report_type}_{frequency}",
        report_type=report_type,
        frequency=frequency,
        recipients=email_list,
        created_by=uuid.UUID(actor.get("sub", "")),
        is_active=True,
    )
    db.add(report)

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_id=uuid.UUID(actor.get("sub", "")),
        action="report.scheduled",
        target_type="scheduled_report",
        target_id=report.id,
        changes={"type": report_type, "frequency": frequency, "recipients": email_list},
    ))
    await db.flush()

    return HTMLResponse(f'<p class="text-sm text-green-600">✅ {"تم الجدولة" if lang == "ar" else "Scheduled"}</p>')


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
