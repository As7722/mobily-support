"""
Knowledge Base Routes
---------------------
GET  /kb                          — Internal KB home
GET  /kb/new                      — New KB article (supervisor+)
GET  /kb/{article_id}             — Internal KB article detail
GET  /kb/{article_id}/edit        — Edit KB article (supervisor+)
GET  /api/kb/search-html          — Internal KB HTMX search partial
POST /api/kb/articles             — Create article (supervisor+)
PUT  /api/kb/articles/{id}        — Edit article (supervisor+)
DELETE /api/kb/articles/{id}      — Soft-delete (supervisor+)
POST /api/kb/articles/{id}/helpful     — Mark helpful
POST /api/kb/articles/{id}/not-helpful — Mark not helpful

GET  /portal/kb                   — Portal KB home (branch employees)
GET  /portal/kb/{article_id}      — Portal KB article detail
GET  /api/portal/kb/search-html   — Portal KB HTMX search partial
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.templates import templates
from app.i18n import t
from app.models.category import Category
from app.models.knowledge import KnowledgeArticle

router = APIRouter()
UTC = timezone.utc
KB_AUDIENCES = {"internal", "portal"}
KB_UPLOADS_DIR = os.path.join("app", "uploads", "kb")
KB_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _ctx(request: Request, **extra) -> dict:
    lang = getattr(request.state, "lang", "ar")
    return {
        "request": request,
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "dark_mode": request.cookies.get("dark_mode", "1") != "0",
        "now": datetime.now(tz=UTC),
        "unread_notifications": 0,
        "t": t,
        **extra,
    }


def _can_edit(request: Request) -> bool:
    user = getattr(request.state, "user", {}) or {}
    return user.get("role") in ("supervisor", "manager", "admin")


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "on", "yes"}


def _normalize_audience(value: Optional[str], fallback: str = "internal") -> str:
    audience = (value or fallback).strip().lower()
    if audience not in KB_AUDIENCES:
        return fallback
    return audience


async def _save_attachment(file: UploadFile) -> dict:
    payload = await file.read()
    if not payload:
        raise HTTPException(422, detail="Empty attachment")
    if len(payload) > KB_MAX_ATTACHMENT_BYTES:
        raise HTTPException(422, detail="Attachment too large")

    os.makedirs(KB_UPLOADS_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(KB_UPLOADS_DIR, stored_name)

    async with aiofiles.open(stored_path, "wb") as fh:
        await fh.write(payload)

    return {
        "attachment_file_name": file.filename or stored_name,
        "attachment_storage_key": stored_path,
        "attachment_mime_type": file.content_type or "application/octet-stream",
        "attachment_size_bytes": len(payload),
    }


# ── GET /kb ────────────────────────────────────────────────────────────────────

@router.get("/kb", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("kb.view"))])
async def kb_home(
    request: Request,
    q: str = "",
    category_id: str = "",
    audience: str = "internal",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    audience = _normalize_audience(audience, fallback="internal")
    if not _can_edit(request):
        audience = "internal"

    cats_q = await db.execute(
        select(Category)
        .where(Category.is_active.is_(True), Category.deleted_at.is_(None),
               Category.parent_id.is_(None))
        .order_by(Category.sort_order, Category.name_ar)
    )
    categories = list(cats_q.scalars().all())

    # Articles query
    stmt = (
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == audience,
        )
    )
    if q:
        search = f"%{q}%"
        stmt = stmt.where(
            or_(
                KnowledgeArticle.title_ar.ilike(search),
                KnowledgeArticle.title_en.ilike(search),
                KnowledgeArticle.content_ar.ilike(search),
                KnowledgeArticle.content_en.ilike(search),
            )
        )
    if category_id:
        try:
            stmt = stmt.where(KnowledgeArticle.category_id == uuid.UUID(category_id))
        except ValueError:
            pass

    stmt = stmt.order_by(KnowledgeArticle.view_count.desc()).limit(50)
    articles_q = await db.execute(stmt)
    articles = list(articles_q.scalars().all())

    # Stats
    total = await db.scalar(
        select(func.count(KnowledgeArticle.id))
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == audience,
        )
    ) or 0
    internal_total = await db.scalar(
        select(func.count(KnowledgeArticle.id))
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "internal",
        )
    ) or 0
    portal_total = await db.scalar(
        select(func.count(KnowledgeArticle.id))
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "portal",
        )
    ) or 0

    return templates.TemplateResponse(
        "kb/index.html",
        _ctx(
            request,
            articles=articles,
            categories=categories,
            search_query=q,
            selected_category=category_id,
            total_articles=total,
            can_edit=_can_edit(request),
            audience=audience,
            internal_total=internal_total,
            portal_total=portal_total,
            active_page="kb",
        ),
    )


# ── GET /kb/new ────────────────────────────────────────────────────────────────

@router.get("/kb/new", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("kb.edit"))])
async def kb_new_article(
    request: Request,
    audience: str = "internal",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if not _can_edit(request):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=getattr(request.state, "lang", "ar")))

    cats_q = await db.execute(
        select(Category).where(Category.is_active.is_(True), Category.deleted_at.is_(None))
        .order_by(Category.name_ar)
    )
    return templates.TemplateResponse(
        "kb/article_form.html",
        _ctx(request, article=None, categories=list(cats_q.scalars().all()),
             can_edit=True, active_page="kb", audience=_normalize_audience(audience)),
    )


@router.get("/kb/{article_id}/edit", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("kb.edit"))])
async def kb_edit_article(
    article_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if not _can_edit(request):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=getattr(request.state, "lang", "ar")))

    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))

    cats_q = await db.execute(
        select(Category).where(Category.is_active.is_(True), Category.deleted_at.is_(None))
        .order_by(Category.name_ar)
    )
    return templates.TemplateResponse(
        "kb/article_form.html",
        _ctx(
            request,
            article=article,
            categories=list(cats_q.scalars().all()),
            can_edit=True,
            active_page="kb",
            audience=article.audience,
        ),
    )


# ── GET /kb/{article_id} ───────────────────────────────────────────────────────

@router.get("/kb/{article_id}", response_class=HTMLResponse,
            dependencies=[Depends(require_permission("kb.view"))])
async def kb_article_detail(
    article_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))
    if article.audience != "internal" and not _can_edit(request):
        raise HTTPException(status_code=404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))

    # Increment view count
    article.view_count = (article.view_count or 0) + 1
    await db.commit()

    # Related articles from same category
    related = []
    if article.category_id:
        rel_q = await db.execute(
            select(KnowledgeArticle)
            .where(
                KnowledgeArticle.category_id == article.category_id,
                KnowledgeArticle.id != article.id,
                KnowledgeArticle.is_published.is_(True),
                KnowledgeArticle.deleted_at.is_(None),
                KnowledgeArticle.audience == article.audience,
            )
            .limit(5)
        )
        related = list(rel_q.scalars().all())

    return templates.TemplateResponse(
        "kb/article_detail.html",
        _ctx(request, article=article, related=related,
             can_edit=_can_edit(request), active_page="kb", audience=article.audience),
    )


@router.get("/kb/articles/{article_id}/attachment", response_class=FileResponse,
            dependencies=[Depends(require_permission("kb.view"))])
async def kb_internal_attachment(
    article_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
        )
    )
    article = result.scalar_one_or_none()
    if not article or not article.attachment_storage_key:
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))
    if article.audience != "internal" and not _can_edit(request):
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))
    if not os.path.exists(article.attachment_storage_key):
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))
    return FileResponse(
        article.attachment_storage_key,
        filename=article.attachment_file_name or "attachment",
        media_type=article.attachment_mime_type or "application/octet-stream",
    )


# ── HTMX Search partial ────────────────────────────────────────────────────────

@router.get("/api/kb/search-html", response_class=HTMLResponse)
async def kb_search(
    request: Request,
    q: str = "",
    audience: str = "internal",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    lang = getattr(request.state, "lang", "ar")
    audience = _normalize_audience(audience, fallback="internal")
    if not _can_edit(request):
        audience = "internal"
    if len(q) < 2:
        return HTMLResponse("")

    search = f"%{q}%"
    result = await db.execute(
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == audience,
            or_(
                KnowledgeArticle.title_ar.ilike(search),
                KnowledgeArticle.title_en.ilike(search),
            ),
        )
        .limit(8)
    )
    articles = list(result.scalars().all())

    title_field = "title_ar" if lang == "ar" else "title_en"
    rows = "".join(
        f'<a href="{"/portal/kb/" + str(a.id) if audience == "portal" else "/kb/" + str(a.id)}" class="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800 transition rounded-lg">'
        f'<svg class="w-4 h-4 text-primary shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>'
        f'<span class="text-sm text-gray-700 dark:text-gray-300">{getattr(a, title_field)}</span>'
        f'</a>'
        for a in articles
    ) if articles else f'<p class="px-4 py-3 text-sm text-gray-400">{t("kb.no_results", lang=lang)}</p>'

    return HTMLResponse(f'<div class="flex flex-col gap-1">{rows}</div>')


# ── POST /api/kb/articles — Create ────────────────────────────────────────────

@router.post("/api/kb/articles",
             dependencies=[Depends(require_permission("kb.edit"))])
async def kb_create_article(
    request: Request,
    title_ar: str = Form(...),
    title_en: str = Form(...),
    content_ar: str = Form(...),
    content_en: str = Form(...),
    category_id: str = Form(""),
    audience: str = Form("internal"),
    is_published: Optional[str] = Form(None),
    attachment: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    lang = getattr(request.state, "lang", "ar")
    user = getattr(request.state, "user", {}) or {}
    if not _can_edit(request):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))

    author_id = uuid.UUID(user["sub"]) if user.get("sub") else None
    article_audience = _normalize_audience(audience, fallback="internal")

    article = KnowledgeArticle(
        title_ar=title_ar,
        title_en=title_en,
        content_ar=content_ar,
        content_en=content_en,
        category_id=uuid.UUID(category_id) if category_id else None,
        author_id=author_id,
        is_published=_coerce_bool(is_published),
        audience=article_audience,
    )

    if attachment and attachment.filename:
        attachment_meta = await _save_attachment(attachment)
        article.attachment_file_name = attachment_meta["attachment_file_name"]
        article.attachment_storage_key = attachment_meta["attachment_storage_key"]
        article.attachment_mime_type = attachment_meta["attachment_mime_type"]
        article.attachment_size_bytes = attachment_meta["attachment_size_bytes"]

    db.add(article)
    await db.commit()
    await db.refresh(article)

    return JSONResponse({"ok": True, "id": str(article.id),
                         "message": t("kb.created", lang=lang)},
                        status_code=201)


@router.put("/api/kb/articles/{article_id}",
            dependencies=[Depends(require_permission("kb.edit"))])
async def kb_update_article(
    article_id: uuid.UUID,
    request: Request,
    title_ar: str = Form(...),
    title_en: str = Form(...),
    content_ar: str = Form(...),
    content_en: str = Form(...),
    category_id: str = Form(""),
    audience: str = Form("internal"),
    is_published: Optional[str] = Form(None),
    attachment: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    lang = getattr(request.state, "lang", "ar")
    if not _can_edit(request):
        raise HTTPException(403, detail=t("errors.permission_denied", lang=lang))

    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(404, detail=t("errors.not_found", lang=lang))

    article.title_ar = title_ar
    article.title_en = title_en
    article.content_ar = content_ar
    article.content_en = content_en
    article.category_id = uuid.UUID(category_id) if category_id else None
    article.audience = _normalize_audience(audience, fallback="internal")
    article.is_published = _coerce_bool(is_published)
    article.updated_at = datetime.now(tz=UTC)

    if attachment and attachment.filename:
        attachment_meta = await _save_attachment(attachment)
        article.attachment_file_name = attachment_meta["attachment_file_name"]
        article.attachment_storage_key = attachment_meta["attachment_storage_key"]
        article.attachment_mime_type = attachment_meta["attachment_mime_type"]
        article.attachment_size_bytes = attachment_meta["attachment_size_bytes"]

    await db.commit()
    return JSONResponse({"ok": True, "id": str(article.id), "message": t("kb.updated", lang=lang)})


# ── POST /api/kb/articles/{id}/helpful ────────────────────────────────────────

@router.post("/api/kb/articles/{article_id}/helpful")
async def kb_mark_helpful(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.id == article_id, KnowledgeArticle.deleted_at.is_(None))
    )
    article = result.scalar_one_or_none()
    if article:
        article.helpful_count = (article.helpful_count or 0) + 1
        await db.commit()
    return JSONResponse({"ok": True, "count": article.helpful_count if article else 0})


# ── POST /api/kb/articles/{id}/not-helpful ────────────────────────────────────

@router.post("/api/kb/articles/{article_id}/not-helpful")
async def kb_mark_not_helpful(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.id == article_id, KnowledgeArticle.deleted_at.is_(None))
    )
    article = result.scalar_one_or_none()
    if article:
        article.not_helpful_count = (article.not_helpful_count or 0) + 1
        await db.commit()
    return JSONResponse({"ok": True, "count": article.not_helpful_count if article else 0})


# ── DELETE /api/kb/articles/{id} ──────────────────────────────────────────────

@router.delete("/api/kb/articles/{article_id}",
               dependencies=[Depends(require_permission("kb.edit"))])
async def kb_delete_article(
    article_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    lang = getattr(request.state, "lang", "ar")
    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail=t("errors.not_found", lang=lang))

    article.deleted_at = datetime.now(tz=UTC)
    await db.commit()
    return JSONResponse({"ok": True})


# ── Portal (external) knowledge base ───────────────────────────────────────────

@router.get("/portal/kb", response_class=HTMLResponse)
async def portal_kb_home(
    request: Request,
    q: str = "",
    category_id: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    cats_q = await db.execute(
        select(Category)
        .where(Category.is_active.is_(True), Category.deleted_at.is_(None), Category.parent_id.is_(None))
        .order_by(Category.sort_order, Category.name_ar)
    )
    categories = list(cats_q.scalars().all())

    stmt = (
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "portal",
        )
    )
    if q:
        search = f"%{q}%"
        stmt = stmt.where(
            or_(
                KnowledgeArticle.title_ar.ilike(search),
                KnowledgeArticle.title_en.ilike(search),
                KnowledgeArticle.content_ar.ilike(search),
                KnowledgeArticle.content_en.ilike(search),
            )
        )
    if category_id:
        try:
            stmt = stmt.where(KnowledgeArticle.category_id == uuid.UUID(category_id))
        except ValueError:
            pass
    stmt = stmt.order_by(KnowledgeArticle.view_count.desc()).limit(60)
    articles = list((await db.execute(stmt)).scalars().all())

    total = await db.scalar(
        select(func.count(KnowledgeArticle.id)).where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "portal",
        )
    ) or 0

    return templates.TemplateResponse(
        "portal/kb_index.html",
        _ctx(
            request,
            articles=articles,
            categories=categories,
            search_query=q,
            selected_category=category_id,
            total_articles=total,
        ),
    )


@router.get("/portal/kb/{article_id}", response_class=HTMLResponse)
async def portal_kb_detail(
    article_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "portal",
            KnowledgeArticle.is_published.is_(True),
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))

    article.view_count = (article.view_count or 0) + 1
    await db.commit()

    related = []
    if article.category_id:
        rel_q = await db.execute(
            select(KnowledgeArticle).where(
                KnowledgeArticle.category_id == article.category_id,
                KnowledgeArticle.id != article.id,
                KnowledgeArticle.is_published.is_(True),
                KnowledgeArticle.deleted_at.is_(None),
                KnowledgeArticle.audience == "portal",
            ).limit(5)
        )
        related = list(rel_q.scalars().all())

    return templates.TemplateResponse(
        "portal/kb_detail.html",
        _ctx(request, article=article, related=related),
    )


@router.get("/portal/kb/articles/{article_id}/attachment", response_class=FileResponse)
async def portal_kb_attachment(
    article_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    result = await db.execute(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id,
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "portal",
            KnowledgeArticle.is_published.is_(True),
        )
    )
    article = result.scalar_one_or_none()
    if not article or not article.attachment_storage_key:
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))
    if not os.path.exists(article.attachment_storage_key):
        raise HTTPException(404, detail=t("errors.not_found", lang=getattr(request.state, "lang", "ar")))
    return FileResponse(
        article.attachment_storage_key,
        filename=article.attachment_file_name or "attachment",
        media_type=article.attachment_mime_type or "application/octet-stream",
    )


@router.get("/api/portal/kb/search-html", response_class=HTMLResponse)
async def portal_kb_search(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    lang = getattr(request.state, "lang", "ar")
    if len(q) < 2:
        return HTMLResponse("")

    search = f"%{q}%"
    result = await db.execute(
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_published.is_(True),
            KnowledgeArticle.deleted_at.is_(None),
            KnowledgeArticle.audience == "portal",
            or_(
                KnowledgeArticle.title_ar.ilike(search),
                KnowledgeArticle.title_en.ilike(search),
            ),
        )
        .limit(8)
    )
    articles = list(result.scalars().all())
    title_field = "title_ar" if lang == "ar" else "title_en"
    rows = "".join(
        f'<a href="/portal/kb/{a.id}" class="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800 transition rounded-lg">'
        f'<svg class="w-4 h-4 text-primary shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>'
        f'<span class="text-sm text-gray-700 dark:text-gray-300">{getattr(a, title_field) or a.title_ar}</span>'
        f'</a>'
        for a in articles
    ) if articles else f'<p class="px-4 py-3 text-sm text-gray-400">{t("kb.no_results", lang=lang)}</p>'

    return HTMLResponse(f'<div class="flex flex-col gap-1">{rows}</div>')
