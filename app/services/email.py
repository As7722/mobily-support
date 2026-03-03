"""
Email Service
=============
Outbound  — aiosmtplib via SMTP (TLS).
Inbound   — IMAP polling (called from Celery task, see app/worker/tasks/email_tasks.py).

Bilingual: recipient's preferred_language (ar | en) picks the correct template rendering.
Spam-loop guard: every outbound message sets X-Ticket-ID header; inbound parsing skips
messages that already carry this header to prevent reply loops.
"""
from __future__ import annotations

import asyncio
import email as _email_lib
import imaplib
import logging
import re
import uuid
from datetime import datetime, timezone
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

import aiosmtplib
from jinja2 import Environment, BaseLoader

log = logging.getLogger(__name__)
UTC = timezone.utc

TICKET_RE = re.compile(r"\[?(TKT-\d{8}-\d{4})\]?", re.IGNORECASE)


# ── Jinja2 inline email templates ─────────────────────────────────────────────

_TEMPLATES: dict[str, dict[str, str]] = {
    "ticket_confirmation": {
        "subject_ar": "تأكيد استلام طلبك — {ticket_number}",
        "subject_en": "Your request has been received — {ticket_number}",
        "body_ar": """
<div dir="rtl" style="font-family: Tajawal, Arial, sans-serif; color: #1f2937; max-width: 600px; margin: 0 auto;">
  <div style="background: #6366f1; padding: 24px; border-radius: 12px 12px 0 0;">
    <h1 style="color: white; margin: 0; font-size: 20px;">موبايلي — دعم فني</h1>
  </div>
  <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
    <p>مرحباً <strong>{name}</strong>،</p>
    <p>تم استلام طلبك بنجاح. رقم التذكرة الخاص بك هو:</p>
    <div style="background: #ede9fe; border-radius: 8px; padding: 16px; text-align: center; margin: 16px 0;">
      <span style="font-family: monospace; font-size: 22px; font-weight: bold; color: #6366f1;">{ticket_number}</span>
    </div>
    <p>يمكنك متابعة حالة طلبك عبر الرابط التالي:</p>
    <a href="{public_url}" style="display: inline-block; background: #6366f1; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none;">متابعة الطلب</a>
    <p style="color: #6b7280; font-size: 12px; margin-top: 24px;">سيتم الرد خلال {sla_hours} ساعة عمل.</p>
  </div>
</div>""",
        "body_en": """
<div style="font-family: Inter, Arial, sans-serif; color: #1f2937; max-width: 600px; margin: 0 auto;">
  <div style="background: #6366f1; padding: 24px; border-radius: 12px 12px 0 0;">
    <h1 style="color: white; margin: 0; font-size: 20px;">Mobily — Technical Support</h1>
  </div>
  <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
    <p>Hello <strong>{name}</strong>,</p>
    <p>Your request has been received. Your ticket number is:</p>
    <div style="background: #ede9fe; border-radius: 8px; padding: 16px; text-align: center; margin: 16px 0;">
      <span style="font-family: monospace; font-size: 22px; font-weight: bold; color: #6366f1;">{ticket_number}</span>
    </div>
    <p>Track your request status:</p>
    <a href="{public_url}" style="display: inline-block; background: #6366f1; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none;">Track Ticket</a>
    <p style="color: #6b7280; font-size: 12px; margin-top: 24px;">We will respond within {sla_hours} business hours.</p>
  </div>
</div>""",
    },
    "ticket_reply": {
        "subject_ar": "رد جديد على طلبك — {ticket_number}",
        "subject_en": "New reply on your request — {ticket_number}",
        "body_ar": """
<div dir="rtl" style="font-family: Tajawal, Arial, sans-serif; color: #1f2937; max-width: 600px; margin: 0 auto;">
  <div style="background: #6366f1; padding: 20px; border-radius: 12px 12px 0 0;">
    <h2 style="color: white; margin: 0; font-size: 16px;">رد من فريق الدعم</h2>
  </div>
  <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
    <p>مرحباً <strong>{name}</strong>، لديك رد جديد على تذكرتك <strong>{ticket_number}</strong>:</p>
    <blockquote style="border-right: 4px solid #6366f1; margin: 16px 0; padding: 12px 16px; background: white; border-radius: 4px;">
      {reply_content}
    </blockquote>
    <a href="{public_url}" style="display: inline-block; background: #6366f1; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none;">عرض التذكرة</a>
  </div>
</div>""",
        "body_en": """
<div style="font-family: Inter, Arial, sans-serif; color: #1f2937; max-width: 600px; margin: 0 auto;">
  <div style="background: #6366f1; padding: 20px; border-radius: 12px 12px 0 0;">
    <h2 style="color: white; margin: 0; font-size: 16px;">Support team reply</h2>
  </div>
  <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
    <p>Hello <strong>{name}</strong>, you have a new reply on ticket <strong>{ticket_number}</strong>:</p>
    <blockquote style="border-left: 4px solid #6366f1; margin: 16px 0; padding: 12px 16px; background: white; border-radius: 4px;">
      {reply_content}
    </blockquote>
    <a href="{public_url}" style="display: inline-block; background: #6366f1; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none;">View Ticket</a>
  </div>
</div>""",
    },
    "csat_survey": {
        "subject_ar": "كيف كانت تجربتك؟ — {ticket_number}",
        "subject_en": "How was your experience? — {ticket_number}",
        "body_ar": """
<div dir="rtl" style="font-family: Tajawal, Arial, sans-serif; color: #1f2937; max-width: 600px; margin: 0 auto;">
  <div style="background: #f59e0b; padding: 20px; border-radius: 12px 12px 0 0;">
    <h2 style="color: white; margin: 0;">⭐ قيّم تجربتك</h2>
  </div>
  <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
    <p>مرحباً <strong>{name}</strong>، تم حل طلبك <strong>{ticket_number}</strong>.</p>
    <p>رأيك يهمنا! انقر على رابط التقييم:</p>
    <a href="{csat_url}" style="display: inline-block; background: #f59e0b; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-size: 16px;">تقييم الخدمة ⭐</a>
  </div>
</div>""",
        "body_en": """
<div style="font-family: Inter, Arial, sans-serif; color: #1f2937; max-width: 600px; margin: 0 auto;">
  <div style="background: #f59e0b; padding: 20px; border-radius: 12px 12px 0 0;">
    <h2 style="color: white; margin: 0;">⭐ Rate Your Experience</h2>
  </div>
  <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
    <p>Hello <strong>{name}</strong>, your ticket <strong>{ticket_number}</strong> has been resolved.</p>
    <p>Your feedback matters! Click to rate:</p>
    <a href="{csat_url}" style="display: inline-block; background: #f59e0b; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-size: 16px;">Rate Service ⭐</a>
  </div>
</div>""",
    },
    "sla_warning": {
        "subject_ar": "⚠️ تحذير SLA — {ticket_number}",
        "subject_en": "⚠️ SLA Warning — {ticket_number}",
        "body_ar": """<p dir="rtl">تحذير: اقترب موعد SLA للتذكرة {ticket_number}. المتبقي: {remaining}.</p>""",
        "body_en": """<p>Warning: SLA deadline approaching for ticket {ticket_number}. Time remaining: {remaining}.</p>""",
    },
}


def _render(template_name: str, lang: str, **kwargs: str) -> tuple[str, str]:
    """Returns (subject, html_body) for the given template and language."""
    tpl = _TEMPLATES[template_name]
    subject = tpl[f"subject_{lang}"].format(**kwargs)
    body    = tpl[f"body_{lang}"].format(**kwargs)
    return subject, body


# ── Outbound: send email via aiosmtplib ───────────────────────────────────────

async def send_email(
    to_address: str,
    subject: str,
    html_body: str,
    ticket_id: Optional[str] = None,
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_name: str = "Mobily Support",
    use_tls: bool = True,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"]    = formataddr((from_name, smtp_user))
    msg["To"]      = to_address
    msg["Subject"] = subject
    if ticket_id:
        msg["X-Ticket-ID"] = ticket_id  # spam-loop guard

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            use_tls=use_tls,
            timeout=30,
        )
        log.info("Email sent to %s [subject: %s]", to_address, subject)
    except Exception as exc:
        log.error("Failed to send email to %s: %s", to_address, exc)
        raise


# ── Convenience wrappers ──────────────────────────────────────────────────────

async def send_confirmation(
    to: str,
    name: str,
    ticket_number: str,
    ticket_id: str,
    public_url: str,
    sla_hours: int = 8,
    lang: str = "ar",
    **smtp_kwargs,
) -> None:
    subject, body = _render("ticket_confirmation", lang,
                             name=name, ticket_number=ticket_number,
                             public_url=public_url, sla_hours=str(sla_hours))
    await send_email(to, subject, body, ticket_id=ticket_id, **smtp_kwargs)


async def send_reply_notification(
    to: str,
    name: str,
    ticket_number: str,
    ticket_id: str,
    reply_content: str,
    public_url: str,
    lang: str = "ar",
    **smtp_kwargs,
) -> None:
    subject, body = _render("ticket_reply", lang,
                             name=name, ticket_number=ticket_number,
                             reply_content=reply_content, public_url=public_url)
    await send_email(to, subject, body, ticket_id=ticket_id, **smtp_kwargs)


async def send_csat(
    to: str,
    name: str,
    ticket_number: str,
    ticket_id: str,
    csat_url: str,
    lang: str = "ar",
    **smtp_kwargs,
) -> None:
    subject, body = _render("csat_survey", lang,
                             name=name, ticket_number=ticket_number, csat_url=csat_url)
    await send_email(to, subject, body, ticket_id=ticket_id, **smtp_kwargs)


async def send_bulk_email(
    recipients: list[str],
    subject: str,
    body: str,
    **smtp_kwargs,
) -> int:
    """Send a plain HTML email to multiple recipients. Returns count of sent."""
    import os

    smtp_host = smtp_kwargs.get("smtp_host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(smtp_kwargs.get("smtp_port") or os.getenv("SMTP_PORT", "587"))
    smtp_user = smtp_kwargs.get("smtp_user") or os.getenv("SMTP_USER", "")
    smtp_pass = smtp_kwargs.get("smtp_password") or os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_pass:
        log.warning("SMTP not configured — broadcast skipped (%d recipients)", len(recipients))
        return 0

    sent = 0
    html = f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;"><h2>{subject}</h2><p>{body}</p></div>'

    for addr in recipients:
        try:
            await send_email(
                addr, subject, html,
                smtp_host=smtp_host, smtp_port=smtp_port,
                smtp_user=smtp_user, smtp_password=smtp_pass,
                from_name="Mobily Support",
            )
            sent += 1
        except Exception:
            log.warning("Failed to send broadcast to %s", addr)

    return sent


async def send_sla_warning(
    to: str,
    ticket_number: str,
    ticket_id: str,
    remaining: str,
    lang: str = "ar",
    **smtp_kwargs,
) -> None:
    subject, body = _render("sla_warning", lang,
                             ticket_number=ticket_number, remaining=remaining)
    await send_email(to, subject, body, ticket_id=ticket_id, **smtp_kwargs)


# ── Inbound: IMAP polling ─────────────────────────────────────────────────────

def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            decoded.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(raw))
    return " ".join(decoded).strip()


def _extract_body(msg: _email_lib.message.Message) -> str:
    """Extract plain-text or HTML body from email."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if ctype == "text/html":
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


def _get_attachments(msg: _email_lib.message.Message) -> list[tuple[str, bytes]]:
    """Returns list of (filename, data) for each attachment."""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = _decode_header(part.get_filename()) or "attachment"
                data = part.get_payload(decode=True) or b""
                attachments.append((filename, data))
    return attachments


def poll_imap_inbox(
    imap_host: str,
    imap_port: int,
    imap_user: str,
    imap_password: str,
    use_ssl: bool = True,
) -> list[dict]:
    """
    Synchronous IMAP poll — returns list of parsed message dicts.
    Called from a Celery task (runs in a thread pool).

    Each dict contains:
      - uid: bytes
      - subject: str
      - sender: str (email address)
      - sender_name: str
      - body: str
      - ticket_number: str | None  (extracted from subject [TKT-...])
      - ticket_id_header: str | None  (X-Ticket-ID header — spam guard)
      - attachments: list[tuple[str, bytes]]
    """
    imap_cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    results: list[dict] = []

    try:
        conn = imap_cls(imap_host, imap_port)
        conn.login(imap_user, imap_password)
        conn.select("INBOX")
        _, uids = conn.uid("search", None, "UNSEEN")

        for uid in (uids[0] or b"").split():
            _, raw = conn.uid("fetch", uid, "(RFC822)")
            if not raw or not raw[0]:
                continue
            raw_email = raw[0][1] if isinstance(raw[0], tuple) else raw[0]
            msg = _email_lib.message_from_bytes(raw_email)

            subject = _decode_header(msg.get("Subject"))
            sender  = msg.get("From", "")
            # Extract email address from "Name <email>" format
            m = re.search(r"<(.+?)>", sender)
            sender_email = m.group(1) if m else sender.strip()
            sender_name  = sender.split("<")[0].strip().strip('"') if "<" in sender else sender_email

            ticket_id_header = msg.get("X-Ticket-ID")  # spam-loop guard
            ticket_number    = None
            match = TICKET_RE.search(subject)
            if match:
                ticket_number = match.group(1).upper()

            body        = _extract_body(msg)
            attachments = _get_attachments(msg)

            # Mark as seen
            conn.uid("store", uid, "+FLAGS", "\\Seen")

            results.append({
                "uid": uid.decode(),
                "subject": subject,
                "sender": sender_email,
                "sender_name": sender_name,
                "body": body,
                "ticket_number": ticket_number,
                "ticket_id_header": ticket_id_header,
                "attachments": attachments,
            })

        conn.logout()
    except Exception as exc:
        log.error("IMAP poll failed: %s", exc)

    return results
