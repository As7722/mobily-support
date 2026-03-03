"""
IMAP Email Ingestion — Celery task running every 60 seconds.

Pipeline per unseen message:
  1. Skip if X-Ticket-ID header present (spam-loop guard).
  2. Look for [TKT-XXXXXXXX-XXXX] in subject → append as reply.
  3. No match → create new ticket.
  4. Attachments: ClamAV scan → S3 upload → attach to ticket.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)
UTC = timezone.utc


@celery_app.task(
    name="email.poll_inbox",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def poll_inbox(self) -> dict:
    """Synchronous Celery task that polls IMAP and processes each email."""
    return asyncio.get_event_loop().run_until_complete(_poll_inbox_async())


async def _poll_inbox_async() -> dict:
    from sqlalchemy import select
    from app.core.database import get_async_session
    from app.core.config import settings
    from app.models.ticket import Ticket
    from app.services.email import poll_imap_inbox
    from app.services.ticket import create_ticket
    from app.services.timeline import add_event, EventType
    from app.services.storage import upload_file, StorageError, VirusDetectedError

    emails = poll_imap_inbox(
        imap_host=settings.IMAP_HOST,
        imap_port=settings.IMAP_PORT,
        imap_user=settings.IMAP_USER,
        imap_password=settings.IMAP_PASSWORD,
        use_ssl=settings.IMAP_SSL,
    )

    if not emails:
        return {"processed": 0}

    processed = replied = created = 0

    async for db in get_async_session():
        # lazy-import Redis pool
        from app.core.redis import get_redis_pool
        redis_pool = await get_redis_pool()

        for msg in emails:
            try:
                # Spam-loop guard
                if msg["ticket_id_header"]:
                    log.debug("Skipping email with X-Ticket-ID=%s", msg["ticket_id_header"])
                    processed += 1
                    continue

                if msg["ticket_number"]:
                    # Find ticket by number
                    result = await db.execute(
                        select(Ticket).where(
                            Ticket.ticket_number == msg["ticket_number"],
                            Ticket.deleted_at.is_(None),
                        )
                    )
                    ticket = result.scalar_one_or_none()
                    if ticket:
                        # Append as customer reply
                        async with db.begin():
                            await add_event(
                                db,
                                ticket_id=ticket.id,
                                event_type=EventType.REPLY_CUSTOMER,
                                content_ar=msg["body"][:2000],
                                content_en=msg["body"][:2000],
                                actor_type="customer",
                                is_public=True,
                                metadata={"email_from": msg["sender"]},
                            )
                            if ticket.status == "pending_customer":
                                ticket.status = "open"
                                ticket.updated_at = datetime.now(tz=UTC)

                            # Handle attachments
                            await _process_attachments(db, msg["attachments"], ticket.id)

                        replied += 1
                        processed += 1
                        continue

                # No matching ticket → create new
                from app.schemas.ticket import TicketSubmitForm
                from app.services.ticket import create_ticket

                form = TicketSubmitForm(
                    submitter_name=msg["sender_name"] or msg["sender"] or "Email",
                    submitter_phone=msg.get("sender_phone") or "email",
                    submitter_email=msg["sender"],
                    subject=msg["subject"][:200] if msg.get("subject") else None,
                    description=(msg.get("body") or "Email ticket")[:10_000],
                    channel="email",
                    priority="medium",
                )
                async with db.begin():
                    ticket = await create_ticket(db=db, redis=redis_pool, form=form)
                    await db.flush()
                    await _process_attachments(db, msg["attachments"], ticket.id)

                created += 1
                processed += 1

            except Exception as exc:
                log.error("Error processing email from %s: %s", msg.get("sender"), exc, exc_info=True)

    log.info("IMAP poll done: processed=%d replied=%d created=%d", processed, replied, created)
    return {"processed": processed, "replied": replied, "created": created}


async def _process_attachments(
    db,
    attachments: list[tuple[str, bytes]],
    ticket_id: uuid.UUID,
) -> None:
    from app.core.config import settings
    from app.models.ticket_assoc import TicketAttachment
    from app.services.storage import upload_file, StorageError, VirusDetectedError

    for filename, data in attachments:
        if not data:
            continue
        try:
            s3_key = await upload_file(
                data,
                filename,
                ticket_id=str(ticket_id),
                bucket=settings.S3_BUCKET,
                aws_access_key=settings.AWS_ACCESS_KEY_ID,
                aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
                region=settings.AWS_REGION,
                endpoint_url=settings.AWS_ENDPOINT_URL or None,
                scan=True,
            )
            att = TicketAttachment(
                id=uuid.uuid4(),
                ticket_id=ticket_id,
                filename=filename,
                s3_key=s3_key,
                file_size=len(data),
                uploaded_at=datetime.now(tz=UTC),
            )
            db.add(att)
        except VirusDetectedError as exc:
            log.warning("Attachment %s virus detected: %s", filename, exc)
        except StorageError as exc:
            log.warning("Attachment %s storage error: %s", filename, exc)
