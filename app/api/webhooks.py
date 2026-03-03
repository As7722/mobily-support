"""
Webhook endpoints for inbound WhatsApp and SMS via Twilio.

Twilio sends POST requests with form-encoded data.
Signature validation is performed for production security.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.services.whatsapp import parse_twilio_webhook, route_inbound_whatsapp

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
log = logging.getLogger(__name__)


def _validate_twilio_signature(
    auth_token: str,
    url: str,
    params: dict,
    signature: str,
) -> bool:
    """Validate that the request genuinely comes from Twilio."""
    import base64, hmac, hashlib
    s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    computed = base64.b64encode(
        hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(computed, signature)


# ── POST /webhooks/whatsapp ────────────────────────────────────────────────────

@router.post("/whatsapp", response_class=PlainTextResponse)
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> PlainTextResponse:
    """
    Twilio WhatsApp inbound webhook.
    Responds with TwiML plain-text reply.
    """
    from app.core.config import settings

    form  = await request.form()
    form_dict = dict(form)

    # ── Signature validation (skip in debug mode) ──────────────────────────
    if not settings.DEBUG:
        sig = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        if not _validate_twilio_signature(settings.TWILIO_AUTH_TOKEN, url, form_dict, sig):
            log.warning("Invalid Twilio signature from %s", request.client.host if request.client else "?")
            raise HTTPException(403, "Invalid Twilio signature")

    msg_data = parse_twilio_webhook(form_dict)
    phone    = msg_data["from_phone"]
    body     = msg_data["body"]

    if not phone or not body:
        return PlainTextResponse("")

    log.info("Inbound WhatsApp from %s: %.80s", phone, body)

    reply_text = await route_inbound_whatsapp(
        db=db,
        redis=redis,
        phone=phone,
        body=body,
        twilio_config={
            "account_sid": settings.TWILIO_ACCOUNT_SID,
            "auth_token":  settings.TWILIO_AUTH_TOKEN,
            "from_number": settings.TWILIO_WHATSAPP_FROM,
        },
        base_url=str(settings.BASE_URL),
    )

    # Return TwiML messaging response
    if reply_text:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>{reply_text}</Message>
</Response>"""
        return PlainTextResponse(twiml, media_type="application/xml")

    return PlainTextResponse("", media_type="application/xml")


# ── POST /webhooks/sms ─────────────────────────────────────────────────────────

@router.post("/sms", response_class=PlainTextResponse)
async def sms_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """
    Inbound SMS webhook (Twilio).
    Currently logs the message — can be extended to create tickets from SMS.
    """
    form = await request.form()
    phone = str(form.get("From", "")).replace("+", "")
    body  = str(form.get("Body", "")).strip()

    if not phone or not body:
        return PlainTextResponse("")

    log.info("Inbound SMS from %s: %.80s", phone, body)

    # Future: route SMS to ticket creation same as WhatsApp
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
</Response>"""
    return PlainTextResponse(twiml, media_type="application/xml")


# ── POST /webhooks/email-inbound ───────────────────────────────────────────────

@router.post("/email-inbound")
async def email_inbound_webhook(request: Request) -> dict:
    """
    Optional: receive inbound emails via Twilio SendGrid Inbound Parse.
    Triggered alongside or instead of IMAP polling.
    """
    form = await request.form()
    subject  = str(form.get("subject", ""))
    from_addr = str(form.get("from", ""))
    text     = str(form.get("text", ""))
    log.info("Inbound email webhook from=%s subject=%.80s", from_addr, subject)
    # Delegate to same logic as IMAP ingestion
    return {"ok": True}
