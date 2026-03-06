"""
Supervisor Dashboard Routes
"""
from __future__ import annotations

import io
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.redis import get_redis
from app.core.templates import templates
from app.i18n import t
from app.services.kpi import get_sla_violations, get_team_workload
from app.services.queue import auto_balance, get_smart_queue

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


def _get_dept_id(request: Request) -> Optional[uuid.UUID]:
    user = getattr(request.state, "user", {}) or {}
    dept = user.get("department_id")
    try:
        return uuid.UUID(dept) if dept else None
    except ValueError:
        return None


# ── GET /supervisor ────────────────────────────────────────────────────────────

@router.get("/supervisor", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("supervisor.view"))])
async def supervisor_dashboard(
    request: Request,
    tab: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    active_tab = (tab or "overview").strip() or "overview"
    if active_tab not in ("overview", ""):
        return RedirectResponse(url=f"/supervisor/{active_tab}", status_code=302)

    from sqlalchemy import func, select as _select
    from app.models.ticket import Ticket as _Ticket

    from app.models.branch import Branch
    from app.models.department import Department

    dept_id   = _get_dept_id(request)
    workload  = await get_team_workload(db, dept_id)
    violations = await get_sla_violations(db, dept_id, limit=20)
    queue     = await get_smart_queue(db, role="supervisor", per_page=15)

    branches = list((await db.execute(
        select(Branch).where(Branch.deleted_at.is_(None)).order_by(Branch.name_ar)
    )).scalars().all())

    spec_departments = list((await db.execute(
        select(Department).where(
            Department.is_active.is_(True),
            Department.deleted_at.is_(None),
            Department.code != "technical_support",
        ).order_by(Department.name_ar)
    )).scalars().all())

    summary = {
        "agents_online":     sum(1 for r in workload if r.get("is_online")),
        "total_agents":      len(workload),
        "active_tickets":    sum(r.get("active_tickets", 0) for r in workload),
        "resolved_today":    sum(r.get("resolved_today", 0) for r in workload),
        "sla_breaches":      sum(r.get("sla_breaches", 0) for r in workload),
        "violations_count":  len(violations),
    }

    return templates.TemplateResponse(
        "supervisor/hub.html",
        _ctx(request, active_tab="overview", workload=workload, violations=violations, queue=queue,
             summary=summary, branches=branches, spec_departments=spec_departments),
    )


# ── GET /api/supervisor/workload (HTMX / SSE partial) ─────────────────────────

@router.get("/api/supervisor/workload", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("supervisor.view"))])
async def workload_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    dept_id  = _get_dept_id(request)
    workload = await get_team_workload(db, dept_id)
    lang     = getattr(request.state, "lang", "ar")
    return templates.TemplateResponse(
        "supervisor/_workload_rows.html",
        {"request": request, "lang": lang, "workload": workload, "t": t},
    )


# ── POST /api/supervisor/auto-balance ─────────────────────────────────────────

@router.post("/api/supervisor/auto-balance",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def auto_balance_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user = getattr(request.state, "user", {}) or {}
    lang = getattr(request.state, "lang", "ar")
    try:
        sup_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    dept_id = _get_dept_id(request)
    async with db.begin():
        count = await auto_balance(db, dept_id, sup_id)

    return JSONResponse({"ok": True, "reassigned": count, "message": t("sup.auto_balance_done", lang=lang)})


# ── GET /supervisor/team ───────────────────────────────────────────────────────

@router.get("/supervisor/team", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("supervisor.team"))])
async def team_management(
    request: Request,
    tab: str = "agents",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from sqlalchemy import func
    from app.models.user import User
    from app.models.branch import Branch, BranchEmployee
    from app.models.ticket import Ticket

    dept_id = _get_dept_id(request)

    agents_q = select(User).where(User.is_active.is_(True), User.role == "employee", User.deleted_at.is_(None))
    if dept_id:
        agents_q = agents_q.where(User.department_id == dept_id)
    agents = list((await db.execute(agents_q.order_by(User.full_name_ar))).scalars().all())

    # Fast aggregate query: employee counts per branch
    emp_counts_q = await db.execute(
        select(BranchEmployee.branch_id, func.count(BranchEmployee.id).label("cnt"))
        .where(BranchEmployee.deleted_at.is_(None))
        .group_by(BranchEmployee.branch_id)
    )
    emp_counts = {str(row.branch_id): row.cnt for row in emp_counts_q.all()}

    total_branches_q = await db.execute(
        select(func.count(Branch.id)).where(Branch.deleted_at.is_(None))
    )
    total_branches = total_branches_q.scalar() or 0
    active_branches_q = await db.execute(
        select(func.count(Branch.id)).where(Branch.deleted_at.is_(None), Branch.is_active.is_(True))
    )
    active_branches = active_branches_q.scalar() or 0
    total_emp = sum(emp_counts.values())

    ticket_count_result = await db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.branch_id.isnot(None), Ticket.deleted_at.is_(None)
        )
    )
    branch_tickets = ticket_count_result.scalar() or 0

    # Only fetch first 50 for initial SSR; rest fetched client-side via API
    branches_first_page = list((await db.execute(
        select(Branch).where(Branch.deleted_at.is_(None)).order_by(Branch.name_ar).limit(50)
    )).scalars().all())

    regions_q = await db.execute(
        select(Branch.region_ar).where(Branch.deleted_at.is_(None), Branch.region_ar.isnot(None)).distinct()
    )
    regions = sorted(r[0] for r in regions_q.all() if r[0])
    cities_q = await db.execute(
        select(Branch.city_ar).where(Branch.deleted_at.is_(None), Branch.city_ar.isnot(None)).distinct()
    )
    cities = sorted(c[0] for c in cities_q.all() if c[0])

    branches_json = _json.dumps([{
        "id": str(b.id), "name_ar": b.name_ar, "name_en": b.name_en or b.name_ar,
        "code": b.code, "city_ar": b.city_ar or "", "city_en": b.city_en or "",
        "region_ar": b.region_ar or "", "region_en": b.region_en or "",
        "phone": b.phone or "", "email": b.email or "",
        "internal_notes": b.internal_notes or "", "is_active": b.is_active,
        "employee_count": emp_counts.get(str(b.id), 0),
    } for b in branches_first_page], ensure_ascii=False)

    branch_stats = {
        "total_branches": total_branches,
        "active_branches": active_branches,
        "total_employees": total_emp,
        "branch_tickets": branch_tickets,
    }

    return templates.TemplateResponse(
        "supervisor/team.html",
        _ctx(request, agents=agents, branches=branches_first_page,
             branches_json=branches_json, branch_stats=branch_stats,
             regions=regions, cities=cities, active_tab=tab),
    )


# ── POST /api/supervisor/agents (CRUD) ────────────────────────────────────────

@router.post("/api/supervisor/agents",
             dependencies=[Depends(require_permission("supervisor.team"))])
async def create_agent(
    request: Request,
    full_name_ar: str = Form(...),
    full_name_en: Optional[str] = Form(None),
    username: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    employee_id: Optional[str] = Form(None),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.security import hash_password
    from app.models.user import User

    user_obj = User(
        id=uuid.uuid4(),
        username=username,
        full_name_ar=full_name_ar,
        full_name_en=full_name_en or None,
        email=email or None,
        phone=phone or None,
        employee_id=employee_id or None,
        role="employee",
        password_hash=hash_password(password),
        department_id=_get_dept_id(request),
    )
    async with db.begin():
        db.add(user_obj)
    return JSONResponse({"ok": True, "id": str(user_obj.id)})


@router.delete("/api/supervisor/agents/{agent_id}",
               dependencies=[Depends(require_permission("supervisor.team"))])
async def delete_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.models.user import User as _User

    try:
        aid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(_User).where(_User.id == aid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404)

    async with db.begin():
        agent.deleted_at = datetime.now(tz=UTC)
    return JSONResponse({"ok": True})


# ── GET /api/supervisor/agents/export (Excel) ─────────────────────────────────

@router.get("/api/supervisor/agents/export",
            dependencies=[Depends(require_permission("supervisor.team"))])
async def export_agents(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.user import User

    dept_id = _get_dept_id(request)
    q = select(User).where(User.is_active.is_(True), User.deleted_at.is_(None))
    if dept_id:
        q = q.where(User.department_id == dept_id)
    agents = list((await db.execute(q)).scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Agents"
    ws.append(["ID", "Username", "Full Name AR", "Full Name EN", "Email", "Phone", "Employee ID", "Role"])
    for a in agents:
        ws.append([str(a.id), a.username, a.full_name_ar, a.full_name_en, a.email, a.phone, a.employee_id, a.role])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=agents.xlsx"},
    )


# ── POST /api/supervisor/agents/import (Excel) ────────────────────────────────

@router.post("/api/supervisor/agents/import",
             dependencies=[Depends(require_permission("supervisor.team"))])
async def import_agents(
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.core.security import hash_password
    from app.models.user import User

    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    count = 0
    async with db.begin():
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0]:
                continue
            username, name_ar, name_en, email, phone, emp_id = (
                str(row[0] or ""), str(row[1] or ""), str(row[2] or ""),
                row[3], row[4], row[5]
            )
            if not username or not name_ar:
                continue
            user_obj = User(
                id=uuid.uuid4(),
                username=username,
                full_name_ar=name_ar,
                full_name_en=name_en or None,
                email=email or None,
                phone=str(phone) if phone else None,
                employee_id=str(emp_id) if emp_id else None,
                role="employee",
                password_hash=hash_password(secrets.token_urlsafe(16)),
                department_id=_get_dept_id(request),
            )
            db.add(user_obj)
            count += 1

    return JSONResponse({"ok": True, "imported": count})


# ── POST /api/supervisor/agents/import/preview (Excel Validation Preview) ──

@router.post("/api/supervisor/agents/import/preview", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("supervisor.team"))])
async def import_agents_preview(
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Parse Excel and return a validation preview before committing."""
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.user import User
    import re

    lang = getattr(request.state, "lang", "ar")
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    existing_usernames: set[str] = set()
    existing_emails: set[str] = set()
    result = await db.execute(select(User.username, User.email).where(User.deleted_at.is_(None)))
    for row in result.all():
        if row.username:
            existing_usernames.add(row.username.lower())
        if row.email:
            existing_emails.add(row.email.lower())

    preview_rows: list[dict] = []
    seen_usernames: set[str] = set()
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            continue
        username = str(row[0] or "").strip()
        name_ar = str(row[1] or "").strip() if len(row) > 1 else ""
        name_en = str(row[2] or "").strip() if len(row) > 2 else ""
        email_val = str(row[3] or "").strip() if len(row) > 3 else ""
        phone_val = str(row[4] or "").strip() if len(row) > 4 else ""
        emp_id = str(row[5] or "").strip() if len(row) > 5 else ""

        errors: list[str] = []
        if not username:
            errors.append("اسم المستخدم مطلوب" if lang == "ar" else "Username required")
        elif username.lower() in existing_usernames:
            errors.append("اسم المستخدم موجود" if lang == "ar" else "Username exists")
        elif username.lower() in seen_usernames:
            errors.append("مكرر في الملف" if lang == "ar" else "Duplicate in file")
        if not name_ar:
            errors.append("الاسم العربي مطلوب" if lang == "ar" else "Arabic name required")
        if email_val and not re.match(r"^[^@]+@[^@]+\.[^@]+$", email_val):
            errors.append("بريد غير صالح" if lang == "ar" else "Invalid email")
        elif email_val and email_val.lower() in existing_emails:
            errors.append("البريد موجود" if lang == "ar" else "Email exists")

        seen_usernames.add(username.lower())
        preview_rows.append({
            "row": idx, "username": username, "name_ar": name_ar,
            "name_en": name_en, "email": email_val, "phone": phone_val,
            "emp_id": emp_id, "errors": errors, "valid": len(errors) == 0,
        })

    valid_count = sum(1 for r in preview_rows if r["valid"])
    invalid_count = sum(1 for r in preview_rows if not r["valid"])
    total = len(preview_rows)

    rows_html = ""
    for r in preview_rows:
        status_cls = "text-green-500" if r["valid"] else "text-red-500"
        status_txt = "✅" if r["valid"] else f"❌ {', '.join(r['errors'])}"
        rows_html += (
            f'<tr style="border-bottom:1px solid var(--border);">'
            f'<td class="px-3 py-2 text-xs" style="color:var(--text-faint);">{r["row"]}</td>'
            f'<td class="px-3 py-2 text-xs font-mono" style="color:var(--text-main);">{r["username"]}</td>'
            f'<td class="px-3 py-2 text-xs" style="color:var(--text-main);">{r["name_ar"]}</td>'
            f'<td class="px-3 py-2 text-xs" style="color:var(--text-main);">{r["name_en"]}</td>'
            f'<td class="px-3 py-2 text-xs" style="color:var(--text-muted);">{r["email"]}</td>'
            f'<td class="px-3 py-2 text-xs {status_cls}">{status_txt}</td>'
            f'</tr>'
        )

    summary = f"✅ {valid_count} / {total}" + (f"  ❌ {invalid_count}" if invalid_count else "")
    btn_label = f"تأكيد الاستيراد ({valid_count})" if lang == "ar" else f"Confirm Import ({valid_count})"
    html = (
        f'<div id="import-preview" class="mt-4">'
        f'<div class="flex items-center justify-between mb-3">'
        f'<p class="text-sm font-bold" style="color:var(--text-main);">{summary}</p>'
        f'<button hx-post="/api/supervisor/agents/import" hx-include="#import-file" '
        f'hx-target="#import-result" hx-encoding="multipart/form-data" '
        f'class="px-4 py-2 rounded font-bold text-white cursor-pointer" style="background:#00AEEF;"'
        f'{" disabled" if valid_count == 0 else ""}>{btn_label}</button>'
        f'</div>'
        f'<div style="max-height:320px;overflow-y:auto;border:1px solid var(--border);border-radius:0.5rem;">'
        f'<table class="w-full"><thead><tr style="background:var(--card-bg);">'
        f'<th class="px-3 py-2 text-xs text-start" style="color:var(--text-faint);">#</th>'
        f'<th class="px-3 py-2 text-xs text-start" style="color:var(--text-faint);">Username</th>'
        f'<th class="px-3 py-2 text-xs text-start" style="color:var(--text-faint);">Name AR</th>'
        f'<th class="px-3 py-2 text-xs text-start" style="color:var(--text-faint);">Name EN</th>'
        f'<th class="px-3 py-2 text-xs text-start" style="color:var(--text-faint);">Email</th>'
        f'<th class="px-3 py-2 text-xs text-start" style="color:var(--text-faint);">Status</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table></div></div>'
    )
    return HTMLResponse(html)


# ── POST /api/supervisor/schedule ─────────────────────────────────────────

@router.post("/api/supervisor/schedule", response_class=HTMLResponse,
             dependencies=[Depends(require_permission("supervisor.team"))])
async def save_schedule(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Save weekly shift schedule for agents."""
    from app.models.schedule import AgentSchedule

    lang = getattr(request.state, "lang", "ar")
    form = await request.form()

    saved = 0
    now = datetime.now(tz=UTC)
    week_start_str = form.get("week_start")
    if not week_start_str:
        from datetime import date
        today = date.today()
        week_start_str = str(today - __import__("datetime").timedelta(days=today.weekday()))

    for key, val in form.items():
        if not key.startswith("shift_"):
            continue
        parts = key.split("_")
        if len(parts) != 3:
            continue
        agent_id_str, day_idx = parts[1], parts[2]
        try:
            agent_uuid = uuid.UUID(agent_id_str)
            day = int(day_idx)
        except (ValueError, TypeError):
            continue

        shift_type = str(val).strip()
        if shift_type not in ("morning", "evening", "off"):
            continue

        existing = await db.execute(
            select(AgentSchedule).where(
                AgentSchedule.agent_id == agent_uuid,
                AgentSchedule.week_start == week_start_str,
                AgentSchedule.day_of_week == day,
            )
        )
        sched = existing.scalar_one_or_none()
        if sched:
            sched.shift_type = shift_type
            sched.updated_at = now
        else:
            db.add(AgentSchedule(
                id=uuid.uuid4(),
                agent_id=agent_uuid,
                week_start=week_start_str,
                day_of_week=day,
                shift_type=shift_type,
            ))
        saved += 1

    await db.flush()

    conflicts = await _detect_schedule_conflicts(db, week_start_str)
    conflict_html = ""
    if conflicts:
        items = "".join(f'<li class="text-xs">⚠️ {c}</li>' for c in conflicts)
        conflict_html = f'<ul class="mt-2 space-y-1 text-amber-500">{items}</ul>'

    msg = f"تم حفظ {saved} وردية" if lang == "ar" else f"Saved {saved} shifts"
    return HTMLResponse(f'<div><p class="text-sm text-green-600">✅ {msg}</p>{conflict_html}</div>')


async def _detect_schedule_conflicts(db: AsyncSession, week_start: str) -> list[str]:
    """Auto-detect gaps in schedule coverage (e.g., no agent on a shift)."""
    from app.models.schedule import AgentSchedule
    from sqlalchemy import func as _func

    conflicts: list[str] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for day_idx in range(7):
        for shift in ("morning", "evening"):
            count_q = await db.execute(
                select(_func.count(AgentSchedule.id)).where(
                    AgentSchedule.week_start == week_start,
                    AgentSchedule.day_of_week == day_idx,
                    AgentSchedule.shift_type == shift,
                )
            )
            cnt = count_q.scalar() or 0
            if cnt == 0:
                conflicts.append(f"{day_names[day_idx]} {shift}: No agents assigned")

    return conflicts


# ── GET /api/supervisor/tickets/export ────────────────────────────────────

@router.get("/api/supervisor/tickets/export",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def export_tickets(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.ticket import Ticket
    from sqlalchemy import or_

    query = select(Ticket).where(Ticket.deleted_at.is_(None)).order_by(Ticket.created_at.desc())
    if q:
        query = query.where(or_(
            Ticket.ticket_number.ilike(f"%{q}%"),
            Ticket.subject.ilike(f"%{q}%"),
        ))
    if status:
        query = query.where(Ticket.status == status)
    if priority:
        query = query.where(Ticket.priority == priority)

    tickets = list((await db.execute(query.limit(5000))).scalars().all())

    wb = __import__("openpyxl").Workbook()
    ws = wb.active
    ws.title = "Tickets"
    ws.append(["#", "Subject", "Status", "Priority", "Queue", "Created"])
    for tk in tickets:
        ws.append([
            tk.ticket_number, tk.subject, tk.status, tk.priority,
            tk.current_queue, str(tk.created_at)[:19] if tk.created_at else "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tickets.xlsx"},
    )


# ── GET /supervisor/tickets ────────────────────────────────────────────────────

@router.get("/supervisor/tickets", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("supervisor.view"))])
async def supervisor_tickets(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    agent_id: Optional[str] = None,
    queue_filter: Optional[str] = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.ticket import Ticket
    from app.models.user import User
    from sqlalchemy import func, or_

    per_page = 25
    dept_id = _get_dept_id(request)

    query = (
        select(Ticket)
        .where(Ticket.deleted_at.is_(None))
        .options(
            __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(Ticket.assignee),
            __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(Ticket.category),
        )
        .order_by(Ticket.created_at.desc())
    )

    if q:
        query = query.where(or_(
            Ticket.ticket_number.ilike(f"%{q}%"),
            Ticket.subject.ilike(f"%{q}%"),
            Ticket.submitter_name.ilike(f"%{q}%"),
            Ticket.description.ilike(f"%{q}%"),
        ))
    if status:
        query = query.where(Ticket.status == status)
    if priority:
        query = query.where(Ticket.priority == priority)
    if agent_id:
        try:
            query = query.where(Ticket.assigned_to == __import__("uuid").UUID(agent_id))
        except ValueError:
            pass
    if queue_filter:
        if queue_filter in ("main", "supervisor", "manager", "specialized", "internal_tickets"):
            query = query.where(Ticket.current_queue == queue_filter)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    tickets_result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    tickets = list(tickets_result.scalars().all())

    # Agents for filter
    agents_q = select(User).where(User.is_active.is_(True), User.deleted_at.is_(None))
    if dept_id:
        agents_q = agents_q.where(User.department_id == dept_id)
    agents = list((await db.execute(agents_q.order_by(User.full_name_ar))).scalars().all())

    ticket_ids = [str(t.id) for t in tickets]

    return templates.TemplateResponse(
        "supervisor/tickets.html",
        _ctx(
            request,
            tickets=tickets,
            agents=agents,
            ticket_ids=ticket_ids,
            q=q, status=status, priority=priority,
            agent_id=agent_id, queue_filter=queue_filter,
            page=page, total_pages=total_pages, total=total,
        ),
    )


# ── POST /api/supervisor/tickets/bulk-assign ──────────────────────────────────

@router.post("/api/supervisor/tickets/bulk-assign",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def bulk_assign_tickets(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    import json as _json
    from app.models.ticket import Ticket

    body = await request.json()
    ticket_ids = body.get("ticket_ids", [])
    agent_id_str = body.get("agent_id")

    if not ticket_ids or not agent_id_str:
        raise HTTPException(400, "Missing ticket_ids or agent_id")

    try:
        agent_uuid = __import__("uuid").UUID(agent_id_str)
    except ValueError:
        raise HTTPException(400, "Invalid agent_id")

    user_payload = getattr(request.state, "user", {}) or {}
    actor_id_str = user_payload.get("sub")

    updated = 0
    async with db.begin():
        for tid_str in ticket_ids:
            try:
                tid = __import__("uuid").UUID(tid_str)
            except ValueError:
                continue
            result = await db.execute(select(Ticket).where(Ticket.id == tid, Ticket.deleted_at.is_(None)))
            ticket = result.scalar_one_or_none()
            if ticket:
                ticket.assigned_to = agent_uuid
                ticket.status = "open" if ticket.status == "new" else ticket.status
                updated += 1

    return JSONResponse({"ok": True, "updated": updated})


# ── POST /api/supervisor/broadcast ────────────────────────────────────────────

@router.post("/api/supervisor/broadcast",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def broadcast_email(
    request: Request,
    subject: str = Form(...),
    body: str = Form(...),
    target: str = Form("all"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Send email alert to all agents or specific branch."""
    from app.models.user import User
    from app.models.branch import Branch
    from app.models.audit import AuditLog

    lang = getattr(request.state, "lang", "ar")
    actor = getattr(request.state, "user", {}) or {}

    q = select(User.email).where(User.is_active.is_(True), User.deleted_at.is_(None), User.email.isnot(None))
    # User has no branch_id; branch filtering for broadcast not supported — send to all agents
    if target and target != "all":
        try:
            uuid.UUID(target)
        except ValueError:
            pass

    result = await db.execute(q)
    emails = [r.email for r in result.all() if r.email]

    try:
        from app.services.email import send_bulk_email
        await send_bulk_email(emails, subject, body)
    except (ImportError, Exception):
        pass

    from app.services.audit import log, AuditAction
    await log(db, AuditAction.BROADCAST_SENT,
        actor_id=uuid.UUID(actor.get("sub", "")) if actor.get("sub") else None,
        resource_type="broadcast",
        new_value={"subject": subject, "target": target, "recipients_count": len(emails)},
    )
    await db.flush()

    return JSONResponse({"ok": True, "recipients": len(emails), "message": t("sup.broadcast_sent", lang=lang)})


# ══════════════════════════════════════════════════════════════════════════════
# BRANCH & EMPLOYEE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/supervisor/branches/list",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def list_branches_api(
    request: Request,
    q: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Paginated, filtered branch list for the frontend table."""
    from sqlalchemy import func as _func, or_ as _or_
    from app.models.branch import Branch, BranchEmployee

    query = select(Branch).where(Branch.deleted_at.is_(None))
    if q:
        q_lower = f"%{q}%"
        query = query.where(_or_(
            Branch.name_ar.ilike(q_lower), Branch.name_en.ilike(q_lower),
            Branch.code.ilike(q_lower), Branch.city_ar.ilike(q_lower),
            Branch.city_en.ilike(q_lower),
        ))
    if region:
        query = query.where(_or_(Branch.region_ar == region, Branch.region_en == region))
    if city:
        query = query.where(_or_(Branch.city_ar == city, Branch.city_en == city))
    if status == "active":
        query = query.where(Branch.is_active.is_(True))
    elif status == "inactive":
        query = query.where(Branch.is_active.is_(False))

    total_q = select(_func.count()).select_from(query.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    branches = list((await db.execute(
        query.order_by(Branch.name_ar).offset((page - 1) * per_page).limit(per_page)
    )).scalars().all())

    # Bulk employee counts for returned branches
    branch_ids = [b.id for b in branches]
    emp_counts: dict[str, int] = {}
    if branch_ids:
        cnt_q = await db.execute(
            select(BranchEmployee.branch_id, _func.count(BranchEmployee.id).label("cnt"))
            .where(BranchEmployee.branch_id.in_(branch_ids), BranchEmployee.deleted_at.is_(None))
            .group_by(BranchEmployee.branch_id)
        )
        for row in cnt_q.all():
            emp_counts[str(row.branch_id)] = row.cnt

    return JSONResponse({
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "branches": [{
            "id": str(b.id), "name_ar": b.name_ar, "name_en": b.name_en or b.name_ar,
            "code": b.code, "city_ar": b.city_ar or "", "city_en": b.city_en or "",
            "region_ar": b.region_ar or "", "region_en": b.region_en or "",
            "phone": b.phone or "", "email": b.email or "",
            "internal_notes": b.internal_notes or "",
            "is_active": b.is_active,
            "employee_count": emp_counts.get(str(b.id), 0),
        } for b in branches],
    })


@router.get("/api/supervisor/branches/{branch_id}/employees/list",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def list_employees_paginated(
    branch_id: str,
    q: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from sqlalchemy import func as _func, or_ as _or_
    from app.models.branch import BranchEmployee

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    query = select(BranchEmployee).where(
        BranchEmployee.branch_id == bid, BranchEmployee.deleted_at.is_(None)
    )
    if q:
        q_like = f"%{q}%"
        query = query.where(_or_(
            BranchEmployee.full_name_ar.ilike(q_like),
            BranchEmployee.full_name_en.ilike(q_like),
            BranchEmployee.employee_id.ilike(q_like),
            BranchEmployee.phone.ilike(q_like),
        ))
    if status == "active":
        query = query.where(BranchEmployee.is_active.is_(True))
    elif status == "inactive":
        query = query.where(BranchEmployee.is_active.is_(False))

    total = (await db.execute(select(_func.count()).select_from(query.subquery()))).scalar() or 0
    emps = list((await db.execute(
        query.order_by(BranchEmployee.full_name_ar).offset((page - 1) * per_page).limit(per_page)
    )).scalars().all())

    return JSONResponse({
        "total": total, "page": page, "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "employees": [{
            "id": str(e.id), "full_name_ar": e.full_name_ar, "full_name_en": e.full_name_en or "",
            "employee_id": e.employee_id, "phone": e.phone or "", "email": e.email or "",
            "position_ar": e.position_ar or "", "position_en": e.position_en or "",
            "preferred_language": e.preferred_language, "is_active": e.is_active,
        } for e in emps],
    })


@router.get("/supervisor/branches", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("supervisor.view"))])
async def branches_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    import json as _json
    from sqlalchemy import func
    from app.models.branch import Branch, BranchEmployee
    from app.models.ticket import Ticket

    branches_result = await db.execute(
        select(Branch).where(Branch.deleted_at.is_(None)).order_by(Branch.name_ar)
    )
    branches = list(branches_result.scalars().all())

    emp_counts: dict[str, int] = {}
    for b in branches:
        c = await db.execute(
            select(func.count()).select_from(BranchEmployee).where(
                BranchEmployee.branch_id == b.id,
                BranchEmployee.deleted_at.is_(None),
            )
        )
        emp_counts[str(b.id)] = c.scalar() or 0

    total_emp = sum(emp_counts.values())
    ticket_count_result = await db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.branch_id.isnot(None), Ticket.deleted_at.is_(None)
        )
    )
    branch_tickets = ticket_count_result.scalar() or 0

    regions = sorted(set(
        (b.region_ar or b.region_en or "") for b in branches if (b.region_ar or b.region_en)
    ))

    branches_json = _json.dumps([{
        "id": str(b.id),
        "name_ar": b.name_ar,
        "name_en": b.name_en,
        "code": b.code,
        "city_ar": b.city_ar or "",
        "city_en": b.city_en or "",
        "region_ar": b.region_ar or "",
        "region_en": b.region_en or "",
        "phone": b.phone or "",
        "email": b.email or "",
        "internal_notes": b.internal_notes or "",
        "is_active": b.is_active,
        "employee_count": emp_counts.get(str(b.id), 0),
    } for b in branches], ensure_ascii=False)

    stats = {
        "total_branches": len(branches),
        "active_branches": sum(1 for b in branches if b.is_active),
        "total_employees": total_emp,
        "branch_tickets": branch_tickets,
    }

    return templates.TemplateResponse(
        "supervisor/branches.html",
        _ctx(request, branches_json=branches_json, stats=stats, regions=regions),
    )


# ── Branch CRUD API ──────────────────────────────────────────────────────────

@router.post("/api/supervisor/branches",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def create_branch(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    from app.models.branch import Branch

    body = await request.json()
    name_ar = (body.get("name_ar") or "").strip()
    name_en = (body.get("name_en") or "").strip()
    code    = (body.get("code") or "").strip()

    if not name_ar or not name_en or not code:
        raise HTTPException(422, detail="Name and code required")

    existing = await db.execute(select(Branch).where(Branch.code == code, Branch.deleted_at.is_(None)))
    if existing.scalar_one_or_none():
        raise HTTPException(409, detail="Branch code already exists")

    branch = Branch(
        id=uuid.uuid4(),
        name_ar=name_ar, name_en=name_en, code=code,
        city_ar=(body.get("city_ar") or "").strip() or None,
        city_en=(body.get("city_en") or "").strip() or None,
        region_ar=(body.get("region_ar") or "").strip() or None,
        region_en=(body.get("region_en") or "").strip() or None,
        phone=(body.get("phone") or "").strip() or None,
        email=(body.get("email") or "").strip() or None,
        internal_notes=(body.get("internal_notes") or "").strip() or None,
    )
    db.add(branch)
    await db.commit()
    return JSONResponse({"ok": True, "id": str(branch.id)})


@router.put("/api/supervisor/branches/{branch_id}",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def update_branch(
    branch_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import Branch

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Branch).where(Branch.id == bid, Branch.deleted_at.is_(None)))
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(404)

    body = await request.json()
    for field in ("name_ar", "name_en", "code", "city_ar", "city_en", "region_ar", "region_en", "phone", "email", "internal_notes"):
        val = body.get(field)
        if val is not None:
            setattr(branch, field, val.strip() if isinstance(val, str) else val)

    branch.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/supervisor/branches/{branch_id}/toggle",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def toggle_branch(
    branch_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import Branch

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(select(Branch).where(Branch.id == bid, Branch.deleted_at.is_(None)))
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(404)

    branch.is_active = not branch.is_active
    branch.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True, "is_active": branch.is_active})


@router.get("/api/supervisor/branches/export",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def export_branches(request: Request, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.branch import Branch

    branches = list((await db.execute(
        select(Branch).where(Branch.deleted_at.is_(None)).order_by(Branch.name_ar)
    )).scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Branches"
    ws.append(["Code", "Name AR", "Name EN", "City AR", "City EN", "Region AR", "Region EN", "Phone", "Email", "Active"])
    for b in branches:
        ws.append([b.code, b.name_ar, b.name_en, b.city_ar, b.city_en, b.region_ar, b.region_en, b.phone, b.email, "Yes" if b.is_active else "No"])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=branches.xlsx"},
    )


@router.get("/api/supervisor/branches/export-with-employees",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def export_branches_with_employees(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.branch import Branch, BranchEmployee

    branches = list((await db.execute(
        select(Branch).where(Branch.deleted_at.is_(None)).order_by(Branch.name_ar)
    )).scalars().all())
    employees = list((await db.execute(
        select(BranchEmployee).where(BranchEmployee.deleted_at.is_(None)).order_by(BranchEmployee.full_name_ar)
    )).scalars().all())

    branch_code_map = {b.id: b.code for b in branches}

    wb = openpyxl.Workbook()

    ws_branches = wb.active
    ws_branches.title = "Branches"
    ws_branches.append(
        ["Code", "Name AR", "Name EN", "City AR", "City EN", "Region AR", "Region EN", "Phone", "Email", "Active"]
    )
    for b in branches:
        ws_branches.append([
            b.code, b.name_ar, b.name_en, b.city_ar, b.city_en, b.region_ar, b.region_en, b.phone, b.email,
            "Yes" if b.is_active else "No",
        ])

    ws_employees = wb.create_sheet("Employees")
    ws_employees.append(
        ["Branch Code", "Employee ID", "Name AR", "Name EN", "Phone", "Email", "Position AR", "Position EN", "Active"]
    )
    for e in employees:
        ws_employees.append([
            branch_code_map.get(e.branch_id, ""),
            e.employee_id,
            e.full_name_ar,
            e.full_name_en,
            e.phone,
            e.email,
            e.position_ar,
            e.position_en,
            "Yes" if e.is_active else "No",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=branches_with_employees.xlsx"},
    )


# ── Employee CRUD API ────────────────────────────────────────────────────────

@router.get("/api/supervisor/branches/{branch_id}/employees",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def list_employees(
    branch_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import BranchEmployee

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(
        select(BranchEmployee).where(
            BranchEmployee.branch_id == bid,
            BranchEmployee.deleted_at.is_(None),
        ).order_by(BranchEmployee.full_name_ar)
    )
    emps = list(result.scalars().all())
    return JSONResponse({"employees": [{
        "id": str(e.id),
        "full_name_ar": e.full_name_ar,
        "full_name_en": e.full_name_en or "",
        "employee_id": e.employee_id,
        "phone": e.phone or "",
        "email": e.email or "",
        "position_ar": e.position_ar or "",
        "position_en": e.position_en or "",
        "preferred_language": e.preferred_language,
        "is_active": e.is_active,
    } for e in emps]})


@router.get("/api/supervisor/branches/{branch_id}/employees/export",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def export_branch_employees(
    branch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.branch import Branch, BranchEmployee

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    branch_result = await db.execute(select(Branch).where(Branch.id == bid, Branch.deleted_at.is_(None)))
    branch = branch_result.scalar_one_or_none()
    if not branch:
        raise HTTPException(404)

    employees = list((await db.execute(
        select(BranchEmployee).where(
            BranchEmployee.branch_id == bid,
            BranchEmployee.deleted_at.is_(None),
        ).order_by(BranchEmployee.full_name_ar)
    )).scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append(["Employee ID", "Name AR", "Name EN", "Phone", "Email", "Position AR", "Position EN", "Language", "Active"])
    for e in employees:
        ws.append([
            e.employee_id,
            e.full_name_ar,
            e.full_name_en,
            e.phone,
            e.email,
            e.position_ar,
            e.position_en,
            e.preferred_language,
            "Yes" if e.is_active else "No",
        ])

    safe_code = (branch.code or "branch").replace("/", "-").replace("\\", "-")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=employees_{safe_code}.xlsx"},
    )


@router.post("/api/supervisor/branches/{branch_id}/employees",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def create_employee(
    branch_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import BranchEmployee

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    body = await request.json()
    full_name_ar = (body.get("full_name_ar") or "").strip()
    employee_id  = (body.get("employee_id") or "").strip()

    if not full_name_ar or not employee_id:
        raise HTTPException(422, detail="Name and employee ID are required")

    existing = await db.execute(
        select(BranchEmployee).where(BranchEmployee.employee_id == employee_id, BranchEmployee.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, detail="Employee ID already exists")

    emp = BranchEmployee(
        id=uuid.uuid4(),
        branch_id=bid,
        full_name_ar=full_name_ar,
        full_name_en=(body.get("full_name_en") or "").strip() or None,
        employee_id=employee_id,
        phone=(body.get("phone") or "").strip() or None,
        email=(body.get("email") or "").strip() or None,
        position_ar=(body.get("position_ar") or "").strip() or None,
        position_en=(body.get("position_en") or "").strip() or None,
        preferred_language=body.get("preferred_language", "ar"),
    )
    db.add(emp)
    await db.commit()
    return JSONResponse({"ok": True, "id": str(emp.id)})


@router.put("/api/supervisor/branches/{branch_id}/employees/{emp_id}",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def update_employee(
    branch_id: str, emp_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import BranchEmployee

    try:
        eid = uuid.UUID(emp_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(
        select(BranchEmployee).where(BranchEmployee.id == eid, BranchEmployee.deleted_at.is_(None))
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(404)

    body = await request.json()
    for field in ("full_name_ar", "full_name_en", "employee_id", "phone", "email", "position_ar", "position_en", "preferred_language"):
        val = body.get(field)
        if val is not None:
            setattr(emp, field, val.strip() if isinstance(val, str) else val)

    emp.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/supervisor/branches/{branch_id}/employees/{emp_id}/toggle",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def toggle_employee(
    branch_id: str, emp_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import BranchEmployee

    try:
        eid = uuid.UUID(emp_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(
        select(BranchEmployee).where(BranchEmployee.id == eid, BranchEmployee.deleted_at.is_(None))
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(404)

    emp.is_active = not emp.is_active
    emp.updated_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True, "is_active": emp.is_active})


@router.delete("/api/supervisor/branches/{branch_id}/employees/{emp_id}",
               dependencies=[Depends(require_permission("supervisor.view"))])
async def delete_employee(
    branch_id: str, emp_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.models.branch import BranchEmployee

    try:
        eid = uuid.UUID(emp_id)
    except ValueError:
        raise HTTPException(400)

    result = await db.execute(
        select(BranchEmployee).where(BranchEmployee.id == eid, BranchEmployee.deleted_at.is_(None))
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(404)

    emp.deleted_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/supervisor/branches/{branch_id}/employees/import",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def import_employees(
    branch_id: str, request: Request, file: UploadFile, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.branch import BranchEmployee

    try:
        bid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(400)

    lang = getattr(request.state, "lang", "ar")
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    count = 0
    skipped = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        emp_id_val = str(row[0]).strip()
        name_ar    = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if not emp_id_val or not name_ar:
            skipped += 1
            continue

        existing = await db.execute(
            select(BranchEmployee).where(BranchEmployee.employee_id == emp_id_val, BranchEmployee.deleted_at.is_(None))
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        db.add(BranchEmployee(
            id=uuid.uuid4(),
            branch_id=bid,
            full_name_ar=name_ar,
            full_name_en=str(row[2]).strip() if len(row) > 2 and row[2] else None,
            employee_id=emp_id_val,
            phone=str(row[3]).strip() if len(row) > 3 and row[3] else None,
            email=str(row[4]).strip() if len(row) > 4 and row[4] else None,
            position_ar=str(row[5]).strip() if len(row) > 5 and row[5] else None,
            position_en=str(row[6]).strip() if len(row) > 6 and row[6] else None,
        ))
        count += 1

    await db.commit()

    msg = f"تم استيراد {count} موظف" if lang == "ar" else f"Imported {count} employees"
    if skipped:
        msg += f" ({skipped} {'تم تخطيه' if lang == 'ar' else 'skipped'})"
    return JSONResponse({"ok": True, "imported": count, "skipped": skipped, "message": msg})


@router.post("/api/supervisor/branches/import",
             dependencies=[Depends(require_permission("supervisor.view"))])
async def import_branches_with_employees(
    request: Request, file: UploadFile, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    """
    Import branches + employees from a single Excel file.
    Sheet 1 (Branches): Code | Name AR | Name EN | City AR | City EN | Region AR | Region EN | Phone | Email
    Sheet 2 (Employees): Branch Code | Employee ID | Name AR | Name EN | Phone | Email | Position AR | Position EN
    """
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from app.models.branch import Branch, BranchEmployee

    lang = getattr(request.state, "lang", "ar")
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    sheets = wb.sheetnames

    branches_created = 0
    branches_skipped = 0
    emps_created = 0
    emps_skipped = 0

    # Sheet 1: Branches
    ws_branches = wb[sheets[0]]
    for row in ws_branches.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        code = str(row[0]).strip()
        name_ar = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if not code or not name_ar:
            branches_skipped += 1
            continue

        existing = await db.execute(
            select(Branch).where(Branch.code == code, Branch.deleted_at.is_(None))
        )
        if existing.scalar_one_or_none():
            branches_skipped += 1
            continue

        db.add(Branch(
            id=uuid.uuid4(), code=code, name_ar=name_ar,
            name_en=str(row[2]).strip() if len(row) > 2 and row[2] else name_ar,
            city_ar=str(row[3]).strip() if len(row) > 3 and row[3] else None,
            city_en=str(row[4]).strip() if len(row) > 4 and row[4] else None,
            region_ar=str(row[5]).strip() if len(row) > 5 and row[5] else None,
            region_en=str(row[6]).strip() if len(row) > 6 and row[6] else None,
            phone=str(row[7]).strip() if len(row) > 7 and row[7] else None,
            email=str(row[8]).strip() if len(row) > 8 and row[8] else None,
        ))
        branches_created += 1

    await db.flush()

    # Sheet 2: Employees (if exists)
    if len(sheets) >= 2:
        ws_emps = wb[sheets[1]]
        for row in ws_emps.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            branch_code = str(row[0]).strip()
            emp_id_val = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            name_ar = str(row[2]).strip() if len(row) > 2 and row[2] else ""
            if not branch_code or not emp_id_val or not name_ar:
                emps_skipped += 1
                continue

            branch_result = await db.execute(
                select(Branch).where(Branch.code == branch_code, Branch.deleted_at.is_(None))
            )
            branch = branch_result.scalar_one_or_none()
            if not branch:
                emps_skipped += 1
                continue

            existing_emp = await db.execute(
                select(BranchEmployee).where(
                    BranchEmployee.employee_id == emp_id_val, BranchEmployee.deleted_at.is_(None)
                )
            )
            if existing_emp.scalar_one_or_none():
                emps_skipped += 1
                continue

            db.add(BranchEmployee(
                id=uuid.uuid4(), branch_id=branch.id,
                full_name_ar=name_ar,
                full_name_en=str(row[3]).strip() if len(row) > 3 and row[3] else None,
                employee_id=emp_id_val,
                phone=str(row[4]).strip() if len(row) > 4 and row[4] else None,
                email=str(row[5]).strip() if len(row) > 5 and row[5] else None,
                position_ar=str(row[6]).strip() if len(row) > 6 and row[6] else None,
                position_en=str(row[7]).strip() if len(row) > 7 and row[7] else None,
            ))
            emps_created += 1

    await db.commit()

    if lang == "ar":
        msg = f"تم استيراد {branches_created} فرع و {emps_created} موظف"
        if branches_skipped or emps_skipped:
            msg += f" (تم تخطي {branches_skipped} فرع و {emps_skipped} موظف)"
    else:
        msg = f"Imported {branches_created} branches and {emps_created} employees"
        if branches_skipped or emps_skipped:
            msg += f" (skipped {branches_skipped} branches, {emps_skipped} employees)"

    return JSONResponse({
        "ok": True,
        "branches_created": branches_created, "branches_skipped": branches_skipped,
        "emps_created": emps_created, "emps_skipped": emps_skipped,
        "message": msg,
    })


@router.get("/api/supervisor/branches/import/template",
            dependencies=[Depends(require_permission("supervisor.view"))])
async def download_import_template(request: Request) -> StreamingResponse:
    """Download an Excel template for bulk branch+employee import."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="00AEEF", end_color="00AEEF", fill_type="solid")

    # Sheet 1: Branches
    ws1 = wb.active
    ws1.title = "Branches"
    headers1 = ["Code", "Name AR", "Name EN", "City AR", "City EN", "Region AR", "Region EN", "Phone", "Email"]
    for col, h in enumerate(headers1, 1):
        cell = ws1.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    ws1.append(["RYD-01", "فرع الرياض", "Riyadh Branch", "الرياض", "Riyadh", "منطقة الرياض", "Riyadh Region", "0112345678", "riyadh@company.com"])
    for col in range(1, 10):
        ws1.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

    # Sheet 2: Employees
    ws2 = wb.create_sheet("Employees")
    headers2 = ["Branch Code", "Employee ID", "Name AR", "Name EN", "Phone", "Email", "Position AR", "Position EN"]
    for col, h in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    ws2.append(["RYD-01", "EMP-0001", "أحمد محمد", "Ahmed Mohammed", "0501234567", "ahmed@company.com", "مسؤول مبيعات", "Sales Officer"])
    for col in range(1, 9):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=branch_import_template.xlsx"},
    )
