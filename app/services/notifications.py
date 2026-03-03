"""
Notification service — creates, fetches, and marks notifications.
Wired into ticket events and SSE for real-time delivery + sound.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationRule


# ── Notification event types ──────────────────────────────────────────────────
class NotifEvent:
    TICKET_ASSIGNED       = "ticket_assigned"
    TICKET_ESCALATED      = "ticket_escalated"
    TICKET_REPLIED        = "ticket_replied"
    TICKET_STATUS_CHANGED = "ticket_status_changed"
    TICKET_CREATED        = "ticket_created"
    SLA_BREACH            = "sla_breach"
    SLA_WARNING           = "sla_warning"
    TICKET_RESOLVED       = "ticket_resolved"
    TICKET_CLOSED         = "ticket_closed"
    TICKET_TRANSFERRED    = "ticket_transferred"
    TICKET_MERGED         = "ticket_merged"
    TICKET_SPLIT          = "ticket_split"
    MENTION               = "mention"
    SYSTEM                = "system"


# ── Text templates per event ──────────────────────────────────────────────────
_TEMPLATES: dict[str, dict[str, str]] = {
    NotifEvent.TICKET_ASSIGNED: {
        "title_ar": "تذكرة مُسندة إليك",
        "title_en": "Ticket assigned to you",
        "body_ar":  "تم إسناد التذكرة {num} إليك",
        "body_en":  "Ticket {num} has been assigned to you",
    },
    NotifEvent.TICKET_ESCALATED: {
        "title_ar": "تذكرة مُصعَّدة",
        "title_en": "Ticket escalated",
        "body_ar":  "تم تصعيد التذكرة {num}",
        "body_en":  "Ticket {num} has been escalated",
    },
    NotifEvent.TICKET_REPLIED: {
        "title_ar": "رد جديد على التذكرة",
        "title_en": "New reply on ticket",
        "body_ar":  "رد جديد على التذكرة {num}",
        "body_en":  "New reply on ticket {num}",
    },
    NotifEvent.TICKET_STATUS_CHANGED: {
        "title_ar": "تغيير حالة التذكرة",
        "title_en": "Ticket status changed",
        "body_ar":  "تغيرت حالة التذكرة {num} إلى {extra}",
        "body_en":  "Ticket {num} status changed to {extra}",
    },
    NotifEvent.TICKET_CREATED: {
        "title_ar": "تذكرة جديدة",
        "title_en": "New ticket",
        "body_ar":  "تذكرة جديدة {num} في الطابور",
        "body_en":  "New ticket {num} in queue",
    },
    NotifEvent.SLA_BREACH: {
        "title_ar": "⚠️ خرق SLA",
        "title_en": "⚠️ SLA Breached",
        "body_ar":  "انتهت مهلة SLA للتذكرة {num}",
        "body_en":  "SLA deadline exceeded for ticket {num}",
    },
    NotifEvent.SLA_WARNING: {
        "title_ar": "تحذير SLA",
        "title_en": "SLA Warning",
        "body_ar":  "ستنتهي مهلة SLA للتذكرة {num} قريبًا",
        "body_en":  "SLA deadline for ticket {num} is approaching",
    },
    NotifEvent.TICKET_RESOLVED: {
        "title_ar": "تذكرة محلولة",
        "title_en": "Ticket resolved",
        "body_ar":  "تم حل التذكرة {num}",
        "body_en":  "Ticket {num} has been resolved",
    },
    NotifEvent.TICKET_CLOSED: {
        "title_ar": "تذكرة مغلقة",
        "title_en": "Ticket closed",
        "body_ar":  "تم إغلاق التذكرة {num}",
        "body_en":  "Ticket {num} has been closed",
    },
    NotifEvent.TICKET_TRANSFERRED: {
        "title_ar": "تذكرة محوَّلة إليك",
        "title_en": "Ticket transferred to you",
        "body_ar":  "تم تحويل التذكرة {num} إليك",
        "body_en":  "Ticket {num} has been transferred to you",
    },
    NotifEvent.TICKET_MERGED: {
        "title_ar": "تم دمج التذاكر",
        "title_en": "Tickets merged",
        "body_ar":  "تم دمج تذاكر مع التذكرة {num}",
        "body_en":  "Tickets merged into {num}",
    },
    NotifEvent.TICKET_SPLIT: {
        "title_ar": "تم تقسيم التذكرة",
        "title_en": "Ticket split",
        "body_ar":  "تم تقسيم التذكرة {num}",
        "body_en":  "Ticket {num} has been split",
    },
    NotifEvent.MENTION: {
        "title_ar": "تم ذكرك",
        "title_en": "You were mentioned",
        "body_ar":  "تم ذكرك في التذكرة {num}",
        "body_en":  "You were mentioned in ticket {num}",
    },
    NotifEvent.SYSTEM: {
        "title_ar": "إشعار النظام",
        "title_en": "System notification",
        "body_ar":  "{extra}",
        "body_en":  "{extra}",
    },
}

# Icon per event type
NOTIF_ICONS: dict[str, str] = {
    NotifEvent.TICKET_ASSIGNED:       "🎫",
    NotifEvent.TICKET_ESCALATED:      "🔺",
    NotifEvent.TICKET_REPLIED:        "💬",
    NotifEvent.TICKET_STATUS_CHANGED: "🔄",
    NotifEvent.TICKET_CREATED:        "✨",
    NotifEvent.SLA_BREACH:            "⚠️",
    NotifEvent.SLA_WARNING:           "⏰",
    NotifEvent.TICKET_RESOLVED:       "✅",
    NotifEvent.TICKET_CLOSED:         "🔒",
    NotifEvent.TICKET_TRANSFERRED:    "➡️",
    NotifEvent.TICKET_MERGED:         "🔗",
    NotifEvent.TICKET_SPLIT:          "✂️",
    NotifEvent.MENTION:               "📢",
    NotifEvent.SYSTEM:                "🔔",
}


async def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    event_type: str,
    ticket_id: Optional[uuid.UUID] = None,
    ticket_number: str = "",
    extra: str = "",
    title_ar: Optional[str] = None,
    title_en: Optional[str] = None,
    body_ar: Optional[str] = None,
    body_en: Optional[str] = None,
) -> Notification:
    """Create a single in-app notification."""
    tpl = _TEMPLATES.get(event_type, _TEMPLATES[NotifEvent.SYSTEM])
    num = ticket_number or ""

    n = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        type=event_type,
        ticket_id=ticket_id,
        title_ar=title_ar or tpl["title_ar"],
        title_en=title_en or tpl["title_en"],
        body_ar=(body_ar or tpl["body_ar"]).format(num=num, extra=extra),
        body_en=(body_en or tpl["body_en"]).format(num=num, extra=extra),
        is_read=False,
    )
    db.add(n)
    return n


async def notify_users(
    db: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
    event_type: str,
    ticket_id: Optional[uuid.UUID] = None,
    ticket_number: str = "",
    extra: str = "",
) -> list[Notification]:
    """Create notifications for multiple users at once."""
    notifs = []
    for uid in user_ids:
        n = await create_notification(
            db,
            user_id=uid,
            event_type=event_type,
            ticket_id=ticket_id,
            ticket_number=ticket_number,
            extra=extra,
        )
        notifs.append(n)
    return notifs


async def get_unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
            Notification.deleted_at.is_(None),
        )
    )
    return result.scalar_one() or 0


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    from datetime import datetime, timezone
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
            Notification.deleted_at.is_(None),
        )
        .values(is_read=True)
    )


async def mark_one_read(db: AsyncSession, notif_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id, Notification.user_id == user_id)
        .values(is_read=True)
    )


async def is_event_enabled(db: AsyncSession, event_type: str, role: str) -> bool:
    """Check if notification rule is active for this event and role."""
    result = await db.execute(
        select(NotificationRule).where(
            NotificationRule.event_type == event_type,
            NotificationRule.is_active.is_(True),
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        return True  # default enabled if no rule defined
    return role in (rule.target_roles or [])
