"""
WhatsApp Integration via Twilio WhatsApp API.

Inbound:  POST /webhooks/whatsapp  (Twilio delivers to this endpoint)
Outbound: send_message() called from Celery tasks or API handlers.

Message routing:
  1. Check if sender phone has an open ticket in the last 24h → append as reply.
  2. Otherwise → create new ticket, reply with ticket number.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)
UTC = timezone.utc


def _twilio_client(account_sid: str, auth_token: str):
    from twilio.rest import Client  # type: ignore[import-untyped]
    return Client(account_sid, auth_token)


# ── Outbound ──────────────────────────────────────────────────────────────────

def send_whatsapp(
    to_phone: str,
    body: str,
    *,
    from_number: str,
    account_sid: str,
    auth_token: str,
) -> None:
    """Send a WhatsApp message via Twilio. Blocking — call from Celery task."""
    client = _twilio_client(account_sid, auth_token)
    to_wa   = f"whatsapp:{to_phone}"
    from_wa = f"whatsapp:{from_number}"
    try:
        msg = client.messages.create(body=body, from_=from_wa, to=to_wa)
        log.info("WhatsApp sent to %s — SID=%s", to_phone, msg.sid)
    except Exception as exc:
        log.error("WhatsApp send failed to %s: %s", to_phone, exc)
        raise


def send_ticket_confirmation_wa(
    to_phone: str,
    ticket_number: str,
    lang: str = "ar",
    **kwargs,
) -> None:
    if lang == "ar":
        body = f"✅ مرحباً! تم استلام طلبك. رقم التذكرة: *{ticket_number}*\nيمكنك الرد على هذه الرسالة لإضافة تفاصيل."
    else:
        body = f"✅ Hello! Your request has been received. Ticket number: *{ticket_number}*\nYou can reply to this message to add more details."
    send_whatsapp(to_phone, body, **kwargs)


def send_status_update_wa(
    to_phone: str,
    ticket_number: str,
    status: str,
    lang: str = "ar",
    **kwargs,
) -> None:
    status_ar = {
        "open": "مفتوح", "resolved": "تم الحل", "closed": "مغلق",
        "pending_customer": "في انتظار ردك",
    }.get(status, status)
    if lang == "ar":
        body = f"📋 تحديث على تذكرتك *{ticket_number}*: الحالة الجديدة — {status_ar}"
    else:
        body = f"📋 Update on your ticket *{ticket_number}*: new status — {status}"
    send_whatsapp(to_phone, body, **kwargs)


# ── Inbound: parse Twilio webhook payload ─────────────────────────────────────

def parse_twilio_webhook(form_data: dict) -> dict:
    """
    Parse Twilio's WhatsApp webhook POST body.
    Returns normalised dict:
      - from_phone: str (e.g. "+966501234567")
      - body: str
      - media_urls: list[str]
    """
    raw_from = form_data.get("From", "")
    phone = raw_from.replace("whatsapp:", "").strip()
    return {
        "from_phone": phone,
        "body": form_data.get("Body", "").strip(),
        "media_urls": [
            form_data.get(f"MediaUrl{i}", "") for i in range(int(form_data.get("NumMedia", "0")))
        ],
    }


# ── Route inbound message to ticket ──────────────────────────────────────────

async def route_inbound_whatsapp(
    db,  # AsyncSession
    redis,
    phone: str,
    body: str,
    twilio_config: dict,
    base_url: str,
) -> str:
    """
    Find or create a ticket for this inbound WhatsApp message.
    Returns reply text to send back.
    """
    from sqlalchemy import select, or_
    from app.models.ticket import Ticket
    from app.services.ticket import create_ticket
    from app.services.timeline import add_event, EventType

    # Deduplicate: Redis key prevents processing same message twice
    dedup_key = f"wa:dedup:{phone}:{hash(body)}"
    if await redis.exists(dedup_key):
        return ""
    await redis.setex(dedup_key, 3600, "1")

    cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
    result = await db.execute(
        select(Ticket).where(
            Ticket.submitter_phone == phone,
            Ticket.status.notin_(("closed", "archived", "resolved")),
            Ticket.created_at >= cutoff,
            Ticket.deleted_at.is_(None),
        ).order_by(Ticket.created_at.desc()).limit(1)
    )
    ticket = result.scalar_one_or_none()

    if ticket:
        # Append as customer reply
        async with db.begin():
            await add_event(
                db,
                ticket_id=ticket.id,
                event_type=EventType.REPLY_CUSTOMER,
                content_ar=body,
                content_en=body,
                actor_type="customer",
                is_public=True,
            )
            if ticket.status == "pending_customer":
                ticket.status = "open"
        return f"✅ تم إضافة ردك على تذكرة {ticket.ticket_number}" if True else f"Reply added to {ticket.ticket_number}"

    # Create new ticket
    from app.schemas.ticket import TicketSubmitForm

    form = TicketSubmitForm(
        submitter_name=phone or "WhatsApp",
        submitter_phone=phone or "unknown",
        subject=body[:200] if body else "WhatsApp",
        description=(body or "WhatsApp message")[:10_000],
        channel="whatsapp",
        priority="medium",
    )
    async with db.begin():
        new_ticket = await create_ticket(db=db, redis=redis, form=form)
        await db.flush()
        ticket_number = new_ticket.ticket_number

    return f"✅ رقم تذكرتك: *{ticket_number}*. سيتواصل معك فريق الدعم قريباً."
