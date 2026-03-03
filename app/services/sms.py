"""
SMS Integration via Twilio.

Use cases:
  - SLA warning → agent's registered phone
  - Critical SLA breach → supervisor's phone
  - OTP for 2FA (delegates to auth module, but utility lives here)
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def _client(account_sid: str, auth_token: str):
    from twilio.rest import Client  # type: ignore[import-untyped]
    return Client(account_sid, auth_token)


def send_sms(
    to_phone: str,
    body: str,
    *,
    from_number: str,
    account_sid: str,
    auth_token: str,
) -> Optional[str]:
    """Send SMS. Returns Twilio message SID, or None on failure."""
    try:
        client = _client(account_sid, auth_token)
        msg = client.messages.create(body=body[:1600], from_=from_number, to=to_phone)
        log.info("SMS sent to %s — SID=%s", to_phone, msg.sid)
        return msg.sid
    except Exception as exc:
        log.error("SMS failed to %s: %s", to_phone, exc)
        return None


def send_sla_warning_sms(
    agent_phone: str,
    ticket_number: str,
    remaining_minutes: int,
    lang: str = "ar",
    **kwargs,
) -> None:
    if lang == "ar":
        body = f"⚠️ موبايلي: تذكرة {ticket_number} ستنتهي مدة SLA خلال {remaining_minutes} دقيقة."
    else:
        body = f"⚠️ Mobily: Ticket {ticket_number} SLA expires in {remaining_minutes} min."
    send_sms(agent_phone, body, **kwargs)


def send_sla_breach_sms(
    supervisor_phone: str,
    ticket_number: str,
    agent_name: str,
    lang: str = "ar",
    **kwargs,
) -> None:
    if lang == "ar":
        body = f"🚨 موبايلي: انتهاك SLA! تذكرة {ticket_number} — الموظف: {agent_name}"
    else:
        body = f"🚨 Mobily: SLA BREACH! Ticket {ticket_number} — Agent: {agent_name}"
    send_sms(supervisor_phone, body, **kwargs)


def send_otp_sms(
    phone: str,
    otp_code: str,
    lang: str = "ar",
    **kwargs,
) -> None:
    if lang == "ar":
        body = f"موبايلي: رمز التحقق الخاص بك هو {otp_code}. صالح لمدة 10 دقائق."
    else:
        body = f"Mobily: Your verification code is {otp_code}. Valid for 10 minutes."
    send_sms(phone, body, **kwargs)
