"""
Internal Ticket Detail Routes (agents/supervisors/managers)
Separate from app/api/portal.py which handles public-facing ticket endpoints.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.redis import get_redis
from app.core.templates import templates
from app.i18n import t
from app.models.knowledge import CannedResponse, KnowledgeArticle
from app.models.ticket import Ticket
from app.models.ticket_timeline import TicketTimeline
from app.models.user import User
from app.services.sla import get_sla_elapsed_ratio, pause_sla, resume_sla
from app.services.ticket_service import (
    STATUS_TRANSITIONS,
    change_ticket_priority,
    change_ticket_status,
)
from app.services.timeline import EventType, add_event, get_public_timeline

router = APIRouter()
logger = logging.getLogger(__name__)
UTC = timezone.utc


def _require_agent(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401)
    return user


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


async def _get_ticket(db: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
    from app.models.ticket_timeline import TicketAttachment
    result = await db.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id, Ticket.deleted_at.is_(None))
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.category),
            selectinload(Ticket.branch),
            selectinload(Ticket.branch_employee),
            selectinload(Ticket.timeline).selectinload(TicketTimeline.actor),
            selectinload(Ticket.timeline).selectinload(TicketTimeline.attachments),
            selectinload(Ticket.attachments),
            selectinload(Ticket.sla_policy),
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404)
    return ticket


async def _can_employee_access_ticket(
    db: AsyncSession, ticket: Ticket, user_id: uuid.UUID, role: str
) -> bool:
    """Employees can only access: assigned to them, unassigned main, or specialized in their dept."""
    if role not in ("supervisor", "manager", "admin"):
        from app.services.queue import _get_user_dept_ids
        user_dept_ids = await _get_user_dept_ids(db, user_id)
        if ticket.assigned_to == user_id:
            return True
        if ticket.assigned_to is None and ticket.current_queue == "main":
            return True
        if ticket.assigned_to is None and ticket.current_queue == "specialized":
            return ticket.sub_queue_dept_id in user_dept_ids if user_dept_ids else False
        if ticket.current_queue == "internal_tickets" and ticket.assigned_to == user_id:
            return True
        if ticket.current_queue == "specialized" and ticket.sub_queue_dept_id in user_dept_ids:
            return True
        return False
    return True


async def _get_ticket_and_check_access(
    db: AsyncSession, ticket_id: uuid.UUID, request: Request
) -> Ticket:
    """Load ticket and enforce department/role access for employees."""
    ticket = await _get_ticket(db, ticket_id)
    user = getattr(request.state, "user", {}) or {}
    role = user.get("role", "employee")
    try:
        agent_id = uuid.UUID(user.get("sub", "")) if user.get("sub") else None
    except (ValueError, TypeError):
        agent_id = None
    if agent_id and not await _can_employee_access_ticket(db, ticket, agent_id, role):
        raise HTTPException(403, detail="Access denied to this ticket")
    return ticket


# ── GET /tickets ───────────────────────────────────────────────────────────────

@router.get("/tickets", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("tickets.view"))])
async def tickets_list(
    request: Request,
    queue: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.models.department import Department, UserDepartment

    user = getattr(request.state, "user", {}) or {}
    role = user.get("role", "employee")
    departments = []
    agents_list = []
    my_departments: list = []

    if role in ("supervisor", "manager", "admin"):
        dept_r = await db.execute(
            select(Department).where(Department.is_active.is_(True), Department.deleted_at.is_(None))
            .order_by(Department.name_ar)
        )
        departments = list(dept_r.scalars().all())

        ag_r = await db.execute(
            select(User).where(User.is_active.is_(True), User.deleted_at.is_(None), User.role == "employee")
            .order_by(User.full_name_ar).limit(200)
        )
        agents_list = list(ag_r.scalars().all())
    else:
        # Employee: load departments assigned via user_departments (many-to-many)
        try:
            user_id = uuid.UUID(user.get("sub", "")) if user.get("sub") else None
        except (ValueError, TypeError):
            user_id = None
        if user_id:
            dept_r = await db.execute(
                select(Department)
                .join(UserDepartment, UserDepartment.department_id == Department.id)
                .where(
                    UserDepartment.user_id == user_id,
                    Department.is_active.is_(True),
                    Department.deleted_at.is_(None),
                )
                .order_by(Department.name_ar)
            )
            my_departments = list(dept_r.scalars().all())

    has_department = (len(my_departments) > 0) if role == "employee" else (len(departments) > 0)

    return templates.TemplateResponse(
        "tickets/list.html",
        _ctx(
            request,
            user_role=role,
            has_department=has_department,
            active_queue=queue or "mine",
            departments=departments,
            my_departments=my_departments,
            agents_list=agents_list,
        ),
    )


# ── GET /tickets/{id} ─────────────────────────────────────────────────────────

@router.get("/tickets/{ticket_id}", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("tickets.view"))])
async def ticket_detail(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(404)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    lang   = getattr(request.state, "lang", "ar")

    # SLA info
    sla_ratio = get_sla_elapsed_ratio(ticket)
    if ticket.sla_deadline:
        now = datetime.now(tz=UTC)
        remaining_secs = max(0, (ticket.sla_deadline - now).total_seconds())
        h, m = int(remaining_secs // 3600), int((remaining_secs % 3600) // 60)
        sla_remaining = f"{h}h {m}m" if h else f"{m}m"
    else:
        sla_remaining = "—"

    # Timeline (full — internal notes visible to agents)
    from app.models.ticket_timeline import TicketTimeline
    tl_result = await db.execute(
        select(TicketTimeline)
        .where(TicketTimeline.ticket_id == ticket.id)
        .options(
            selectinload(TicketTimeline.actor),
            selectinload(TicketTimeline.attachments),
        )
        .order_by(TicketTimeline.created_at)
    )
    timeline = list(tl_result.scalars().all())

    # Canned responses
    cr_result = await db.execute(
        select(CannedResponse).where(CannedResponse.is_active.is_(True)).limit(20)
    )
    canned = cr_result.scalars().all()
    canned_json = [
        {
            "id": str(c.id),
            "shortcut": c.shortcut,
            "name": c.name_ar if lang == "ar" else (c.name_en or c.name_ar),
            "content": c.content_ar if lang == "ar" else (c.content_en or c.content_ar),
        }
        for c in canned
    ]

    # KB articles related to this category
    kb_query = select(KnowledgeArticle).where(
        KnowledgeArticle.is_published.is_(True),
        KnowledgeArticle.deleted_at.is_(None),
        KnowledgeArticle.audience == "internal",
    ).limit(8)
    if ticket.category_id:
        kb_query = kb_query.where(KnowledgeArticle.category_id == ticket.category_id)
    kb_result = await db.execute(kb_query)
    kb_articles = [
        {
            "id": str(a.id),
            "title": a.title_ar if lang == "ar" else (a.title_en or a.title_ar),
            "excerpt": (a.content_ar if lang == "ar" else (a.content_en or a.content_ar))[:100],
        }
        for a in kb_result.scalars().all()
    ]

    # Agents for transfer modal
    agents_result = await db.execute(
        select(User).where(User.is_active.is_(True), User.role == "employee", User.deleted_at.is_(None))
        .order_by(User.full_name_ar).limit(100)
    )
    agents = list(agents_result.scalars().all())

    # Departments for return-to-specialized
    from app.models.department import Department
    dept_result = await db.execute(
        select(Department).where(Department.is_active.is_(True), Department.deleted_at.is_(None))
        .order_by(Department.name_ar)
    )
    departments = list(dept_result.scalars().all())

    # Last escalator — the agent who escalated this ticket (for "return to escalator")
    last_escalator = None
    for ev in reversed(timeline):
        if ev.event_type == "escalated" and ev.actor_id:
            esc_result = await db.execute(
                select(User).where(User.id == ev.actor_id)
            )
            last_escalator = esc_result.scalar_one_or_none()
            break

    # Build readable labels for custom_fields
    custom_fields_display = _build_custom_fields_display(ticket.custom_fields or {}, lang)

    return templates.TemplateResponse(
        "tickets/detail.html",
        _ctx(
            request,
            ticket=ticket,
            timeline=timeline,
            sla_ratio=sla_ratio,
            sla_remaining=sla_remaining,
            canned_responses=canned_json,
            kb_articles=kb_articles,
            agents=agents,
            departments=departments,
            last_escalator=last_escalator,
            custom_fields_display=custom_fields_display,
        ),
    )


_CUSTOM_FIELD_LABELS = {
    "department": {
        "_label": {"ar": "القسم المختص", "en": "Department"},
        "technical_support": {"ar": "الدعم التقني", "en": "Technical Support"},
        "user_management": {"ar": "إدارة اليوزرات", "en": "User Management"},
        "device_activation": {"ar": "التفعيل الخاطئ للأجهزة", "en": "Device Activation Error"},
        "absher": {"ar": "أبشر", "en": "Absher"},
    },
    "ts_problem_type": {
        "_label": {"ar": "نوع المشكلة", "en": "Problem Type"},
        "fingerprint": {"ar": "بصمة", "en": "Fingerprint"},
        "package_change": {"ar": "تغيير الباقة", "en": "Package Change"},
        "new_activation": {"ar": "تفعيل جديد", "en": "New Activation"},
        "ownership_transfer": {"ar": "نقل ملكية", "en": "Ownership Transfer"},
        "other": {"ar": "أخرى", "en": "Other"},
    },
    "um_problem_type": {
        "_label": {"ar": "نوع المشكلة", "en": "Problem Type"},
        "fingerprint_error": {"ar": "خطأ بصمة", "en": "Fingerprint Error"},
        "reader": {"ar": "قارئ البصمة", "en": "Fingerprint Reader"},
        "system_access": {"ar": "مشكلة دخول لنظام", "en": "System Access Issue"},
        "user_auth": {"ar": "مشكلة توثيق اليوزر", "en": "User Auth Issue"},
        "other": {"ar": "أخرى", "en": "Other"},
    },
    "device_problem_type": {
        "_label": {"ar": "نوع المشكلة", "en": "Problem Type"},
        "mobile": {"ar": "تفعيل جوال بالخطأ", "en": "Wrong Mobile Activation"},
        "router": {"ar": "تفعيل راوتر بالخطأ", "en": "Wrong Router Activation"},
    },
    "activation_type": {
        "_label": {"ar": "نوع التفعيل", "en": "Activation Type"},
        "display": {"ar": "بعرض", "en": "Display"},
        "cash": {"ar": "كاش", "en": "Cash"},
    },
    "absher_problem_type": {
        "_label": {"ar": "نوع المشكلة", "en": "Problem Type"},
        "absher_app": {"ar": "مشكلة تطبيق أبشر", "en": "Absher App Issue"},
        "fingerprint_reader": {"ar": "مشكلة قارئ البصمة", "en": "Fingerprint Reader Issue"},
        "tablet_issue": {"ar": "مشكلة التابلت", "en": "Tablet Issue"},
        "charger_issue": {"ar": "مشكلة شاحن التابلت", "en": "Tablet Charger Issue"},
    },
    "absher_tablet_number": {"_label": {"ar": "رقم التابلت", "en": "Tablet Number"}},
    "ts_error_number":  {"_label": {"ar": "رقم الخطأ", "en": "Error Number"}},
    "um_error_number":  {"_label": {"ar": "رقم الخطأ", "en": "Error Number"}},
    "um_reader_number": {"_label": {"ar": "رقم القارئ", "en": "Reader Number"}},
    "device_number":    {"_label": {"ar": "رقم الجهاز", "en": "Device Number"}},
    "customer_number":  {"_label": {"ar": "رقم العميل / الحساب", "en": "Customer / Account Number"}},
    "contact_phone":    {"_label": {"ar": "رقم جوال التواصل", "en": "Contact Phone"}},
    "contact_name":     {"_label": {"ar": "اسم شخص التواصل", "en": "Contact Name"}},
}


def _build_custom_fields_display(custom_fields: dict, lang: str) -> list[dict]:
    result = []
    for key, raw_value in custom_fields.items():
        if not raw_value:
            continue
        meta = _CUSTOM_FIELD_LABELS.get(key, {})
        label = meta.get("_label", {}).get(lang, key)
        value_label = meta.get(raw_value, {}).get(lang, raw_value) if isinstance(meta.get(raw_value), dict) else raw_value
        result.append({"key": key, "label": label, "value": value_label, "raw": raw_value})
    return result


# ── POST /api/tickets/{id}/reply ──────────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/reply", response_class=HTMLResponse)
async def reply(
    ticket_id: str,
    request: Request,
    content: str = Form(...),
    is_internal: str = Form("0"),
    version: int = Form(1),
    attachment: Optional[UploadFile] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from fastapi import UploadFile as _UF  # re-import for optional param
    user = _require_agent(request)
    lang = getattr(request.state, "lang", "ar")
    try:
        tid = uuid.UUID(ticket_id)
        agent_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    internal = is_internal == "1"
    event_type = EventType.REPLY_INTERNAL if internal else EventType.REPLY_EXTERNAL

    event = await add_event(
        db,
        ticket_id=tid,
        event_type=event_type,
        content_ar=content,
        content_en=content,
        actor_id=agent_id,
        actor_type="agent",
        is_public=not internal,
    )
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.TICKET_COMMENT,
        resource_type="tickets", resource_id=tid,
        new_value={
            "ticket_number": ticket.ticket_number,
            "source": "internal" if internal else "external",
            "content_length": len((content or "").strip()),
            "has_attachment": bool(attachment and attachment.filename),
        },
    )
    ticket.updated_at = datetime.now(tz=UTC)
    ticket.version += 1

    # Handle optional file attachment (store locally; path from settings for Windows/Docker)
    if attachment and attachment.filename:
        import os, aiofiles
        from app.models.ticket_timeline import TicketAttachment
        from app.core.config import settings
        upload_dir = settings.ticket_uploads_path
        os.makedirs(upload_dir, exist_ok=True)
        import re as _re
        clean_filename = _re.sub(r'[^\w\-.]', '_', os.path.basename(attachment.filename or "file"))
        safe_name = f"{uuid.uuid4().hex}_{clean_filename}"
        file_path = os.path.join(str(upload_dir), safe_name)
        file_bytes = await attachment.read()
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_bytes)
        att = TicketAttachment(
            id=uuid.uuid4(),
            ticket_id=tid,
            timeline_id=event.id,
            file_name=attachment.filename,
            file_size=len(file_bytes),
            mime_type=attachment.content_type or "application/octet-stream",
            s3_key=f"local/{safe_name}",
            s3_bucket="local",
            virus_scanned=True,
            virus_clean=True,
            uploaded_by=agent_id,
        )
        db.add(att)
        logger.info(
            "ticket_attachment_created",
            extra={"ticket_id": str(tid), "att_id": str(att.id), "s3_key": att.s3_key},
        )

    await db.flush()

    # Notify: assigned agent gets notified of new reply (if external and not self)
    if not internal and ticket.assigned_to and ticket.assigned_to != agent_id:
        try:
            from app.services.notifications import create_notification, NotifEvent
            await create_notification(
                db,
                user_id=ticket.assigned_to,
                event_type=NotifEvent.TICKET_REPLIED,
                ticket_id=tid,
                ticket_number=ticket.ticket_number or "",
            )
        except Exception:
            pass

    await db.commit()

    # Return updated timeline partial with new version in header
    partial = await _timeline_partial(db, tid, lang, request)
    partial.headers["X-Ticket-Version"] = str(ticket.version)
    return partial


# ── POST /api/tickets/{id}/status ────────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/status")
async def change_status(
    ticket_id: str,
    request: Request,
    status: str = Form(...),
    version: int = Form(1),
    reason: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    lang = getattr(request.state, "lang", "ar")
    try:
        tid = uuid.UUID(ticket_id)
        agent_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    if ticket.version != version:
        raise HTTPException(409, detail=t("ticket_detail.version_conflict", lang=lang))

    try:
        await change_ticket_status(
            db, ticket, status, agent_id,
            reason=reason, lang=lang,
            actor_role=user.get("role"),
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))

    await db.commit()

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/transfer ──────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/transfer")
async def transfer(
    ticket_id: str,
    request: Request,
    agent_id: str = Form(...),
    reason: Optional[str] = Form(None),
    version: int = Form(1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    try:
        tid      = uuid.UUID(ticket_id)
        new_agent = uuid.UUID(agent_id)
        acting   = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    if ticket.version != version:
        raise HTTPException(409)

    now = datetime.now(tz=UTC)
    ticket.assigned_to = new_agent
    ticket.assigned_at  = now
    ticket.updated_at   = now
    ticket.version     += 1
    await add_event(
        db, ticket_id=tid,
        event_type=EventType.TRANSFERRED,
        content_ar=f"تم التحويل — {reason or ''}",
        content_en=f"Transferred — {reason or ''}",
        actor_id=acting, actor_type="agent", is_public=False,
        metadata={"to_agent": str(new_agent), "reason": reason},
    )
    await db.flush()

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.TICKET_ASSIGN,
        resource_type="tickets", resource_id=tid,
        new_value={"ticket_number": ticket.ticket_number, "assigned_to": str(new_agent), "reason": reason},
    )

    # Notify new assignee
    try:
        from app.services.notifications import create_notification, NotifEvent
        await create_notification(
            db, user_id=new_agent,
            event_type=NotifEvent.TICKET_TRANSFERRED,
            ticket_id=tid, ticket_number=ticket.ticket_number or "",
        )
    except Exception:
        pass

    await db.commit()
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── PATCH /api/tickets/{id}/priority (Iron Rule #1: supervisor+ only) ────────

@router.patch("/api/tickets/{ticket_id}/priority")
async def update_priority(
    ticket_id: str,
    request: Request,
    priority: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    role = user.get("role", "employee")
    lang = getattr(request.state, "lang", "ar")
    try:
        tid      = uuid.UUID(ticket_id)
        actor_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    try:
        old_priority = ticket.priority
        await change_ticket_priority(db, ticket, priority, actor_id, role)
    except PermissionError:
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))
    else:
        from app.services.audit import log_from_request, AuditAction
        await log_from_request(
            db, request, AuditAction.TICKET_UPDATE,
            resource_type="tickets", resource_id=tid,
            old_value={"priority": old_priority},
            new_value={"priority": priority, "ticket_number": ticket.ticket_number},
        )

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/escalate ──────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/escalate")
async def escalate(
    ticket_id: str,
    request: Request,
    reason: str = Form(...),
    version: int = Form(1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """
    Iron Rule #4 escalation chain:
      employee   -> supervisor queue
      supervisor -> manager queue
      Employees cannot bypass supervisors.
    """
    user = _require_agent(request)
    role = user.get("role", "employee")
    lang = getattr(request.state, "lang", "ar")
    try:
        tid    = uuid.UUID(ticket_id)
        acting = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    now = datetime.now(tz=UTC)

    if role == "employee":
        target_queue = "supervisor"
    elif role == "supervisor":
        target_queue = "manager"
    elif role in ("manager", "admin"):
        target_queue = "manager"
    else:
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))

    if role == "employee" and ticket.current_queue == "supervisor":
        raise HTTPException(403, detail="Employees cannot escalate beyond supervisor queue")

    ticket.current_queue = target_queue
    ticket.updated_at    = now
    ticket.version      += 1
    await add_event(
        db, ticket_id=tid,
        event_type=EventType.ESCALATED,
        content_ar=f"تم التصعيد إلى {target_queue} — {reason}",
        content_en=f"Escalated to {target_queue} — {reason}",
        actor_id=acting, actor_type="agent", is_public=True,
        metadata={"reason": reason, "target_queue": target_queue},
    )
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.TICKET_ESCALATE,
        resource_type="tickets", resource_id=tid,
        new_value={"ticket_number": ticket.ticket_number, "target_queue": target_queue, "reason": reason},
    )
    await db.flush()

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/return-ticket (supervisor/manager de-escalate) ────

@router.post("/api/tickets/{ticket_id}/return-ticket")
async def return_ticket(
    ticket_id: str,
    request: Request,
    target: str = Form(...),
    agent_id: Optional[str] = Form(None),
    department_id: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
    version: int = Form(1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """
    Supervisor/Manager can return a ticket to:
      - 'queue_main'        → unassign and send back to main queue
      - 'queue_specialized' → send to specialized queue (with department_id)
      - 'agent'             → reassign to a specific agent (requires agent_id)
      - 'escalator'         → return to the agent who last escalated it
    """
    user = _require_agent(request)
    role = user.get("role", "employee")
    lang = getattr(request.state, "lang", "ar")

    if role not in ("supervisor", "manager", "admin"):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))

    try:
        tid    = uuid.UUID(ticket_id)
        acting = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    if ticket.version != version:
        raise HTTPException(409)

    now = datetime.now(tz=UTC)
    metadata_extra: dict = {"target": target, "reason": reason}

    if target == "queue_main":
        ticket.assigned_to  = None
        ticket.assigned_at  = None
        ticket.current_queue = "main"
        desc_ar = "تم إعادة التذكرة إلى الطابور العام"
        desc_en = "Ticket returned to main queue"

    elif target == "queue_specialized":
        ticket.assigned_to  = None
        ticket.assigned_at  = None
        ticket.current_queue = "specialized"
        if department_id:
            try:
                dept_uuid = uuid.UUID(department_id)
            except ValueError:
                raise HTTPException(400)
            ticket.category_id = None
            from app.models.department import Department
            dept = await db.get(Department, dept_uuid)
            dept_name = (dept.name_ar if lang == "ar" else dept.name_en) if dept else department_id
            desc_ar = f"تم إعادة التذكرة إلى قسم {dept_name}"
            desc_en = f"Ticket returned to department: {dept_name}"
            metadata_extra["department_id"] = department_id
        else:
            desc_ar = "تم إعادة التذكرة إلى طابور القسم المختص"
            desc_en = "Ticket returned to specialized queue"

    elif target == "escalator":
        from app.models.ticket_timeline import TicketTimeline as TL
        esc_result = await db.execute(
            select(TL).where(
                TL.ticket_id == tid,
                TL.event_type == "escalated",
            ).order_by(TL.created_at.desc()).limit(1)
        )
        esc_event = esc_result.scalar_one_or_none()
        if not esc_event or not esc_event.actor_id:
            raise HTTPException(422, detail="No escalation source found")
        ticket.assigned_to  = esc_event.actor_id
        ticket.assigned_at  = now
        ticket.current_queue = "main"
        escalator = await db.get(User, esc_event.actor_id)
        esc_name = (escalator.full_name_ar if lang == "ar" else (escalator.full_name_en or escalator.full_name_ar)) if escalator else str(esc_event.actor_id)
        desc_ar = f"تم إعادة التذكرة إلى الموظف المُحوِّل: {esc_name}"
        desc_en = f"Ticket returned to escalator: {esc_name}"
        metadata_extra["escalator_id"] = str(esc_event.actor_id)

    elif target == "agent" and agent_id:
        try:
            target_agent_id = uuid.UUID(agent_id)
        except ValueError:
            raise HTTPException(400)
        ticket.assigned_to  = target_agent_id
        ticket.assigned_at  = now
        ticket.current_queue = "main"
        desc_ar = "تم إعادة إسناد التذكرة إلى موظف"
        desc_en = "Ticket reassigned to agent"
        metadata_extra["agent_id"] = agent_id

    else:
        raise HTTPException(422, detail="Invalid target")

    if ticket.status in ("pending_customer", "pending_3rd"):
        ticket.status = "open"
        ticket.last_opened_at = now

    ticket.updated_at = now
    ticket.version   += 1

    await add_event(
        db, ticket_id=tid,
        event_type=EventType.TRANSFERRED,
        content_ar=f"{desc_ar} — {reason or ''}",
        content_en=f"{desc_en} — {reason or ''}",
        actor_id=acting, actor_type="agent", is_public=False,
        metadata=metadata_extra,
    )
    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.TICKET_ASSIGN,
        resource_type="tickets", resource_id=tid,
        new_value={"ticket_number": ticket.ticket_number, "target": target, "reason": reason, **metadata_extra},
    )
    await db.flush()

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/resolve ────────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/resolve")
async def resolve(
    ticket_id: str,
    request: Request,
    reason: Optional[str] = Form(None),
    version: int = Form(1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    lang = getattr(request.state, "lang", "ar")
    try:
        tid    = uuid.UUID(ticket_id)
        acting = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    try:
        await change_ticket_status(db, ticket, "resolved", acting, reason=reason, lang=lang)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/close ─────────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/close")
async def close(
    ticket_id: str,
    request: Request,
    reason: Optional[str] = Form(None),
    version: int = Form(1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    lang = getattr(request.state, "lang", "ar")
    try:
        tid    = uuid.UUID(ticket_id)
        acting = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    try:
        await change_ticket_status(db, ticket, "closed", acting, reason=reason, lang=lang)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/pause-sla ─────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/pause-sla")
async def pause_sla_endpoint(
    ticket_id: str,
    request: Request,
    reason: str = Form(...),
    version: int = Form(1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    try:
        tid    = uuid.UUID(ticket_id)
        acting = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    await pause_sla(db, ticket, reason, acting)
    await db.flush()

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── POST /api/tickets/{id}/resume-sla ────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/resume-sla")
async def resume_sla_endpoint(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = _require_agent(request)
    try:
        tid    = uuid.UUID(ticket_id)
        acting = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    ticket = await _get_ticket_and_check_access(db, tid, request)
    await resume_sla(db, ticket, acting)
    await db.flush()

    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/tickets/{ticket_id}"
    return r


# ── GET /api/tickets/{id}/attachments/{att_id} ───────────────────────────────

@router.get("/api/tickets/{ticket_id}/attachments/{att_id}")
async def download_attachment(
    ticket_id: str,
    att_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from fastapi.responses import FileResponse, StreamingResponse
    from app.models.ticket_timeline import TicketAttachment

    _require_agent(request)
    try:
        att_uuid = uuid.UUID(att_id)
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(404)

    await _get_ticket_and_check_access(db, tid, request)

    result = await db.execute(
        select(TicketAttachment).where(
            TicketAttachment.id == att_uuid,
            TicketAttachment.ticket_id == tid,
        )
    )
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(404)

    # Local storage: resolve key (support "local/xxx" and legacy plain key)
    import os
    from app.core.config import settings, BASE_DIR

    if not att.s3_key or not att.s3_key.strip():
        raise HTTPException(404, "File not available")

    raw_key = att.s3_key.replace("\\", "/").strip()
    if raw_key.startswith("local/"):
        key_suffix = raw_key[6:].lstrip("/")
    else:
        key_suffix = raw_key.lstrip("/")

    if not key_suffix:
        raise HTTPException(404, "File not available")

    def _try_path(path: str):
        if path and os.path.exists(path):
            return FileResponse(
                path,
                media_type=att.mime_type or "application/octet-stream",
                filename=att.file_name,
            )
        return None

    # 1) Current config path (project uploads/tickets or TICKET_UPLOADS_DIR)
    r = _try_path(str(settings.ticket_uploads_path / key_suffix))
    if r is not None:
        return r
    # 2) Default BASE_DIR/uploads/tickets (in case env points elsewhere)
    r = _try_path(str(BASE_DIR / "uploads" / "tickets" / key_suffix))
    if r is not None:
        return r
    # 3) Legacy path for old tickets (e.g. /app/uploads/tickets on Docker)
    legacy_path = os.path.join("/app", "uploads", "tickets", key_suffix)
    r = _try_path(legacy_path)
    if r is not None:
        return r

    logger.warning(
        "ticket_attachment_file_not_found",
        extra={
            "ticket_id": str(tid),
            "att_id": str(att_uuid),
            "s3_key": att.s3_key,
            "tried_paths": [
                str(settings.ticket_uploads_path / key_suffix),
                str(BASE_DIR / "uploads" / "tickets" / key_suffix),
                legacy_path,
            ],
        },
    )
    raise HTTPException(404, "File not available")


# ── Helper: render timeline partial ──────────────────────────────────────────

async def _timeline_partial(
    db: AsyncSession,
    ticket_id: uuid.UUID,
    lang: str,
    request: Request,
) -> HTMLResponse:
    from app.models.ticket_timeline import TicketTimeline

    tl_result = await db.execute(
        select(TicketTimeline)
        .where(TicketTimeline.ticket_id == ticket_id)
        .options(
            selectinload(TicketTimeline.actor),
            selectinload(TicketTimeline.attachments),
        )
        .order_by(TicketTimeline.created_at)
    )
    timeline = list(tl_result.scalars().all())

    return templates.TemplateResponse(
        "tickets/_timeline_partial.html",
        {"request": request, "lang": lang, "timeline": timeline,
         "t": t, "format_date": templates.env.globals["format_date"],
         "bl": templates.env.globals["bl"]},
    )


# ── POST /api/tickets/merge ────────────────────────────────────────────────────

@router.post("/api/tickets/merge")
async def merge_tickets(
    request: Request,
    primary_id: str = Form(...),
    secondary_ids: str = Form(...),
    reason: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Merge secondary tickets into a primary ticket.
    - Secondary tickets are closed and linked via parent_ticket_id.
    - Public replies from secondaries are copied to the primary timeline.
    - Permanent, cannot be undone (Zendesk/Freshdesk pattern).
    Requires supervisor+ permission.
    """
    user = _require_agent(request)
    role = user.get("role", "employee")
    if role not in ("supervisor", "manager", "admin"):
        raise HTTPException(403)
    lang = getattr(request.state, "lang", "ar")

    try:
        p_id = uuid.UUID(primary_id)
        s_ids = [uuid.UUID(s.strip()) for s in secondary_ids.split(",") if s.strip()]
        actor_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400, "Invalid ticket IDs")

    if not s_ids:
        raise HTTPException(400, "No secondary tickets provided")
    if p_id in s_ids:
        raise HTTPException(400, "Cannot merge a ticket into itself")

    from app.models.ticket_timeline import TicketTimeline

    parent_q = await db.execute(
        select(Ticket).where(Ticket.id == p_id, Ticket.deleted_at.is_(None))
    )
    parent = parent_q.scalar_one_or_none()
    if not parent:
        raise HTTPException(404, "Primary ticket not found")

    now = datetime.now(tz=UTC)
    merged_numbers = []

    for child_id in s_ids:
        child_q = await db.execute(
            select(Ticket).where(Ticket.id == child_id, Ticket.deleted_at.is_(None))
        )
        child = child_q.scalar_one_or_none()
        if not child:
            continue

        if child.status in ("closed", "archived"):
            continue

        merged_numbers.append(child.ticket_number)

        # Copy public replies from child to parent timeline
        tl_q = await db.execute(
            select(TicketTimeline).where(
                TicketTimeline.ticket_id == child_id,
                TicketTimeline.event_type.in_(("reply_external", "reply_customer")),
                TicketTimeline.is_public.is_(True),
            ).order_by(TicketTimeline.created_at)
        )
        for entry in tl_q.scalars().all():
            db.add(TicketTimeline(
                id=uuid.uuid4(),
                ticket_id=p_id,
                event_type=entry.event_type,
                actor_id=entry.actor_id,
                content_ar=entry.content_ar,
                content_en=entry.content_en,
                is_public=True,
                created_at=entry.created_at,
            ))

        child.status = "closed"
        child.parent_ticket_id = p_id
        child.resolved_at = now
        child.closed_at = now
        child.updated_at = now

        db.add(TicketTimeline(
            id=uuid.uuid4(),
            ticket_id=child_id,
            event_type=EventType.MERGED,
            actor_id=actor_id,
            content_ar=f"دُمجت في التذكرة {parent.ticket_number}",
            content_en=f"Merged into ticket {parent.ticket_number}",
            is_public=True,
        ))

    reason_text = f" — {reason}" if reason else ""
    merged_list = ", ".join(merged_numbers) if merged_numbers else "—"
    db.add(TicketTimeline(
        id=uuid.uuid4(),
        ticket_id=p_id,
        event_type=EventType.MERGED,
        actor_id=actor_id,
        content_ar=f"تم دمج {len(merged_numbers)} تذكرة ({merged_list}){reason_text}",
        content_en=f"{len(merged_numbers)} ticket(s) merged ({merged_list}){reason_text}",
        is_public=False,
    ))

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.TICKET_MERGE,
        resource_type="tickets", resource_id=p_id,
        new_value={"merged_tickets": merged_numbers, "reason": reason},
    )
    await db.flush()

    return JSONResponse({"ok": True, "parent_id": str(p_id), "merged_count": len(merged_numbers)})


# ── POST /api/tickets/{id}/split ──────────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/split")
async def split_ticket(
    ticket_id: str,
    request: Request,
    subject: str = Form(...),
    reason: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    """
    Split: create a child ticket linked to the parent.
    Copies priority, category, channel, branch, submitter info from parent.
    Requires supervisor+ permission.
    """
    user = _require_agent(request)
    role = user.get("role", "employee")
    if role not in ("supervisor", "manager", "admin"):
        raise HTTPException(403)
    lang = getattr(request.state, "lang", "ar")

    try:
        parent_id = uuid.UUID(ticket_id)
        actor_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(400)

    parent = await _get_ticket_and_check_access(db, parent_id, request)

    from app.services.ticket import generate_ticket_number
    from app.services.sla import calculate_sla_deadline
    from app.models.ticket_timeline import TicketTimeline
    import secrets

    now = datetime.now(tz=UTC)
    ticket_num = await generate_ticket_number(redis)
    sla_deadline = await calculate_sla_deadline(db, parent.priority, now)
    description = reason if reason.strip() else f"Split from {parent.ticket_number}"

    child = Ticket(
        id=uuid.uuid4(),
        ticket_number=ticket_num,
        public_token=secrets.token_urlsafe(32),
        csat_token=secrets.token_urlsafe(24),
        subject=subject,
        description=description,
        status="new",
        priority=parent.priority,
        channel=parent.channel,
        category_id=parent.category_id,
        branch_id=parent.branch_id,
        submitter_name=parent.submitter_name,
        submitter_name_ar=parent.submitter_name_ar,
        submitter_name_en=parent.submitter_name_en,
        submitter_phone=parent.submitter_phone,
        submitter_email=parent.submitter_email,
        submitted_by_id=parent.submitted_by_id,
        parent_ticket_id=parent_id,
        sla_deadline=sla_deadline,
        sla_breached=False,
        current_queue="main",
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(child)

    db.add(TicketTimeline(
        id=uuid.uuid4(),
        ticket_id=child.id,
        event_type=EventType.CREATED,
        actor_id=actor_id,
        content_ar=f"تم إنشاء التذكرة بالتقسيم من {parent.ticket_number}",
        content_en=f"Created by splitting from {parent.ticket_number}",
        is_public=True,
    ))

    db.add(TicketTimeline(
        id=uuid.uuid4(),
        ticket_id=parent_id,
        event_type=EventType.SPLIT,
        actor_id=actor_id,
        content_ar=f"تم تقسيم التذكرة — أُنشئت {ticket_num}",
        content_en=f"Ticket split — created {ticket_num}",
        is_public=False,
    ))

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.TICKET_SPLIT,
        resource_type="tickets", resource_id=parent_id,
        new_value={"child_ticket": ticket_num, "reason": reason},
    )
    await db.flush()

    return JSONResponse({
        "ok": True,
        "child_id": str(child.id),
        "ticket_number": ticket_num,
    })


# ── GET /api/tickets/search ─────────────────────────────────────────────────

@router.get("/api/tickets/search",
            dependencies=[Depends(require_permission("tickets.view"))])
async def search_tickets(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Quick ticket search by number or subject — used by merge UI."""
    from sqlalchemy import or_

    if len(q) < 2:
        return JSONResponse({"tickets": []})

    result = await db.execute(
        select(Ticket)
        .where(
            Ticket.deleted_at.is_(None),
            Ticket.status.notin_(["closed", "archived"]),
            or_(
                Ticket.ticket_number.ilike(f"%{q}%"),
                Ticket.subject.ilike(f"%{q}%"),
            ),
        )
        .order_by(Ticket.created_at.desc())
        .limit(15)
    )
    tickets = result.scalars().all()
    return JSONResponse({
        "tickets": [
            {
                "id": str(tk.id),
                "ticket_number": tk.ticket_number,
                "subject": tk.subject or "",
                "status": tk.status,
                "priority": tk.priority,
            }
            for tk in tickets
        ]
    })


# ── POST /api/tickets/{id}/watchers ───────────────────────────────────────────

@router.post("/api/tickets/{ticket_id}/watchers")
async def add_watcher(
    ticket_id: str,
    request: Request,
    watcher_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a watcher (observer) to a ticket."""
    user = _require_agent(request)
    lang = getattr(request.state, "lang", "ar")

    try:
        tid = uuid.UUID(ticket_id)
        wid = uuid.UUID(watcher_id)
    except ValueError:
        raise HTTPException(400)

    await _get_ticket_and_check_access(db, tid, request)

    # Store in ticket's watcher list (JSON field or association table)
    # Using a timeline note as a lightweight implementation
    from app.models.ticket_timeline import TicketTimeline
    from app.models.user import User

    watcher_q = await db.execute(select(User).where(User.id == wid, User.deleted_at.is_(None)))
    watcher = watcher_q.scalar_one_or_none()
    if not watcher:
        raise HTTPException(404, "Watcher user not found")

    try:
        actor_id = uuid.UUID(user["sub"])
    except (ValueError, KeyError):
        raise HTTPException(401)

    db.add(TicketTimeline(
        id=uuid.uuid4(),
        ticket_id=tid,
        event_type="watcher_added",
        actor_id=actor_id,
        content_ar=f"تمت إضافة {watcher.full_name_ar} كمراقب للتذكرة",
        content_en=f"{watcher.full_name_en or watcher.full_name_ar} added as a watcher",
        is_public=False,
    ))
    await db.flush()

    return {"ok": True, "watcher_id": str(wid)}


@router.delete("/api/tickets/{ticket_id}/watchers/{watcher_id}")
async def remove_watcher(
    ticket_id: str,
    watcher_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watcher from a ticket."""
    user = _require_agent(request)
    try:
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(400)
    await _get_ticket_and_check_access(db, tid, request)
    return {"ok": True}


# ── BULK ACTIONS (supervisor/manager) ─────────────────────────────────────────

def _require_supervisor(request: Request) -> dict:
    user = _require_agent(request)
    if user.get("role") not in ("supervisor", "manager", "admin"):
        raise HTTPException(403)
    return user


@router.post("/api/tickets/bulk/reassign")
async def bulk_reassign(
    request: Request,
    ticket_ids: str = Form(...),
    agent_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user = _require_supervisor(request)
    acting = uuid.UUID(user["sub"])
    target = uuid.UUID(agent_id)
    ids = [uuid.UUID(x.strip()) for x in ticket_ids.split(",") if x.strip()]
    now = datetime.now(tz=UTC)
    count = 0
    for tid in ids:
        result = await db.execute(select(Ticket).where(Ticket.id == tid, Ticket.deleted_at.is_(None)))
        ticket = result.scalar_one_or_none()
        if not ticket:
            continue
        ticket.assigned_to = target
        ticket.assigned_at = now
        ticket.current_queue = "main"
        ticket.updated_at = now
        ticket.version += 1
        await add_event(
            db, ticket_id=tid, event_type=EventType.TRANSFERRED,
            content_ar="إعادة إسناد جماعي", content_en="Bulk reassign",
            actor_id=acting, actor_type="agent", is_public=False,
            metadata={"bulk": True, "to_agent": str(target)},
        )
        count += 1
    await db.flush()
    return JSONResponse({"ok": True, "count": count})


@router.post("/api/tickets/bulk/move-to-queue")
async def bulk_move_to_queue(
    request: Request,
    ticket_ids: str = Form(...),
    target_queue: str = Form(...),
    department_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    user = _require_supervisor(request)
    acting = uuid.UUID(user["sub"])
    ids = [uuid.UUID(x.strip()) for x in ticket_ids.split(",") if x.strip()]
    if target_queue not in ("main", "specialized", "supervisor", "manager"):
        raise HTTPException(422, "Invalid queue")
    now = datetime.now(tz=UTC)
    count = 0
    for tid in ids:
        result = await db.execute(select(Ticket).where(Ticket.id == tid, Ticket.deleted_at.is_(None)))
        ticket = result.scalar_one_or_none()
        if not ticket:
            continue
        ticket.assigned_to = None
        ticket.assigned_at = None
        ticket.current_queue = target_queue
        ticket.updated_at = now
        ticket.version += 1
        await add_event(
            db, ticket_id=tid, event_type=EventType.TRANSFERRED,
            content_ar=f"نقل جماعي إلى {target_queue}", content_en=f"Bulk move to {target_queue}",
            actor_id=acting, actor_type="agent", is_public=False,
            metadata={"bulk": True, "target_queue": target_queue, "department_id": department_id},
        )
        count += 1
    await db.flush()
    return JSONResponse({"ok": True, "count": count})


@router.get("/api/tickets/bulk/export")
async def bulk_export(
    request: Request,
    ticket_ids: Optional[str] = None,
    queue: Optional[str] = None,
    agent_id: Optional[str] = None,
    department_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    _require_supervisor(request)
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    from io import BytesIO
    from starlette.responses import StreamingResponse

    query = select(Ticket).where(Ticket.deleted_at.is_(None))
    if ticket_ids:
        ids = [uuid.UUID(x.strip()) for x in ticket_ids.split(",") if x.strip()]
        query = query.where(Ticket.id.in_(ids))
    if queue:
        query = query.where(Ticket.current_queue == queue)
    if agent_id:
        query = query.where(Ticket.assigned_to == uuid.UUID(agent_id))

    query = query.options(selectinload(Ticket.assignee)).order_by(Ticket.created_at.desc()).limit(500)
    result = await db.execute(query)
    tickets = result.scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tickets"
    ws.append(["#", "Number", "Subject", "Status", "Priority", "Queue", "Assigned To", "Created"])
    for i, tk in enumerate(tickets, 1):
        assignee_name = ""
        if tk.assignee:
            assignee_name = tk.assignee.full_name_ar or ""
        ws.append([i, tk.ticket_number, tk.subject or "", tk.status, tk.priority, tk.current_queue,
                    assignee_name, str(tk.created_at)[:19] if tk.created_at else ""])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tickets_export.xlsx"},
    )
