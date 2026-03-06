"""
Public Portal Routes
--------------------
GET  /portal                  — Portal home (Submit / Track tabs)
POST /api/tickets/submit      — Create ticket from portal form
GET  /api/portal/track        — Track ticket by number or phone
GET  /api/portal/autofill     — Auto-fill submitter data by employee ID / phone
GET  /api/portal/subcategories— HTMX partial: sub-categories for a category
GET  /ticket/{token}          — Public ticket view
POST /api/tickets/{token}/reply — Customer reply
GET  /csat/{token}            — CSAT survey page
POST /api/csat/{token}/submit — Submit CSAT survey
GET  /status                  — System status page
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.templates import templates
from app.i18n import t
from app.models.branch import Branch
from app.models.category import Category
from app.models.system import SystemAlert
from app.models.ticket import Ticket
from app.models.ticket_timeline import TicketTimeline
from app.models.csat import CSATSurvey
from app.schemas.ticket import CSATSubmitForm, TicketSubmitForm, TicketSubmitResponse
from app.services.ticket import create_ticket, _enqueue_confirmation
from app.services.timeline import EventType, add_event, get_public_timeline

router = APIRouter()
UTC = timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lang(request: Request) -> str:
    return getattr(request.state, "lang", "ar")


def _tpl_ctx(request: Request, **extra) -> dict:
    """Build base template context every page needs."""
    lang = _lang(request)
    return {
        "request": request,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "dark_mode": request.cookies.get("dark_mode", "1") != "0",
        "now": datetime.now(tz=UTC),
        **extra,
    }


async def _get_active_alerts(db: AsyncSession) -> list[SystemAlert]:
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc)
    result = await db.execute(
        select(SystemAlert)
        .where(
            SystemAlert.is_active.is_(True),
            SystemAlert.starts_at <= now,
            or_(SystemAlert.ends_at.is_(None), SystemAlert.ends_at >= now),
        )
        .order_by(SystemAlert.severity.desc())
        .limit(3)
    )
    return list(result.scalars().all())


def _format_relative(dt: datetime, lang: str) -> str:
    now   = datetime.now(tz=UTC)
    delta = now - dt.replace(tzinfo=UTC) if dt.tzinfo is None else now - dt
    secs  = int(delta.total_seconds())
    if secs < 60:
        return t("timeline.just_now", lang=lang)
    if secs < 3600:
        return t("timeline.minutes_ago", lang=lang).replace("{n}", str(secs // 60))
    if secs < 86400:
        return t("timeline.hours_ago", lang=lang).replace("{n}", str(secs // 3600))
    return t("timeline.days_ago", lang=lang).replace("{n}", str(secs // 86400))


# ── GET /portal ────────────────────────────────────────────────────────────────

@router.get("/portal", response_class=HTMLResponse)
async def portal_home(
    request: Request,
    tab: str = "submit",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    lang = _lang(request)
    from app.models.form import FormVersion

    branches_q  = await db.execute(
        select(Branch).where(Branch.is_active.is_(True), Branch.deleted_at.is_(None))
        .order_by(Branch.name_ar)
    )
    categories_q = await db.execute(
        select(Category)
        .where(Category.parent_id.is_(None), Category.is_active.is_(True), Category.deleted_at.is_(None))
        .order_by(Category.sort_order, Category.name_ar)
    )
    alerts = await _get_active_alerts(db)

    # Load active form schema for dynamic rendering
    fv_result = await db.execute(
        select(FormVersion)
        .where(FormVersion.is_active.is_(True), FormVersion.deleted_at.is_(None))
        .order_by(FormVersion.version.desc())
        .limit(1)
    )
    active_form = fv_result.scalar_one_or_none()
    form_schema = (active_form.schema if active_form else None) or {}

    # Load active departments with portal_fields
    from app.models.department import Department
    import json as _json
    active_depts = list((await db.execute(
        select(Department).where(Department.is_active.is_(True), Department.deleted_at.is_(None))
        .order_by(Department.name_ar)
    )).scalars().all())
    departments_json = _json.dumps([{
        "code": d.code, "name_ar": d.name_ar, "name_en": d.name_en,
        "portal_fields": d.portal_fields or [],
    } for d in active_depts], ensure_ascii=False)

    return templates.TemplateResponse(
        "portal/index.html",
        _tpl_ctx(
            request,
            active_tab=tab,
            branches=list(branches_q.scalars().all()),
            categories=list(categories_q.scalars().all()),
            active_alerts=alerts,
            form_schema=form_schema,
            departments_json=departments_json,
        ),
    )


# ── GET /api/portal/subcategories  (HTMX partial) ────────────────────────────

@router.get("/api/portal/subcategories", response_class=HTMLResponse)
async def subcategories_partial(
    request: Request,
    category_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    lang = _lang(request)
    if not category_id:
        return HTMLResponse("")

    try:
        cat_uuid = uuid.UUID(category_id)
    except ValueError:
        return HTMLResponse("")

    result = await db.execute(
        select(Category)
        .where(Category.parent_id == cat_uuid, Category.is_active.is_(True), Category.deleted_at.is_(None))
        .order_by(Category.sort_order, Category.name_ar)
    )
    subs = list(result.scalars().all())
    if not subs:
        return HTMLResponse("")

    label = t("portal.subcategory", lang=lang)
    options = "".join(
        f'<option value="{s.id}">'
        f'{"" + s.name_ar if lang == "ar" else (s.name_en or s.name_ar)}'
        f"</option>"
        for s in subs
    )
    html = f"""
    <div class="sm:col-span-2">
      <label class="form-label">{label}</label>
      <select name="subcategory_id" class="form-input">
        <option value=""></option>
        {options}
      </select>
    </div>
    """
    return HTMLResponse(html)


# ── GET /api/portal/autofill ──────────────────────────────────────────────────

@router.get("/api/portal/autofill")
async def autofill_employee(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    """Lookup branch employee by employee_id, national ID, or phone."""
    from app.models.branch import BranchEmployee

    lang = _lang(request)
    q = q.strip()
    if not q or len(q) < 3:
        return JSONResponse({"found": False})

    # Rate limit: 30 lookups per IP per minute
    client_ip = request.client.host if request.client else "unknown"
    rl_key = f"rl:autofill:{client_ip}"
    count = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, 60)
    if count > 30:
        return JSONResponse({"found": False})

    result = await db.execute(
        select(BranchEmployee)
        .where(
            or_(
                BranchEmployee.employee_id == q,
                BranchEmployee.phone == q,
            ),
            BranchEmployee.is_active.is_(True),
            BranchEmployee.deleted_at.is_(None),
        )
        .options(selectinload(BranchEmployee.branch))
        .limit(1)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        return JSONResponse({"found": False})

    branch_name = ""
    if emp.branch:
        branch_name = emp.branch.name_ar if lang == "ar" else (emp.branch.name_en or emp.branch.name_ar)

    return JSONResponse({
        "found": True,
        "branch_employee_id": str(emp.id),
        "full_name_ar": emp.full_name_ar,
        "full_name_en": emp.full_name_en or emp.full_name_ar,
        "phone": emp.phone,
        "email": emp.email,
        "employee_id": emp.employee_id,
        "branch_id": str(emp.branch_id) if emp.branch_id else None,
        "branch_name": branch_name,
        "position": emp.position_ar if lang == "ar" else (emp.position_en or emp.position_ar or ""),
    })


@router.post("/api/portal/register-employee")
async def register_employee_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    """Create an internal ticket to register a new branch employee."""
    lang = _lang(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400)

    emp_name  = (body.get("name", "") or "").strip()
    emp_phone = (body.get("phone", "") or "").strip()
    emp_id    = (body.get("employee_id", "") or "").strip()

    if not emp_name or (not emp_phone and not emp_id):
        raise HTTPException(422, detail=t("errors.required_field", lang=lang))

    # Rate limit
    rl_key = f"reg_emp:{emp_phone or emp_id}"
    count = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, 86_400)
    if count > 3:
        raise HTTPException(429, detail=t("errors.rate_limited", lang=lang))

    # Create internal ticket for supervisor queue
    ticket_number = await _next_internal_ticket_number(redis)
    now = datetime.now(tz=UTC)

    ticket_kwargs = dict(
        id=uuid.uuid4(),
        ticket_number=ticket_number,
        submitter_name=emp_name,
        submitter_phone=emp_phone,
        employee_id=emp_id,
        subject=f"طلب تسجيل بيانات موظف فرع: {emp_name}" if lang == "ar" else f"Branch Employee Registration: {emp_name}",
        description=(
            f"طلب تسجيل بيانات موظف فرع جديد في النظام\n"
            f"الاسم: {emp_name}\n"
            f"الهاتف: {emp_phone}\n"
            f"الرقم الوظيفي: {emp_id}\n"
        ),
        priority="medium",
        status="new",
        channel="portal",
        current_queue="supervisor",
        public_token=uuid.uuid4().hex[:16],
        created_at=now,
        updated_at=now,
    )
    ticket = Ticket(**ticket_kwargs)
    db.add(ticket)

    from app.services.timeline import EventType, add_event

    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.CREATED,
        content_ar=f"تذكرة داخلية: طلب تسجيل بيانات موظف فرع ({emp_name})",
        content_en=f"Internal ticket: Branch employee registration request ({emp_name})",
        actor_type="system",
        is_public=False,
    )

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.PORTAL_REGISTER_EMPLOYEE,
        resource_type="tickets", resource_id=ticket.id,
        new_value={
            "ticket_number": ticket_number,
            "submitter_name": emp_name,
            "submitter_phone": emp_phone[:20] if emp_phone else None,
            "employee_id": emp_id[:50] if emp_id else None,
        },
    )

    await db.commit()

    msg = (
        "تم إرسال طلب تسجيل بياناتك بنجاح. سيتم التواصل معك قريباً."
        if lang == "ar" else
        "Your registration request has been submitted. You will be contacted soon."
    )
    return JSONResponse({
        "ok": True,
        "ticket_number": ticket_number,
        "message": msg,
    })


async def _next_internal_ticket_number(redis) -> str:
    counter = await redis.incr("ticket:internal_counter")
    return f"CS-INT-{counter:04d}"


# ── GET /api/portal/track ─────────────────────────────────────────────────────

@router.get("/api/portal/track")
async def track_ticket(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    lang = _lang(request)
    if not q:
        return JSONResponse({"found": False})

    # Rate limit: 20 track lookups per IP per minute
    client_ip = request.client.host if request.client else "unknown"
    rl_key = f"rl:track:{client_ip}"
    count = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, 60)
    if count > 20:
        return JSONResponse({"found": False})

    # Try ticket number first, then phone
    result = await db.execute(
        select(Ticket)
        .where(
            or_(
                Ticket.ticket_number == q.upper().strip(),
                Ticket.submitter_phone == q.strip(),
            ),
            Ticket.deleted_at.is_(None),
        )
        .options(selectinload(Ticket.assignee))
        .order_by(Ticket.created_at.desc())
        .limit(1)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        return JSONResponse({"found": False})

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.PORTAL_TRACK,
        resource_type="tickets", resource_id=ticket.id,
        new_value={"ticket_number": ticket.ticket_number, "lookup": (q or "")[:100]},
    )
    await db.commit()

    # Iron Rule #3: Only status + public replies visible to customers
    REPLY_TYPES = {"reply_external", "reply_customer"}
    events = await get_public_timeline(db, ticket.id)
    public_replies = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "content": e.content_ar if lang == "ar" else (e.content_en or e.content_ar),
            "created_at_label": _format_relative(e.created_at, lang),
            "actor_type": e.actor_type,
        }
        for e in events
        if e.event_type in REPLY_TYPES
    ]

    return JSONResponse({
        "found": True,
        "ticket_number": ticket.ticket_number,
        "token": ticket.public_token,
        "subject": ticket.subject,
        "status": ticket.status,
        "status_label": t(f"ticket.status.{ticket.status}", lang=lang),
        "replies": public_replies,
    })


# ── POST /api/tickets/submit ──────────────────────────────────────────────────

@router.post("/api/tickets/submit")
async def submit_ticket(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> JSONResponse:
    lang = _lang(request)
    from app.models.form import FormVersion

    form_data = await request.form()
    attachments = form_data.getlist("attachments")

    submitter_name      = form_data.get("submitter_name", "").strip()
    submitter_phone     = form_data.get("submitter_phone", "").strip()
    submitter_email     = form_data.get("submitter_email", "").strip() or None
    employee_id         = form_data.get("employee_id", "").strip() or None
    branch_employee_id  = form_data.get("branch_employee_id", "").strip() or None
    branch_id           = form_data.get("branch_id", "").strip() or None
    category_id         = form_data.get("category_id", "").strip() or None
    subcategory_id      = form_data.get("subcategory_id", "").strip() or None
    channel             = form_data.get("channel", "portal").strip() or "portal"
    subject             = form_data.get("subject", "").strip() or None
    description         = form_data.get("description", "").strip()

    # Fallbacks to ensure we always have usable values
    if not submitter_name:
        submitter_name = employee_id or (lang == "ar" and "موظف فرع" or "Branch Employee")
    if not submitter_phone:
        submitter_phone = "0000000000"

    if not branch_employee_id:
        raise HTTPException(422, detail=t("errors.employee_verification_required", lang=lang))

    if not description:
        raise HTTPException(422, detail=t("errors.required_field", lang=lang))

    # Rate-limit: max 5 ticket submissions per phone per day
    rl_key = f"portal_submit:{submitter_phone}"
    count  = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, 86_400)
    if count > 5:
        raise HTTPException(429, detail=t("errors.rate_limited", lang=lang))

    # Collect ALL custom_ prefixed fields from form data
    custom_fields = {}
    for key in form_data.keys():
        if not key.startswith("custom_"):
            continue
        fkey = key[7:]
        raw = form_data.get(key, "")
        if hasattr(raw, "strip"):
            raw = raw.strip()
        if raw:
            custom_fields[fkey] = raw

    try:
        form = TicketSubmitForm(
            submitter_name=submitter_name,
            submitter_phone=submitter_phone,
            submitter_email=submitter_email,
            employee_id=employee_id,
            branch_id=uuid.UUID(branch_id) if branch_id else None,
            category_id=uuid.UUID(category_id) if category_id else None,
            subcategory_id=uuid.UUID(subcategory_id) if subcategory_id else None,
            priority="medium",
            channel=channel,
            subject=subject,
            description=description,
        )
    except Exception as exc:
        err_str = str(exc).lower()
        if "description" in err_str:
            detail = "يرجى كتابة وصف للمشكلة (5 أحرف على الأقل)" if lang == "ar" else "Please describe the issue (min 5 chars)"
        else:
            detail = "حدث خطأ في البيانات المُدخلة" if lang == "ar" else "Invalid input data"
        raise HTTPException(422, detail=detail) from exc

    submitter_user_id: Optional[uuid.UUID] = None
    state_user = getattr(request.state, "user", None)
    if state_user:
        try:
            submitter_user_id = uuid.UUID(state_user.get("sub", ""))
        except (ValueError, AttributeError):
            pass

    ticket = await create_ticket(db, redis, form, submitter_user_id=submitter_user_id)

    from app.services.audit import log, AuditAction
    actor_id = None
    if submitter_user_id:
        try:
            actor_id = uuid.UUID(submitter_user_id) if isinstance(submitter_user_id, str) else submitter_user_id
        except (ValueError, TypeError):
            pass
    await log(
        db,
        AuditAction.TICKET_CREATE,
        actor_id=actor_id,
        actor_ip=request.client.host if request.client else None,
        resource_type="tickets",
        resource_id=ticket.id,
        new_value={"ticket_number": ticket.ticket_number, "source": "portal"},
    )

    if branch_employee_id:
        try:
            from app.models.branch import BranchEmployee
            emp_uuid = uuid.UUID(branch_employee_id)
            emp_check = await db.execute(
                select(BranchEmployee).where(BranchEmployee.id == emp_uuid, BranchEmployee.deleted_at.is_(None))
            )
            if emp_check.scalar_one_or_none():
                ticket.branch_employee_id = emp_uuid
        except (ValueError, Exception):
            pass

    if custom_fields and hasattr(ticket, "custom_fields"):
        ticket.custom_fields = custom_fields

    # Auto-route to department queue based on selected department
    dept_code = custom_fields.get("department", "")
    if dept_code and dept_code != "technical_support":
        from app.models.department import Department
        dept_result = await db.execute(
            select(Department).where(
                Department.code == dept_code,
                Department.is_active.is_(True),
                Department.deleted_at.is_(None),
            )
        )
        dept_obj = dept_result.scalar_one_or_none()
        if dept_obj:
            ticket.current_queue = "specialized"
            ticket.sub_queue_dept_id = dept_obj.id

    # Save attachments for new ticket (linked to CREATED timeline event)
    if attachments:
        import os
        import aiofiles
        import re as _re
        from sqlalchemy import desc
        from app.models.ticket_timeline import TicketAttachment
        from app.core.config import settings

        created_ev_result = await db.execute(
            select(TicketTimeline)
            .where(
                TicketTimeline.ticket_id == ticket.id,
                TicketTimeline.event_type == EventType.CREATED,
            )
            .order_by(desc(TicketTimeline.created_at))
            .limit(1)
        )
        created_event = created_ev_result.scalar_one_or_none()
        if created_event:
            MAX_SIZE = 10 * 1024 * 1024  # 10 MB
            ALLOWED = {
                "image/jpeg", "image/png", "image/gif", "image/webp",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/zip", "text/plain",
            }
            allowed_ext = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".txt"}
            upload_dir = settings.ticket_uploads_path
            os.makedirs(upload_dir, exist_ok=True)
            for upl in attachments:
                if not getattr(upl, "filename", None) or not upl.filename.strip():
                    continue
                try:
                    data = await upl.read()
                except Exception:
                    continue
                if len(data) > MAX_SIZE:
                    continue
                ct = getattr(upl, "content_type", None) or "application/octet-stream"
                if ct not in ALLOWED:
                    continue
                clean_name = os.path.basename(upl.filename or "file")
                ext = os.path.splitext(clean_name)[1]
                if ext.lower() not in allowed_ext:
                    ext = ".bin"
                file_key = f"{uuid.uuid4().hex}{ext}"
                file_path = os.path.join(str(upload_dir), file_key)
                try:
                    async with aiofiles.open(file_path, "wb") as f:
                        await f.write(data)
                except Exception:
                    continue
                att = TicketAttachment(
                    id=uuid.uuid4(),
                    ticket_id=ticket.id,
                    timeline_id=created_event.id,
                    file_name=upl.filename,
                    file_size=len(data),
                    mime_type=ct,
                    s3_key=f"local/{file_key}",
                    s3_bucket="local",
                )
                db.add(att)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    _enqueue_confirmation(ticket)

    return JSONResponse({
        "ticket_number": ticket.ticket_number,
        "ticket_id": str(ticket.id),
        "sla_deadline": ticket.sla_deadline.isoformat() if ticket.sla_deadline else None,
        "message": "ok",
    })


# ── GET /ticket/{token}  (public view) ────────────────────────────────────────

@router.get("/ticket/{token}", response_class=HTMLResponse)
async def public_ticket_view(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await db.execute(
        select(Ticket)
        .where(Ticket.public_token == token, Ticket.deleted_at.is_(None))
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.category),
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404)

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.PORTAL_VIEW,
        resource_type="tickets", resource_id=ticket.id,
        new_value={"ticket_number": ticket.ticket_number},
    )
    await db.commit()

    # Iron Rule #3: Only public replies visible to customer (no timeline, no routing)
    all_public = await get_public_timeline(db, ticket.id)
    public_replies = [e for e in all_public if e.event_type in ("reply_external", "reply_customer")]

    return templates.TemplateResponse(
        "portal/ticket_view.html",
        _tpl_ctx(request, ticket=ticket, timeline=public_replies),
    )


# ── POST /api/tickets/{token}/reply ──────────────────────────────────────────

@router.post("/api/portal/tickets/{token}/reply")
async def customer_reply(
    token: str,
    request: Request,
    content: str = Form(...),
    attachment: Optional[UploadFile] = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    import os
    import aiofiles
    from app.models.ticket_timeline import TicketAttachment

    lang = _lang(request)
    result = await db.execute(
        select(Ticket)
        .where(Ticket.public_token == token, Ticket.deleted_at.is_(None))
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.category),
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404)

    if ticket.status in ("closed", "archived"):
        raise HTTPException(422, detail=t("errors.ticket_closed", lang=lang))

    if len(content.strip()) < 1:
        raise HTTPException(422, detail=t("errors.required_field", lang=lang))

    event = await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.REPLY_CUSTOMER,
        content_ar=content,
        content_en=content,
        actor_type="customer",
        is_public=True,
    )

    from app.services.audit import log_from_request, AuditAction
    await log_from_request(
        db, request, AuditAction.PORTAL_REPLY,
        resource_type="tickets", resource_id=ticket.id,
        new_value={
            "ticket_number": ticket.ticket_number,
            "source": "portal",
            "content_length": len((content or "").strip()),
            "has_attachment": bool(attachment and attachment.filename),
        },
    )

    # Handle optional attachment
    if attachment and attachment.filename:
        MAX_SIZE = 10 * 1024 * 1024  # 10 MB
        ALLOWED = {
            "image/jpeg", "image/png", "image/gif", "image/webp",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip", "text/plain",
        }
        data = await attachment.read()
        if len(data) <= MAX_SIZE and attachment.content_type in ALLOWED:
            from app.core.config import settings
            upload_dir = settings.ticket_uploads_path
            os.makedirs(upload_dir, exist_ok=True)
            import re as _re
            clean_name = os.path.basename(attachment.filename or "file")
            ext = os.path.splitext(clean_name)[1]
            allowed_ext = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".txt"}
            if ext.lower() not in allowed_ext:
                ext = ".bin"
            file_key = f"{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(str(upload_dir), file_key)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(data)
            att = TicketAttachment(
                id=uuid.uuid4(),
                ticket_id=ticket.id,
                timeline_id=event.id if event else None,
                file_name=attachment.filename,
                mime_type=attachment.content_type or "application/octet-stream",
                file_size=len(data),
                s3_key=f"local/{file_key}",
                s3_bucket="local",
            )
            db.add(att)

    # If waiting on customer, flip back to open (with time tracking)
    if ticket.status == "pending_customer":
        ticket.status = "open"
        now = datetime.now(tz=UTC)
        ticket.last_opened_at = now
        ticket.updated_at = now
    await db.flush()
    await db.commit()

    # Return updated public timeline partial
    tl = await get_public_timeline(db, ticket.id)
    return templates.TemplateResponse(
        "portal/_timeline_partial.html",
        _tpl_ctx(request, timeline=tl, ticket=ticket),
    )


# ── GET /api/portal/tickets/{token}/attachments/{att_id} ─────────────────────

@router.get("/api/portal/tickets/{token}/attachments/{att_id}")
async def portal_download_attachment(
    token: str,
    att_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a ticket attachment by public token (no agent auth required)."""
    import os
    from fastapi.responses import FileResponse

    from app.models.ticket_timeline import TicketAttachment
    from app.core.config import settings

    try:
        att_uuid = uuid.UUID(att_id)
    except ValueError:
        raise HTTPException(404)

    ticket_result = await db.execute(
        select(Ticket).where(
            Ticket.public_token == token,
            Ticket.deleted_at.is_(None),
        )
    )
    ticket = ticket_result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404)

    att_result = await db.execute(
        select(TicketAttachment).where(
            TicketAttachment.id == att_uuid,
            TicketAttachment.ticket_id == ticket.id,
        )
    )
    att = att_result.scalar_one_or_none()
    if not att:
        raise HTTPException(404)

    from app.core.config import BASE_DIR

    if not att.s3_key or not att.s3_key.strip():
        raise HTTPException(404, "File not available")
    raw_key = att.s3_key.replace("\\", "/").strip()
    key_suffix = raw_key[6:].lstrip("/") if raw_key.startswith("local/") else raw_key.lstrip("/")
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

    r = _try_path(str(settings.ticket_uploads_path / key_suffix))
    if r is not None:
        return r
    r = _try_path(str(BASE_DIR / "uploads" / "tickets" / key_suffix))
    if r is not None:
        return r
    r = _try_path(os.path.join("/app", "uploads", "tickets", key_suffix))
    if r is not None:
        return r
    raise HTTPException(404, "File not available")


# ── GET /csat/{token} ─────────────────────────────────────────────────────────

@router.get("/csat/{token}", response_class=HTMLResponse)
async def csat_page(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await db.execute(
        select(CSATSurvey)
        .where(CSATSurvey.token == token)
        .options(selectinload(CSATSurvey.ticket))
    )
    survey = result.scalar_one_or_none()
    if not survey:
        raise HTTPException(404)

    now = datetime.now(tz=UTC)
    expired        = survey.token_expires_at and survey.token_expires_at < now
    already_submitted = survey.submitted_at is not None

    return templates.TemplateResponse(
        "portal/csat.html",
        _tpl_ctx(
            request,
            token=token,
            survey=survey,
            already_submitted=already_submitted,
            expired=expired,
            submitted=False,
        ),
    )


# ── POST /api/csat/{token}/submit ────────────────────────────────────────────

@router.post("/api/csat/{token}/submit")
async def csat_submit(
    token: str,
    request: Request,
    rating_overall:        int            = Form(...),
    rating_speed:          Optional[int]  = Form(None),
    rating_professionalism: Optional[int] = Form(None),
    rating_clarity:        Optional[int]  = Form(None),
    comments:              Optional[str]  = Form(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    lang = _lang(request)

    result = await db.execute(select(CSATSurvey).where(CSATSurvey.token == token))
    survey = result.scalar_one_or_none()
    if not survey:
        raise HTTPException(404)

    now = datetime.now(tz=UTC)
    if survey.submitted_at:
        raise HTTPException(409, detail=t("csat.already_submitted", lang=lang))
    if survey.token_expires_at and survey.token_expires_at < now:
        raise HTTPException(410, detail=t("csat.expired", lang=lang))

    if not (1 <= rating_overall <= 5):
        raise HTTPException(422, detail=t("csat.required_overall", lang=lang))

    async with db.begin():
        survey.rating_overall        = rating_overall
        survey.rating_speed          = rating_speed
        survey.rating_professionalism = rating_professionalism
        survey.rating_clarity        = rating_clarity
        survey.comments              = comments
        survey.submitted_at          = now

        if survey.ticket_id:
            ticket_r = await db.execute(select(Ticket).where(Ticket.id == survey.ticket_id))
            ticket   = ticket_r.scalar_one_or_none()
            if ticket:
                ticket.csat_score   = float(rating_overall)
                ticket.csat_comments = comments

                await add_event(
                    db,
                    ticket_id=ticket.id,
                    event_type=EventType.CSAT_RECEIVED,
                    content_ar=f"تم استلام تقييم CSAT — {rating_overall}/5",
                    content_en=f"CSAT received — {rating_overall}/5",
                    actor_type="customer",
                    is_public=False,
                )

                from app.services.audit import log_from_request, AuditAction
                await log_from_request(
                    db, request, AuditAction.PORTAL_CSAT_SUBMIT,
                    resource_type="tickets", resource_id=ticket.id,
                    new_value={
                        "ticket_number": ticket.ticket_number,
                        "rating_overall": rating_overall,
                        "rating_speed": rating_speed,
                        "rating_professionalism": rating_professionalism,
                        "rating_clarity": rating_clarity,
                        "has_comments": bool(comments and comments.strip()),
                    },
                )

    return JSONResponse({"ok": True})


