"""
SLA Engine — business-hours aware deadline calculator.

Business calendar: Sun–Thu, 08:00–16:00 Asia/Riyadh (UTC+3)
Weekdays (Python weekday()): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
Business days in SA weekday set: {0,1,2,3,6}  (Mon–Thu + Sun)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import Holiday
from app.models.sla import SLAPause
from app.models.ticket import Ticket
from app.models.ticket_timeline import TicketTimeline

RIYADH_TZ = ZoneInfo("Asia/Riyadh")
UTC = timezone.utc

# Business day weekday numbers (Python: Mon=0 … Sun=6)
BUSINESS_WEEKDAYS: frozenset[int] = frozenset({0, 1, 2, 3, 6})

WORK_START_H = 8
WORK_END_H   = 16
WORK_MINUTES = (WORK_END_H - WORK_START_H) * 60   # 480 min/day

# SLA clock minutes per priority (SPEC.md §2)
SLA_MINUTES: dict[str, int] = {
    "critical": 30,
    "high":     120,
    "medium":   480,
    "low":      1440,
}


# ── Holiday helper ────────────────────────────────────────────────────────────

async def _get_holiday_set(db: AsyncSession, year: int) -> set[date]:
    """Load all holiday dates for a given year from the DB."""
    result = await db.execute(
        select(Holiday.date).where(
            Holiday.date >= date(year, 1, 1),
            Holiday.date <= date(year, 12, 31),
        )
    )
    return {row[0] for row in result.fetchall()}


# ── Core calculator ───────────────────────────────────────────────────────────

def _add_business_minutes(start: datetime, minutes: int, holidays: set[date]) -> datetime:
    """
    Pure function. Returns deadline by counting only business minutes from start.
    start must be timezone-aware.
    """
    current = start.astimezone(RIYADH_TZ)
    remaining = minutes

    while remaining > 0:
        # Skip non-business days
        if current.weekday() not in BUSINESS_WEEKDAYS or current.date() in holidays:
            # Advance to start-of-next-day, then loop
            current = (current + timedelta(days=1)).replace(
                hour=WORK_START_H, minute=0, second=0, microsecond=0
            )
            continue

        # Clamp to work hours
        day_start = current.replace(hour=WORK_START_H, minute=0, second=0, microsecond=0)
        day_end   = current.replace(hour=WORK_END_H,   minute=0, second=0, microsecond=0)

        if current < day_start:
            current = day_start

        if current >= day_end:
            # Past EOD — jump to next day
            current = (current + timedelta(days=1)).replace(
                hour=WORK_START_H, minute=0, second=0, microsecond=0
            )
            continue

        # How many business minutes remain today?
        minutes_today = int((day_end - current).total_seconds() / 60)

        if remaining <= minutes_today:
            current = current + timedelta(minutes=remaining)
            remaining = 0
        else:
            remaining -= minutes_today
            current = (current + timedelta(days=1)).replace(
                hour=WORK_START_H, minute=0, second=0, microsecond=0
            )

    return current.astimezone(UTC)


async def calculate_sla_deadline(
    db: AsyncSession,
    priority: str,
    created_at: datetime,
) -> datetime:
    """Return the SLA deadline for a new ticket (TIMESTAMPTZ, UTC)."""
    sla_mins = SLA_MINUTES.get(priority, SLA_MINUTES["medium"])
    holidays  = await _get_holiday_set(db, created_at.year)
    return _add_business_minutes(created_at, sla_mins, holidays)


# ── SLA Pause / Resume ────────────────────────────────────────────────────────

async def pause_sla(
    db: AsyncSession,
    ticket: Ticket,
    reason: str,
    actor_id: Optional[uuid.UUID] = None,
) -> SLAPause:
    """
    Freeze SLA clock.  Creates an open SLAPause row and sets ticket.sla_paused_at.
    Also appends a timeline event (caller responsible for committing).
    """
    if ticket.sla_paused_at is not None:
        raise ValueError("SLA is already paused for this ticket")

    now = datetime.now(tz=UTC)
    pause = SLAPause(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        reason=reason,
        paused_at=now,
    )
    ticket.sla_paused_at = now
    db.add(pause)
    await db.flush()

    from app.services.timeline import add_event, EventType
    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.SLA_PAUSED,
        content_ar=f"تم إيقاف SLA مؤقتاً — {reason}",
        content_en=f"SLA paused — {reason}",
        actor_id=actor_id,
        actor_type="agent",
        is_public=False,
    )
    return pause


async def resume_sla(
    db: AsyncSession,
    ticket: Ticket,
    actor_id: Optional[uuid.UUID] = None,
) -> None:
    """
    Resume SLA clock.  Closes the open SLAPause row and extends sla_deadline
    by the paused duration (excluding non-business time).
    """
    if ticket.sla_paused_at is None:
        raise ValueError("SLA is not paused for this ticket")

    now      = datetime.now(tz=UTC)
    paused   = ticket.sla_paused_at

    # Extend SLA deadline by the paused wall-clock duration
    pause_duration = now - paused
    if ticket.sla_deadline:
        ticket.sla_deadline = ticket.sla_deadline + pause_duration

    ticket.sla_paused_at = None

    # Close the open pause row
    result = await db.execute(
        select(SLAPause)
        .where(SLAPause.ticket_id == ticket.id, SLAPause.resumed_at.is_(None))
        .order_by(SLAPause.paused_at.desc())
        .limit(1)
    )
    pause_row = result.scalar_one_or_none()
    if pause_row:
        pause_row.resumed_at = now

    from app.services.timeline import add_event, EventType
    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.SLA_RESUMED,
        content_ar="تم استئناف SLA",
        content_en="SLA resumed",
        actor_id=actor_id,
        actor_type="agent",
        is_public=False,
    )


# ── Elapsed ratio ─────────────────────────────────────────────────────────────

def get_sla_elapsed_ratio(ticket: Ticket) -> float:
    """
    Return 0.0–1.0+ representing the fraction of SLA time elapsed.
    >1.0 means SLA is breached.  Returns 0.0 if no SLA deadline set.
    Uses wall-clock time (not business hours) for live dashboard display.
    """
    if not ticket.sla_deadline or not ticket.created_at:
        return 0.0

    now         = datetime.now(tz=UTC)
    total_secs  = (ticket.sla_deadline - ticket.created_at).total_seconds()
    elapsed_secs = (now - ticket.created_at).total_seconds()

    if total_secs <= 0:
        return 1.0
    return elapsed_secs / total_secs


# ── Celery Beat task: check SLA breaches every 60 s ──────────────────────────

async def check_sla_breaches_async(db: AsyncSession) -> int:
    """
    Mark tickets as SLA-breached when sla_deadline has passed.
    Returns the number of tickets newly marked as breached.
    Called from the Celery task wrapper in app/worker/tasks/sla.py.
    """
    from sqlalchemy import update
    from app.models.ticket import Ticket as T

    now = datetime.now(tz=UTC)

    # Find tickets that are overdue but not yet flagged
    result = await db.execute(
        select(T).where(
            T.sla_deadline <= now,
            T.sla_breached.is_(False),
            T.sla_paused_at.is_(None),
            T.status.notin_(["resolved", "closed", "archived"]),
            T.deleted_at.is_(None),
        )
    )
    tickets: list[Ticket] = list(result.scalars().all())

    from app.services.timeline import add_event, EventType
    from app.services.ticket_service import check_sla_auto_escalation

    from app.services.notifications import create_notification, NotifEvent

    for ticket in tickets:
        ticket.sla_breached = True

        await add_event(
            db,
            ticket_id=ticket.id,
            event_type=EventType.SLA_BREACH,
            content_ar="⚠️ تجاوز وقت SLA",
            content_en="⚠️ SLA Breached",
            actor_type="system",
            is_public=True,
        )

        # Notify the assigned agent (if any)
        if ticket.assigned_to:
            try:
                await create_notification(
                    db, user_id=ticket.assigned_to,
                    event_type=NotifEvent.SLA_BREACH,
                    ticket_id=ticket.id,
                    ticket_number=ticket.ticket_number or "",
                )
            except Exception:
                pass

        await check_sla_auto_escalation(db, ticket)

    await db.commit()
    return len(tickets)
