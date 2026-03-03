"""
Ticket State Machine & Automated Time Tracking Service
-------------------------------------------------------
Iron Rule #2: NO manual start/stop buttons. Time is computed purely
from state transitions:
  - Start/Resume: status -> open  (set last_opened_at)
  - Pause:        status -> pending_customer | pending_3rd
  - Stop:         status -> resolved

Iron Rule #1: Priority can only be changed by supervisor/manager/admin.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket
from app.services.timeline import EventType, add_event

UTC = timezone.utc

STATUS_TRANSITIONS: dict[str, list[str]] = {
    "new":              ["open"],
    "open":             ["pending_customer", "pending_3rd", "resolved"],
    "pending_customer": ["open", "resolved"],
    "pending_3rd":      ["open", "resolved"],
    "resolved":         ["closed", "open"],
    "closed":           ["open"],
}

PAUSING_STATUSES = frozenset({"pending_customer", "pending_3rd"})
WORK_ACTIVE_STATUS = "open"


def validate_transition(current: str, target: str) -> bool:
    return target in STATUS_TRANSITIONS.get(current, [])


def _accumulate_work_time(ticket: Ticket, now: datetime) -> None:
    """Add elapsed open-time to work_time_seconds when leaving 'open'."""
    if ticket.last_opened_at is not None:
        opened = ticket.last_opened_at
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=UTC)
        delta = int((now - opened).total_seconds())
        if delta > 0:
            ticket.work_time_seconds = (ticket.work_time_seconds or 0) + delta
    ticket.last_opened_at = None


async def change_ticket_status(
    db: AsyncSession,
    ticket: Ticket,
    new_status: str,
    actor_id: uuid.UUID,
    *,
    reason: Optional[str] = None,
    lang: str = "ar",
) -> None:
    """
    Transition ticket to new_status with automated time tracking.
    Raises ValueError if the transition is not allowed.
    """
    from app.i18n import t

    old_status = ticket.status
    if not validate_transition(old_status, new_status):
        raise ValueError(f"Cannot transition from {old_status} → {new_status}")

    now = datetime.now(tz=UTC)

    # ── Time tracking math ─────────────────────────────────────────────────
    if old_status == WORK_ACTIVE_STATUS:
        _accumulate_work_time(ticket, now)

    if new_status == WORK_ACTIVE_STATUS:
        ticket.last_opened_at = now

    # ── Status-specific fields ─────────────────────────────────────────────
    ticket.status = new_status
    ticket.updated_at = now
    ticket.version += 1

    if new_status == "resolved":
        ticket.resolved_at = now
        if ticket.created_at:
            created = ticket.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            ticket.total_time_seconds = int((now - created).total_seconds())
    elif new_status == "closed":
        ticket.closed_at = now
    elif new_status == "open" and old_status in ("resolved", "closed"):
        ticket.reopen_count = (ticket.reopen_count or 0) + 1
        await _check_auto_escalation(db, ticket, actor_id)

    # ── Timeline event ─────────────────────────────────────────────────────
    event_type = EventType.STATUS_CHANGED
    if new_status == "resolved":
        event_type = EventType.RESOLVED
    elif new_status == "closed":
        event_type = EventType.CLOSED
    elif new_status == "open" and old_status in ("resolved", "closed"):
        event_type = EventType.REOPENED

    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=event_type,
        content_ar=f"تغيّر الحالة من {t('ticket.status.' + old_status, lang='ar')} إلى {t('ticket.status.' + new_status, lang='ar')}",
        content_en=f"Status changed from {old_status} to {new_status}",
        actor_id=actor_id,
        actor_type="agent",
        is_public=True,
        metadata={"from": old_status, "to": new_status, "reason": reason},
    )
    await db.flush()


async def change_ticket_priority(
    db: AsyncSession,
    ticket: Ticket,
    new_priority: str,
    actor_id: uuid.UUID,
    role: str,
) -> None:
    """
    Iron Rule #1: Only supervisor/manager/admin can change priority.
    Raises PermissionError if role is insufficient.
    """
    if role not in ("supervisor", "manager", "admin"):
        raise PermissionError("Only supervisor/manager/admin can change priority")

    valid = ("critical", "high", "medium", "low")
    if new_priority not in valid:
        raise ValueError(f"Invalid priority: {new_priority}")

    old_priority = ticket.priority
    if old_priority == new_priority:
        return

    now = datetime.now(tz=UTC)
    ticket.priority = new_priority
    ticket.updated_at = now
    ticket.version += 1

    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.STATUS_CHANGED,
        content_ar=f"تغيّر الأولوية من {old_priority} إلى {new_priority}",
        content_en=f"Priority changed from {old_priority} to {new_priority}",
        actor_id=actor_id,
        actor_type="agent",
        is_public=False,
        metadata={"field": "priority", "from": old_priority, "to": new_priority},
    )
    await db.flush()


async def _check_auto_escalation(
    db: AsyncSession,
    ticket: Ticket,
    actor_id: uuid.UUID,
) -> None:
    """
    Iron Rule #4 auto-escalation:
      - 3+ reopens -> supervisor queue
      - 100% SLA breach (sla_breached=True) -> supervisor queue
    Only escalates if ticket is still in main/specialized queue.
    """
    if ticket.current_queue in ("supervisor", "manager"):
        return

    should_escalate = False
    reason_ar = ""
    reason_en = ""

    if (ticket.reopen_count or 0) >= 3:
        should_escalate = True
        reason_ar = f"تصعيد تلقائي — إعادة فتح {ticket.reopen_count} مرات"
        reason_en = f"Auto-escalated — {ticket.reopen_count} reopens"
    elif ticket.sla_breached:
        should_escalate = True
        reason_ar = "تصعيد تلقائي — تجاوز اتفاقية مستوى الخدمة"
        reason_en = "Auto-escalated — SLA breach"

    if should_escalate:
        ticket.current_queue = "supervisor"
        await add_event(
            db,
            ticket_id=ticket.id,
            event_type=EventType.ESCALATED,
            content_ar=reason_ar,
            content_en=reason_en,
            actor_id=actor_id,
            actor_type="system",
            is_public=False,
            metadata={"auto": True, "reopen_count": ticket.reopen_count, "sla_breached": ticket.sla_breached},
        )


async def check_sla_auto_escalation(
    db: AsyncSession,
    ticket: Ticket,
) -> None:
    """Called by SLA breach detection task to auto-escalate."""
    if ticket.sla_breached and ticket.current_queue in ("main", "specialized"):
        ticket.current_queue = "supervisor"
        now = datetime.now(tz=UTC)
        ticket.updated_at = now
        await add_event(
            db,
            ticket_id=ticket.id,
            event_type=EventType.ESCALATED,
            content_ar="تصعيد تلقائي — تجاوز اتفاقية مستوى الخدمة",
            content_en="Auto-escalated — SLA breach",
            actor_type="system",
            is_public=False,
            metadata={"auto": True, "sla_breached": True},
        )


__all__ = [
    "STATUS_TRANSITIONS",
    "validate_transition",
    "change_ticket_status",
    "change_ticket_priority",
    "check_sla_auto_escalation",
]
