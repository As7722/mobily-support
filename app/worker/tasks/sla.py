"""
Celery SLA tasks — runs every 60 seconds via Celery Beat.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
UTC = timezone.utc


@celery_app.task(name="check-sla-breaches", bind=True, max_retries=3)
def check_sla_breaches(self) -> dict:  # type: ignore[override]
    """
    Scan all open tickets for SLA deadline violations.
    Marks sla_breached=True and appends a timeline event for each.
    """
    async def _run() -> int:
        from app.core.database import AsyncSessionLocal
        from app.services.sla import check_sla_breaches_async

        async with AsyncSessionLocal() as db:
            return await check_sla_breaches_async(db)

    try:
        count = asyncio.get_event_loop().run_until_complete(_run())
        logger.info("SLA breach check: %d ticket(s) newly breached", count)
        return {"breached": count}
    except Exception as exc:
        logger.exception("SLA breach check failed: %s", exc)
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(name="auto-archive-old-tickets", bind=True)
def auto_archive_old_tickets(self) -> dict:  # type: ignore[override]
    """Archive tickets closed >30 days ago."""
    from datetime import datetime, timedelta, timezone

    async def _run() -> int:
        from sqlalchemy import update
        from app.core.database import AsyncSessionLocal
        from app.models.ticket import Ticket

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(Ticket)
                .where(
                    Ticket.status == "closed",
                    Ticket.updated_at <= cutoff,
                    Ticket.deleted_at.is_(None),
                )
                .values(status="archived", updated_at=datetime.now(tz=timezone.utc))
                .returning(Ticket.id)
            )
            count = len(result.fetchall())
            await db.commit()
        return count

    try:
        count = asyncio.get_event_loop().run_until_complete(_run())
        logger.info("Auto-archived %d ticket(s)", count)
        return {"archived": count}
    except Exception as exc:
        logger.exception("Auto-archive failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="auto-resolve-pending-customer", bind=True, max_retries=3)
def auto_resolve_pending_customer(self) -> dict:  # type: ignore[override]
    """
    Auto-resolve tickets that have been in pending_customer for 48+ hours
    with no customer reply. Fires every hour via Celery Beat.
    """
    async def _run() -> int:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.ticket import Ticket
        from app.models.ticket_timeline import TicketTimeline
        from app.services.timeline import EventType, add_event

        cutoff = datetime.now(tz=UTC) - timedelta(hours=48)
        count = 0

        async with AsyncSessionLocal() as db:
            # Find tickets stuck in pending_customer for > 48h
            result = await db.execute(
                select(Ticket).where(
                    Ticket.status == "pending_customer",
                    Ticket.updated_at <= cutoff,
                    Ticket.deleted_at.is_(None),
                )
            )
            tickets = result.scalars().all()

            for ticket in tickets:
                # Verify no customer reply has come in since status changed
                last_reply = await db.execute(
                    select(TicketTimeline).where(
                        TicketTimeline.ticket_id == ticket.id,
                        TicketTimeline.event_type == EventType.REPLY_CUSTOMER,
                        TicketTimeline.created_at > cutoff,
                    ).limit(1)
                )
                if last_reply.scalar_one_or_none():
                    continue  # Customer replied — skip

                now = datetime.now(tz=UTC)
                ticket.status = "resolved"
                ticket.resolved_at = now
                ticket.updated_at = now

                await add_event(
                    db,
                    ticket_id=ticket.id,
                    event_type=EventType.RESOLVED,
                    content_ar="تم الحل تلقائياً — لم يرد العميل خلال 48 ساعة",
                    content_en="Auto-resolved — no customer reply within 48 hours",
                    actor_id=None,
                    actor_type="system",
                    is_public=True,
                )
                count += 1

            await db.commit()

        return count

    try:
        count = asyncio.get_event_loop().run_until_complete(_run())
        logger.info("Auto-resolved %d pending_customer ticket(s)", count)
        return {"resolved": count}
    except Exception as exc:
        logger.exception("Auto-resolve pending_customer failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)
