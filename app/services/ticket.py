"""
Ticket creation service — number generator + DB write + SLA + timeline.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket
from app.schemas.ticket import TicketSubmitForm
from app.services.sla import calculate_sla_deadline
from app.services.timeline import EventType, add_event

UTC = timezone.utc


# ── Ticket number generator ────────────────────────────────────────────────────

_TICKET_SEQ_KEY    = "csts_ticket_seq"
_INT_TICKET_SEQ_KEY = "csint_ticket_seq"


async def _seed_counter_if_needed(redis: aioredis.Redis) -> None:
    """
    One-time seed: if the global counter doesn't exist yet, read the highest
    existing ticket number from the DB-seeded Redis or default to 0.
    Uses SETNX so only the first caller wins (race-safe).
    """
    exists = await redis.exists(_TICKET_SEQ_KEY)
    if exists:
        return

    max_seq = 0
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text(
                    "SELECT ticket_number FROM tickets "
                    "WHERE ticket_number LIKE 'CSTS-%' "
                    "ORDER BY length(ticket_number) DESC, ticket_number DESC "
                    "LIMIT 1"
                )
            )
            result = row.scalar_one_or_none()
            if result:
                num_part = result.split("-", 1)[1]
                max_seq = int(num_part)
    except Exception:
        pass

    if max_seq == 0:
        try:
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import text

            async with AsyncSessionLocal() as db:
                row = await db.execute(
                    text("SELECT COUNT(*) FROM tickets WHERE deleted_at IS NULL")
                )
                count = row.scalar_one_or_none() or 0
                max_seq = count
        except Exception:
            pass

    await redis.setnx(_TICKET_SEQ_KEY, max_seq)


async def generate_ticket_number(redis: aioredis.Redis) -> str:
    """
    Thread-safe globally incrementing ticket number.
    Format: CSTS-{seq}  (e.g. CSTS-001, CSTS-002, ... CSTS-1234)
    Uses a single Redis key that never resets.
    """
    await _seed_counter_if_needed(redis)

    seq: int = await redis.incr(_TICKET_SEQ_KEY)

    return f"CSTS-{seq:03d}"


async def generate_int_ticket_number(redis: aioredis.Redis) -> str:
    """CS-INT-{seq} — globally incrementing internal ticket numbers."""
    seq: int = await redis.incr(_INT_TICKET_SEQ_KEY)
    return f"CS-INT-{seq:03d}"


# ── Ticket creation ────────────────────────────────────────────────────────────

async def create_ticket(
    db: AsyncSession,
    redis: aioredis.Redis,
    form: TicketSubmitForm,
    *,
    submitter_user_id: Optional[uuid.UUID] = None,
) -> Ticket:
    """
    Create a ticket from a portal form submission:
    1. Generate unique ticket number (Redis INCR)
    2. Calculate SLA deadline (business hours)
    3. Insert Ticket row
    4. Append "ticket_created" timeline event
    5. flush so the ticket gets an ID (outer transaction still open)
    Returns the Ticket ORM object (not yet committed).
    """
    now           = datetime.now(tz=UTC)
    ticket_number = await generate_ticket_number(redis)
    sla_deadline  = await calculate_sla_deadline(db, form.priority, now)

    # Opaque token for public ticket-view URL (/ticket/{token})
    public_token  = secrets.token_urlsafe(32)
    # CSAT survey token (separate, shorter)
    csat_token    = secrets.token_urlsafe(24)

    ticket = Ticket(
        id=uuid.uuid4(),
        ticket_number=ticket_number,
        public_token=public_token,
        csat_token=csat_token,
        submitter_name=form.submitter_name,
        submitter_name_ar=form.submitter_name,
        submitter_phone=form.submitter_phone,
        submitter_email=form.submitter_email,
        employee_id=form.employee_id,
        branch_id=form.branch_id,
        category_id=form.category_id,
        priority=form.priority,
        status="new",
        channel=form.channel,
        subject=form.subject or "",
        description=form.description,
        submitted_by_id=submitter_user_id,
        sla_deadline=sla_deadline,
        sla_breached=False,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    await db.flush()   # gets ticket.id without full commit

    # Immutable creation event
    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.CREATED,
        content_ar=f"تم إنشاء التذكرة {ticket_number}",
        content_en=f"Ticket {ticket_number} created",
        actor_id=submitter_user_id,
        actor_type="customer" if submitter_user_id is None else "agent",
        is_public=True,
        metadata={
            "channel": form.channel,
            "priority": form.priority,
            "sla_deadline": sla_deadline.isoformat(),
        },
    )

    return ticket


# ── Internal ticket creation (from call log) ──────────────────────────────────

async def create_internal_ticket(
    db: AsyncSession,
    redis: aioredis.Redis,
    *,
    subject: str,
    description: str,
    agent_id: uuid.UUID,
    assigned_to: Optional[uuid.UUID] = None,
    queue: str = "internal_tickets",
    caller_name: str = "",
) -> Ticket:
    """
    Create an internal CS-INT ticket from a call log outcome.
    - followup  → assigned_to=agent, status=open (agent works it)
    - ticket    → assigned_to=None,  status=new  (supervisor claims from queue)
    """
    now           = datetime.now(tz=UTC)
    ticket_number = await generate_int_ticket_number(redis)

    # Unassigned = new (waiting to be claimed); assigned = open (ready to work)
    initial_status = "open" if assigned_to else "new"

    ticket = Ticket(
        id=uuid.uuid4(),
        ticket_number=ticket_number,
        public_token=secrets.token_urlsafe(32),
        csat_token=secrets.token_urlsafe(24),
        submitter_name=caller_name or "Internal",
        submitter_name_ar=caller_name or "داخلي",
        subject=subject,
        description=description,
        priority="medium",
        status=initial_status,
        channel="phone",
        current_queue=queue,
        assigned_to=assigned_to,
        submitted_by_id=agent_id,
        sla_breached=False,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    await db.flush()

    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.CREATED,
        content_ar=f"تذكرة داخلية {ticket_number} — أُنشئت من سجل مكالمة",
        content_en=f"Internal ticket {ticket_number} — created from call log",
        actor_id=agent_id,
        actor_type="agent",
        is_public=False,
        metadata={"source": "call_log", "queue": queue},
    )

    return ticket


# ── Notification helpers (async Celery dispatch) ──────────────────────────────

def _enqueue_confirmation(ticket: Ticket) -> None:
    """
    Fire-and-forget: enqueue Celery tasks for email + WhatsApp confirmation.
    Imported lazily to avoid circular imports.
    """
    try:
        from app.worker.tasks.notifications import send_ticket_confirmation
        send_ticket_confirmation.delay(str(ticket.id))
    except Exception:
        pass   # Celery not available during unit tests; safe to ignore
