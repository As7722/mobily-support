"""
Immutable ticket timeline service.
Every ticket action (created, replied, escalated, resolved …) appends
one row to ticket_timeline.  Rows are NEVER updated or deleted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket_timeline import TicketTimeline


# ── Canonical event types (mirrors SPEC.md §6) ───────────────────────────────
class EventType:
    CREATED           = "ticket_created"
    ASSIGNED          = "assigned"
    STATUS_CHANGED    = "status_changed"
    REPLY_EXTERNAL    = "reply_external"    # agent → customer (visible)
    REPLY_CUSTOMER    = "reply_customer"    # customer reply
    REPLY_INTERNAL    = "reply_internal"    # internal note (not public)
    SLA_PAUSED        = "sla_paused"
    SLA_RESUMED       = "sla_resumed"
    SLA_BREACH        = "sla_breach"
    ESCALATED         = "escalated"
    TRANSFERRED       = "transferred"
    MERGED            = "merged"
    SPLIT             = "split"
    RESOLVED          = "resolved"
    CLOSED            = "closed"
    REOPENED          = "reopened"
    ARCHIVED          = "archived"
    CSAT_SENT         = "csat_sent"
    CSAT_RECEIVED     = "csat_received"
    ATTACHMENT_ADDED  = "attachment_added"
    FOLLOWUP_ADDED    = "followup_added"
    WATCHER_ADDED     = "watcher_added"
    TAG_ADDED         = "tag_added"
    FORM_VERSION      = "form_version"


# Map event type → is_public by default
_PUBLIC_EVENTS: frozenset[str] = frozenset({
    EventType.CREATED,
    EventType.REPLY_EXTERNAL,
    EventType.REPLY_CUSTOMER,
    EventType.STATUS_CHANGED,
    EventType.RESOLVED,
    EventType.CLOSED,
    EventType.REOPENED,
    EventType.SLA_BREACH,
    EventType.CSAT_SENT,
})


async def add_event(
    db: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    event_type: str,
    content_ar: str,
    content_en: str = "",
    actor_id: Optional[uuid.UUID] = None,
    actor_type: str = "system",   # "agent" | "customer" | "system"
    is_public: Optional[bool] = None,
    metadata: Optional[dict] = None,
) -> TicketTimeline:
    """
    Append an immutable event to ticket_timeline.
    is_public defaults to the canonical map; pass explicitly to override.
    """
    if is_public is None:
        is_public = event_type in _PUBLIC_EVENTS

    event = TicketTimeline(
        id=uuid.uuid4(),
        ticket_id=ticket_id,
        event_type=event_type,
        content_ar=content_ar,
        content_en=content_en or content_ar,
        actor_id=actor_id,
        actor_type=actor_type,
        is_public=is_public,
        metadata_=metadata or {},
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(event)
    await db.flush()   # get the ID without committing the outer transaction
    return event


async def get_public_timeline(
    db: AsyncSession,
    ticket_id: uuid.UUID,
) -> list[TicketTimeline]:
    """Return only public events, ordered oldest-first, for customer-facing views."""
    from sqlalchemy import select, asc
    from sqlalchemy.orm import selectinload
    from app.models.ticket_timeline import TicketTimeline as TL

    result = await db.execute(
        select(TL)
        .where(TL.ticket_id == ticket_id, TL.is_public.is_(True))
        .options(selectinload(TL.actor))
        .order_by(asc(TL.created_at))
    )
    return list(result.scalars().all())
