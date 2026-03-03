"""
Notification Celery tasks — email + WhatsApp confirmations.
"""
from __future__ import annotations

import asyncio
import logging

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="send-ticket-confirmation", bind=True, max_retries=3)
def send_ticket_confirmation(self, ticket_id: str) -> dict:  # type: ignore[override]
    """
    Send submission confirmation to the customer via email and/or WhatsApp.
    """
    async def _run() -> dict:
        import uuid
        from app.core.database import AsyncSessionLocal
        from app.models.ticket import Ticket
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Ticket).where(Ticket.id == uuid.UUID(ticket_id))
            )
            ticket = result.scalar_one_or_none()
            if not ticket:
                return {"status": "not_found"}

            sent = []

            if ticket.submitter_email:
                # TODO: wire to aiosmtplib email service
                logger.info("Email confirmation queued for %s → %s", ticket.ticket_number, ticket.submitter_email)
                sent.append("email")

            if ticket.submitter_phone:
                # TODO: wire to Twilio WhatsApp service
                logger.info("WhatsApp confirmation queued for %s → %s", ticket.ticket_number, ticket.submitter_phone)
                sent.append("whatsapp")

            return {"status": "sent", "channels": sent}

    try:
        result = asyncio.get_event_loop().run_until_complete(_run())
        return result
    except Exception as exc:
        logger.exception("send_ticket_confirmation failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="send-csat-survey", bind=True, max_retries=3)
def send_csat_survey(self, ticket_id: str) -> dict:  # type: ignore[override]
    """Send CSAT survey link after ticket resolution."""
    # TODO: implement
    logger.info("CSAT survey queued for ticket %s", ticket_id)
    return {"status": "queued"}
