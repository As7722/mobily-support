"""
Employee Dashboard Routes
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.redis import get_redis
from app.core.templates import templates
from app.i18n import t
from app.services.kpi import get_employee_kpis
from app.services.queue import claim_ticket, get_smart_queue

router = APIRouter()
UTC = timezone.utc


async def _get_unread_count(request: Request, db: AsyncSession) -> int:
    from app.services.notifications import get_unread_count
    user = getattr(request.state, "user", {}) or {}
    uid_str = user.get("sub")
    if not uid_str:
        return 0
    try:
        return await get_unread_count(db, uuid.UUID(uid_str))
    except Exception:
        return 0


def _ctx(request: Request, **extra) -> dict:
    lang = getattr(request.state, "lang", "ar")
    return {
        "request": request,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "dark_mode": request.cookies.get("dark_mode", "1") != "0",
        "now": datetime.now(tz=UTC),
        "unread_notifications": extra.pop("unread_notifications", 0),
        **extra,
    }


# ── GET /dashboard ─────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("dashboard.view"))])
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    user_id_str = user.get("sub")
    role        = user.get("role", "employee")
    try:
        user_id = uuid.UUID(user_id_str) if user_id_str else None
    except ValueError:
        user_id = None

    kpis   = await get_employee_kpis(db, user_id, redis) if user_id else {}
    queue  = await get_smart_queue(db, user_id=user_id, role=role)
    unread = await _get_unread_count(request, db)

    # Fetch display name from DB (not in JWT payload)
    employee_name = ""
    if user_id:
        from sqlalchemy import select
        from app.models.user import User
        lang = getattr(request.state, "lang", "ar")
        db_user = await db.scalar(select(User).where(User.id == user_id))
        if db_user:
            employee_name = (db_user.full_name_ar or db_user.full_name_en or "") if lang == "ar" \
                else (db_user.full_name_en or db_user.full_name_ar or "")

    return templates.TemplateResponse(
        "dashboard/index.html",
        _ctx(request, kpis=kpis, queue=queue, unread_notifications=unread,
             employee_name=employee_name),
    )


# ── GET /api/dashboard/queue (HTMX partial) ───────────────────────────────────

@router.get("/api/dashboard/queue", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("dashboard.view"))])
async def queue_partial(
    request: Request,
    page: int = 1,
    filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    user_id_str = user.get("sub")
    role        = user.get("role", "employee")
    try:
        user_id = uuid.UUID(user_id_str) if user_id_str else None
    except ValueError:
        user_id = None

    lang = getattr(request.state, "lang", "ar")
    queue = await get_smart_queue(db, user_id=user_id, role=role, page=page, assigned_filter=filter)

    _d = "rtl" if lang == "ar" else "ltr"
    return templates.TemplateResponse(
        "dashboard/_queue_rows.html",
        {"request": request, "lang": lang, "dir": _d, "queue": queue, "format_date": templates.env.globals["format_date"], "t": t, "bl": templates.env.globals["bl"]},
    )


# ── Iron Rule #4: Segregated Queue Endpoints ──────────────────────────────────

def _queue_ctx(request: Request, queue: dict) -> dict:
    lang = getattr(request.state, "lang", "ar")
    return {
        "request": request, "lang": lang, "dir": "rtl" if lang == "ar" else "ltr",
        "queue": queue, "format_date": templates.env.globals["format_date"],
        "t": t, "bl": templates.env.globals["bl"],
    }


def _parse_filter_uuid(val: Optional[str]) -> Optional[uuid.UUID]:
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except ValueError:
        return None


@router.get("/api/tickets/queues/main", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("tickets.view"))])
async def queue_main(
    request: Request, page: int = 1,
    agent_id: Optional[str] = None, dept_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    queue = await get_smart_queue(
        db, user_id=_parse_user_id(user), role=user.get("role", "employee"),
        page=page, queue_filter="main",
        filter_agent_id=_parse_filter_uuid(agent_id),
        filter_dept_id=_parse_filter_uuid(dept_id),
    )
    return templates.TemplateResponse("dashboard/_queue_rows.html", _queue_ctx(request, queue))


@router.get("/api/tickets/queues/specialized", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("tickets.view"))])
async def queue_specialized(
    request: Request, page: int = 1,
    agent_id: Optional[str] = None, dept_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    user_dept = _parse_dept_id(user)
    role = user.get("role", "employee")
    lang = getattr(request.state, "lang", "ar")

    if not user_dept and role not in ("supervisor", "manager", "admin"):
        return HTMLResponse(
            f'<tr><td colspan="10" class="text-center text-xs py-4" '
            f'style="color:var(--text-muted);">{t("dash.empty_queue", lang=lang)}</td></tr>'
        )

    queue = await get_smart_queue(
        db, user_id=_parse_user_id(user), role=role, dept_id=user_dept,
        page=page, queue_filter="specialized",
        filter_agent_id=_parse_filter_uuid(agent_id),
        filter_dept_id=_parse_filter_uuid(dept_id),
    )
    return templates.TemplateResponse("dashboard/_queue_rows.html", _queue_ctx(request, queue))


@router.get("/api/tickets/queues/supervisor", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("supervisor.view"))])
async def queue_supervisor(
    request: Request, page: int = 1,
    agent_id: Optional[str] = None, dept_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    queue = await get_smart_queue(
        db, user_id=_parse_user_id(user), role=user.get("role", "supervisor"),
        page=page, queue_filter="supervisor",
        filter_agent_id=_parse_filter_uuid(agent_id),
        filter_dept_id=_parse_filter_uuid(dept_id),
    )
    return templates.TemplateResponse("dashboard/_queue_rows.html", _queue_ctx(request, queue))


@router.get("/api/tickets/queues/manager", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("manager.view"))])
async def queue_manager(
    request: Request, page: int = 1,
    agent_id: Optional[str] = None, dept_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    queue = await get_smart_queue(
        db, user_id=_parse_user_id(user), role=user.get("role", "manager"),
        page=page, queue_filter="manager",
        filter_agent_id=_parse_filter_uuid(agent_id),
        filter_dept_id=_parse_filter_uuid(dept_id),
    )
    return templates.TemplateResponse("dashboard/_queue_rows.html", _queue_ctx(request, queue))


@router.get("/api/tickets/queues/internal_tickets", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("tickets.view"))])
async def queue_internal_tickets(
    request: Request, page: int = 1,
    agent_id: Optional[str] = None, dept_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    queue = await get_smart_queue(
        db, user_id=_parse_user_id(user), role=user.get("role", "employee"),
        page=page, queue_filter="internal_tickets",
        filter_agent_id=_parse_filter_uuid(agent_id),
        filter_dept_id=_parse_filter_uuid(dept_id),
    )
    return templates.TemplateResponse("dashboard/_queue_rows.html", _queue_ctx(request, queue))


@router.get("/api/tickets/queues/mine", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("tickets.view"))])
async def queue_mine(
    request: Request, page: int = 1,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    queue = await get_smart_queue(
        db, user_id=_parse_user_id(user), role=user.get("role", "employee"),
        page=page, assigned_filter="mine",
    )
    ctx = _queue_ctx(request, queue)
    ctx["show_claim"] = False
    return templates.TemplateResponse("dashboard/_queue_rows.html", ctx)


def _parse_user_id(user: dict) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(user.get("sub", "")) if user.get("sub") else None
    except ValueError:
        return None


def _parse_dept_id(user: dict) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(user.get("department_id", "")) if user.get("department_id") else None
    except ValueError:
        return None


# ── POST /api/dashboard/claim/{ticket_id} ─────────────────────────────────────

@router.post("/api/dashboard/claim/{ticket_id}", response_class=HTMLResponse)
async def claim(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = getattr(request.state, "user", {}) or {}
    user_id_str = user.get("sub")
    lang = getattr(request.state, "lang", "ar")
    try:
        agent_id = uuid.UUID(user_id_str)
        tid      = uuid.UUID(ticket_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "invalid id")

    try:
        async with db.begin():
            ticket = await claim_ticket(db, tid, agent_id)
    except ValueError:
        return HTMLResponse(
            f'<tr><td colspan="6" class="text-center text-xs text-red-500 py-2">{t("errors.permission_denied", lang=lang)}</td></tr>'
        )

    return HTMLResponse(
        f'<tr class="bg-green-50 dark:bg-green-900/10">'
        f'<td colspan="6" class="text-center text-xs text-green-600 py-2">✅ {t("dash.claim", lang=lang)} — {ticket.ticket_number}</td>'
        f'</tr>'
    )


# ── POST /api/call-log ────────────────────────────────────────────────────────

_CALL_REASON_REDIS_KEY = "call_reason_fields_v2"
_DEFAULT_CALL_REASON_FIELDS: list[dict] = [
    {
        "id": "reason",
        "type": "select",
        "label_ar": "سبب الاتصال",
        "label_en": "Call Reason",
        "required": True,
        "options_ar": ["استفسار عام", "مشكلة تقنية", "شكوى", "طلب خدمة", "أخرى"],
        "options_en": ["General Inquiry", "Technical Issue", "Complaint", "Service Request", "Other"],
    }
]


async def _get_call_reason_fields(redis) -> list[dict]:
    import json as _json
    if redis:
        raw = await redis.get(_CALL_REASON_REDIS_KEY)
        if raw:
            return _json.loads(raw)
    return _DEFAULT_CALL_REASON_FIELDS


@router.get("/api/call-reason-config",
            dependencies=[Depends(require_permission("dashboard.view"))])
async def get_call_reason_config(
    request: Request,
    redis=Depends(get_redis),
) -> JSONResponse:
    fields = await _get_call_reason_fields(redis)
    return JSONResponse({"fields": fields})


@router.post("/api/call-reason-config",
             dependencies=[Depends(require_permission("manager.settings"))])
async def save_call_reason_config(
    request: Request,
    redis=Depends(get_redis),
) -> JSONResponse:
    import json as _json
    body = await request.json()
    fields = body.get("fields", [])
    # Validate each field
    allowed_types = ("text", "select", "checkbox", "textarea")
    cleaned = []
    for f in fields:
        if f.get("type") not in allowed_types:
            continue
        cleaned.append({
            "id": str(f.get("id", "")),
            "type": f["type"],
            "label_ar": str(f.get("label_ar", ""))[:100],
            "label_en": str(f.get("label_en", ""))[:100],
            "required": bool(f.get("required", False)),
            "options_ar": [str(o)[:100] for o in f.get("options_ar", [])],
            "options_en": [str(o)[:100] for o in f.get("options_en", [])],
        })
    if redis:
        await redis.set(_CALL_REASON_REDIS_KEY, _json.dumps(cleaned))
    return JSONResponse({"ok": True})


@router.get("/api/users/search",
            dependencies=[Depends(require_permission("dashboard.view"))])
async def search_users(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from sqlalchemy import select, or_
    from app.models.user import User
    if not q or len(q) < 2:
        return JSONResponse([])
    pattern = f"%{q}%"
    rows = (await db.execute(
        select(User.id, User.full_name_ar, User.full_name_en, User.employee_id, User.role)
        .where(
            User.deleted_at.is_(None),
            or_(
                User.full_name_ar.ilike(pattern),
                User.full_name_en.ilike(pattern),
                User.employee_id.ilike(pattern),
            ),
        )
        .limit(10)
    )).fetchall()
    return JSONResponse([
        {"id": str(r.id), "name_ar": r.full_name_ar, "name_en": r.full_name_en or r.full_name_ar,
         "employee_id": r.employee_id or "", "role": r.role}
        for r in rows
    ])


@router.get("/api/branch-employees/search",
            dependencies=[Depends(require_permission("dashboard.view"))])
async def search_branch_employees(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Search branch employees (callers) by name or employee ID."""
    from sqlalchemy import select, or_
    from app.models.branch import BranchEmployee, Branch
    if not q or len(q) < 2:
        return JSONResponse([])
    pattern = f"%{q}%"
    rows = (await db.execute(
        select(
            BranchEmployee.id,
            BranchEmployee.full_name_ar,
            BranchEmployee.full_name_en,
            BranchEmployee.employee_id,
            BranchEmployee.position_ar,
            BranchEmployee.phone,
            Branch.name_ar.label("branch_name_ar"),
        )
        .outerjoin(Branch, BranchEmployee.branch_id == Branch.id)
        .where(
            BranchEmployee.deleted_at.is_(None),
            BranchEmployee.is_active.is_(True),
            or_(
                BranchEmployee.full_name_ar.ilike(pattern),
                BranchEmployee.full_name_en.ilike(pattern),
                BranchEmployee.employee_id.ilike(pattern),
            ),
        )
        .limit(10)
    )).fetchall()
    return JSONResponse([
        {
            "id": str(r.id),
            "name_ar": r.full_name_ar,
            "name_en": r.full_name_en or r.full_name_ar,
            "employee_id": r.employee_id or "",
            "position": r.position_ar or "",
            "branch": r.branch_name_ar or "",
            "phone": r.phone or "",
        }
        for r in rows
    ])


@router.post("/api/call-log")
async def log_call(
    request: Request,
    reason: str = Form(""),
    reason_data: Optional[str] = Form(None),
    branch_employee_id: Optional[str] = Form(None),
    outcome: str = Form("resolved"),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    import json as _json
    from sqlalchemy import select
    from app.models.call_log import CallLog
    from app.models.user import User
    from app.models.branch import BranchEmployee
    from app.services.ticket import create_internal_ticket

    user = getattr(request.state, "user", {}) or {}
    agent_id_str = user.get("sub")
    lang = getattr(request.state, "lang", "ar")
    if not agent_id_str:
        raise HTTPException(401)
    try:
        agent_id = uuid.UUID(agent_id_str)
    except ValueError:
        raise HTTPException(400)

    branch_emp_uid: Optional[uuid.UUID] = None
    if branch_employee_id:
        try:
            branch_emp_uid = uuid.UUID(branch_employee_id)
        except ValueError:
            pass

    parsed_reason_data = None
    if reason_data:
        try:
            parsed_reason_data = _json.loads(reason_data)
        except Exception:
            parsed_reason_data = {"value": reason_data}
    elif reason:
        parsed_reason_data = {"value": reason}

    # Build a readable reason string for ticket subject
    reason_summary = ""
    if parsed_reason_data:
        parts = []
        for v in parsed_reason_data.values():
            if isinstance(v, list):
                parts.extend(v)
            elif v:
                parts.append(str(v))
        reason_summary = " | ".join(parts)

    # Caller name for ticket subject
    caller_name = ""
    if branch_emp_uid:
        be = await db.get(BranchEmployee, branch_emp_uid)
        if be:
            caller_name = be.full_name_ar if lang == "ar" else (be.full_name_en or be.full_name_ar)

    created_ticket_number: Optional[str] = None

    log = CallLog(
        id=uuid.uuid4(),
        agent_id=agent_id,
        branch_employee_id=branch_emp_uid,
        reason_data=parsed_reason_data,
        outcome=outcome,
        notes=notes or None,
        created_at=datetime.now(tz=UTC),
    )
    db.add(log)
    await db.flush()  # get log.id without committing

    if outcome == "followup":
        subj = f"متابعة مكالمة — {reason_summary}" if reason_summary else "متابعة مكالمة"
        desc = notes or reason_summary or "تذكرة متابعة داخلية"
        ticket = await create_internal_ticket(
            db, redis,
            subject=subj,
            description=desc,
            agent_id=agent_id,
            assigned_to=agent_id,
            queue="internal_tickets",
            caller_name=caller_name,
        )
        log.ticket_id = ticket.id
        created_ticket_number = ticket.ticket_number

    elif outcome == "ticket":
        # Place unassigned in internal_tickets — supervisor claims it themselves
        subj = f"طلب تذكرة من مكالمة — {reason_summary}" if reason_summary else "طلب تذكرة داخلية"
        desc = notes or reason_summary or "تذكرة داخلية تحتاج مراجعة المشرف"
        ticket = await create_internal_ticket(
            db, redis,
            subject=subj,
            description=desc,
            agent_id=agent_id,
            assigned_to=None,   # unassigned — supervisor claims from queue
            queue="internal_tickets",
            caller_name=caller_name,
        )
        log.ticket_id = ticket.id
        created_ticket_number = ticket.ticket_number

    await db.commit()
    return JSONResponse({"ok": True, "id": str(log.id),
                         "ticket_number": created_ticket_number})


# ── GET /api/call-logs (manager — list) ───────────────────────────────────────

@router.get("/api/call-logs",
            dependencies=[Depends(require_permission("manager.settings"))])
async def list_call_logs(
    request: Request,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from sqlalchemy import select, func
    from app.models.call_log import CallLog
    from app.models.user import User

    lang = getattr(request.state, "lang", "ar")
    page_size = 50
    offset = (page - 1) * page_size

    total = await db.scalar(select(func.count(CallLog.id)))

    rows = (await db.execute(
        select(CallLog)
        .order_by(CallLog.created_at.desc())
        .limit(page_size).offset(offset)
    )).scalars().all()

    result = []
    for r in rows:
        agent = await db.get(User, r.agent_id)
        caller = await db.get(User, r.caller_user_id) if r.caller_user_id else None
        result.append({
            "id": str(r.id),
            "agent": (agent.full_name_ar if lang == "ar" else (agent.full_name_en or agent.full_name_ar)) if agent else "—",
            "caller": (caller.full_name_ar if lang == "ar" else (caller.full_name_en or caller.full_name_ar)) if caller else "—",
            "outcome": r.outcome or "—",
            "reason_data": r.reason_data or {},
            "notes": r.notes or "",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        })
    return JSONResponse({"total": total or 0, "page": page, "rows": result})


# ── GET /api/call-logs/export (manager — Excel) ────────────────────────────────

@router.get("/api/call-logs/export",
            dependencies=[Depends(require_permission("manager.settings"))])
async def export_call_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    import io
    import json as _json
    from fastapi.responses import StreamingResponse
    from sqlalchemy import select
    from app.models.call_log import CallLog
    from app.models.user import User
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    lang = getattr(request.state, "lang", "ar")

    rows = (await db.execute(
        select(CallLog).order_by(CallLog.created_at.desc()).limit(10000)
    )).scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Call Logs"

    header_fill = PatternFill("solid", fgColor="0050A0")
    header_font = Font(color="FFFFFF", bold=True)
    headers = ["#", "التاريخ", "الموظف", "المتصل", "نتيجة المكالمة", "سبب الاتصال", "ملاحظات"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for i, r in enumerate(rows, 2):
        agent = await db.get(User, r.agent_id)
        caller = await db.get(User, r.caller_user_id) if r.caller_user_id else None
        reason_str = ""
        if r.reason_data:
            parts = []
            for k, v in r.reason_data.items():
                if isinstance(v, list):
                    parts.append(f"{k}: {', '.join(v)}")
                else:
                    parts.append(f"{k}: {v}")
            reason_str = " | ".join(parts)
        ws.append([
            i - 1,
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            (agent.full_name_ar if lang == "ar" else (agent.full_name_en or agent.full_name_ar)) if agent else "—",
            (caller.full_name_ar if lang == "ar" else (caller.full_name_en or caller.full_name_ar)) if caller else "—",
            r.outcome or "",
            reason_str,
            r.notes or "",
        ])

    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=call-logs.xlsx"},
    )


# ── GET /api/kb/search (quick search used in dashboard + ticket detail) ────────

@router.get("/api/kb/search",
            dependencies=[Depends(require_permission("kb.view"))])
async def kb_search(
    request: Request,
    q: str = "",
    category: Optional[str] = None,
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from sqlalchemy import select, or_
    from app.models.knowledge import KnowledgeArticle

    lang = getattr(request.state, "lang", "ar")
    if not q or len(q) < 2:
        return JSONResponse({"results": []})

    query = select(KnowledgeArticle).where(
        KnowledgeArticle.is_published.is_(True),
        KnowledgeArticle.deleted_at.is_(None),
        KnowledgeArticle.audience == "internal",
        or_(
            KnowledgeArticle.title_ar.ilike(f"%{q}%"),
            KnowledgeArticle.title_en.ilike(f"%{q}%"),
            KnowledgeArticle.content_ar.ilike(f"%{q}%"),
        ),
    ).limit(limit)

    if category:
        try:
            cat_id = uuid.UUID(category)
            query = query.where(KnowledgeArticle.category_id == cat_id)
        except ValueError:
            pass

    result = await db.execute(query)
    articles = result.scalars().all()

    return JSONResponse({
        "results": [
            {
                "id": str(a.id),
                "title": a.title_ar if lang == "ar" else (a.title_en or a.title_ar),
                "excerpt": (a.content_ar if lang == "ar" else (a.content_en or a.content_ar))[:120],
            }
            for a in articles
        ]
    })


# ── GET /api/notifications (panel partial) ───────────────────────────────────

@router.get("/api/notifications", response_class=HTMLResponse)
async def notifications_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from sqlalchemy import select
    from app.models.notification import Notification
    from app.services.notifications import NOTIF_ICONS

    user = getattr(request.state, "user", {}) or {}
    user_id_str = user.get("sub")
    lang = getattr(request.state, "lang", "ar")

    if not user_id_str:
        return HTMLResponse("")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return HTMLResponse("")

    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.deleted_at.is_(None))
        .order_by(Notification.created_at.desc())
        .limit(20)
    )
    notifs = result.scalars().all()

    if not notifs:
        empty = "لا توجد إشعارات" if lang == "ar" else "No notifications"
        return HTMLResponse(
            f'<div style="padding:32px 16px;text-align:center;color:var(--text-faint);font-size:13px;">'
            f'<div style="font-size:32px;margin-bottom:8px;">🔔</div>{empty}</div>'
        )

    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc)

    def time_ago(dt) -> str:
        if not dt:
            return ""
        diff = int((now - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else now - dt).total_seconds())
        if diff < 60:
            return ("الآن" if lang == "ar" else "just now")
        if diff < 3600:
            m = diff // 60
            return (f"منذ {m} د" if lang == "ar" else f"{m}m ago")
        if diff < 86400:
            h = diff // 3600
            return (f"منذ {h} س" if lang == "ar" else f"{h}h ago")
        d = diff // 86400
        return (f"منذ {d} ي" if lang == "ar" else f"{d}d ago")

    rows = []
    for n in notifs:
        icon  = NOTIF_ICONS.get(n.type or "system", "🔔")
        title = n.title_ar if lang == "ar" else (n.title_en or n.title_ar)
        body  = (n.body_ar if lang == "ar" else (n.body_en or n.body_ar)) or ""
        unread_bg = "background:rgba(0,174,239,0.06);border-inline-start:3px solid #00AEEF;" if not n.is_read else ""
        ticket_link = f'href="/tickets/{n.ticket_id}"' if n.ticket_id else ""
        tag = "a" if n.ticket_id else "div"
        rows.append(
            f'<{tag} {ticket_link} '
            f'hx-post="/api/notifications/{n.id}/read" hx-swap="none" '
            f'style="{unread_bg}display:flex;align-items:flex-start;gap:10px;padding:12px 16px;'
            f'border-bottom:1px solid var(--border-color,rgba(255,255,255,0.07));cursor:pointer;'
            f'text-decoration:none;transition:background 0.15s;" '
            f'onmouseover="this.style.background=\'rgba(0,174,239,0.04)\'" '
            f'onmouseout="this.style.background=\'{("rgba(0,174,239,0.06)" if not n.is_read else "")}\'">'
            f'<div style="font-size:20px;line-height:1;padding-top:2px;flex-shrink:0;">{icon}</div>'
            f'<div style="flex:1;min-width:0;">'
            f'<p style="margin:0;font-size:12px;font-weight:{"700" if not n.is_read else "500"};'
            f'color:var(--text-ink,#F1F5F9);line-height:1.3;">{title}</p>'
            f'{"<p style=\"margin:3px 0 0;font-size:11px;color:var(--text-muted,#94A3B8);\">" + body + "</p>" if body else ""}'
            f'<p style="margin:4px 0 0;font-size:10px;color:var(--text-faint,#64748B);">{time_ago(n.created_at)}</p>'
            f'</div>'
            f'</{tag}>'
        )

    mark_all_label = "تحديد الكل كمقروء" if lang == "ar" else "Mark all read"
    footer = (
        f'<div style="padding:10px 16px;border-top:1px solid var(--border-color,rgba(255,255,255,0.07));'
        f'text-align:center;">'
        f'<button hx-post="/api/notifications/read-all" hx-swap="none" '
        f'onclick="this.closest(\'[id=\\"notif-list\\"]\').innerHTML=\'<div style=\\"padding:24px;text-align:center;font-size:12px;color:var(--text-faint);\\">' + ("تم تحديد الكل كمقروء" if lang == "ar" else "All marked as read") + '</div>\'"'
        f'style="font-size:11px;font-weight:600;color:#00AEEF;background:none;border:none;cursor:pointer;">'
        f'{mark_all_label}</button></div>'
    )
    return HTMLResponse("".join(rows) + footer)


# ── POST /api/notifications/{id}/read ────────────────────────────────────────

@router.post("/api/notifications/{notif_id}/read")
async def mark_notification_read(
    notif_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.services.notifications import mark_one_read
    user = getattr(request.state, "user", {}) or {}
    uid_str = user.get("sub")
    if not uid_str:
        return JSONResponse({"ok": False})
    try:
        await mark_one_read(db, uuid.UUID(notif_id), uuid.UUID(uid_str))
        await db.commit()
    except Exception:
        pass
    return JSONResponse({"ok": True})


# ── POST /api/notifications/read-all ─────────────────────────────────────────

@router.post("/api/notifications/read-all")
async def mark_all_notifications_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.services.notifications import mark_all_read
    user = getattr(request.state, "user", {}) or {}
    uid_str = user.get("sub")
    if not uid_str:
        return JSONResponse({"ok": False})
    try:
        await mark_all_read(db, uuid.UUID(uid_str))
        await db.commit()
    except Exception:
        pass
    return JSONResponse({"ok": True})
