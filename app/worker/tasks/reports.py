"""
Report Generation — Celery Beat scheduled + on-demand.

PDF generation via WeasyPrint (handles Arabic RTL natively via CSS).
Falls back to plain HTML attachment if WeasyPrint unavailable.

Bilingual: renders Arabic or English based on report config.
Delivers via email to configured recipients.
"""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)
UTC = timezone.utc


# ── PDF template ──────────────────────────────────────────────────────────────

_PDF_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&family=Inter:wght@400;700&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: {font_family}, Arial, sans-serif;
    color: #1f2937;
    font-size: 13px;
    direction: {direction};
    padding: 40px;
  }}
  .header {{
    background: #6366f1;
    color: white;
    padding: 24px;
    border-radius: 8px;
    margin-bottom: 24px;
  }}
  .header h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .header p  {{ font-size: 12px; opacity: .85; }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}
  .kpi-card .value {{ font-size: 28px; font-weight: 700; color: #6366f1; }}
  .kpi-card .label {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th {{ background: #f9fafb; font-weight: 600; font-size: 11px; text-transform: uppercase;
       letter-spacing: .05em; color: #6b7280; padding: 10px 12px; border-bottom: 2px solid #e5e7eb; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f3f4f6; }}
  .badge {{ display: inline-block; border-radius: 9999px; padding: 2px 8px; font-size: 11px; font-weight: 600; }}
  .badge-green  {{ background: #dcfce7; color: #166534; }}
  .badge-red    {{ background: #fee2e2; color: #991b1b; }}
  .badge-yellow {{ background: #fef9c3; color: #854d0e; }}
  .footer {{ margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 12px;
             font-size: 10px; color: #9ca3af; text-align: center; }}
</style>
</head>
<body>
  <div class="header">
    <h1>موبايلي — تقرير الدعم الفني | Mobily Technical Support Report</h1>
    <p>{period_label} | Generated: {generated_at}</p>
  </div>

  <div class="kpi-grid">
    {kpi_cards_html}
  </div>

  <h3 style="margin-bottom:12px; font-size:14px; color:#374151;">
    {tickets_heading}
  </h3>
  <table>
    <thead>
      <tr>
        <th>{col_number}</th>
        <th>{col_status}</th>
        <th>{col_priority}</th>
        <th>{col_channel}</th>
        <th>{col_created}</th>
        <th>{col_resolved}</th>
        <th>SLA</th>
      </tr>
    </thead>
    <tbody>
      {ticket_rows_html}
    </tbody>
  </table>

  <div class="footer">
    Mobily Technical Support System — Confidential
  </div>
</body>
</html>"""


def _kpi_card(value: str, label: str) -> str:
    return f'<div class="kpi-card"><div class="value">{value}</div><div class="label">{label}</div></div>'


def _ticket_row(t: dict, lang: str) -> str:
    sla_badge = (
        '<span class="badge badge-red">⚠️ Breached</span>'
        if t.get("sla_breached")
        else '<span class="badge badge-green">✅ OK</span>'
    )
    return (
        f"<tr>"
        f"<td style='font-family:monospace'>{t.get('ticket_number','')}</td>"
        f"<td>{t.get('status','')}</td>"
        f"<td>{t.get('priority','')}</td>"
        f"<td>{t.get('channel','')}</td>"
        f"<td>{t.get('created_at','')}</td>"
        f"<td>{t.get('resolved_at','') or '—'}</td>"
        f"<td>{sla_badge}</td>"
        f"</tr>"
    )


def _render_pdf_html(kpis: dict, tickets: list[dict], lang: str, period_label: str) -> str:
    direction  = "rtl" if lang == "ar" else "ltr"
    font_family = "Tajawal" if lang == "ar" else "Inter"

    kpi_cards = "".join([
        _kpi_card(str(kpis.get("total_tickets", 0)), "Total Tickets" if lang == "en" else "إجمالي التذاكر"),
        _kpi_card(str(kpis.get("resolved_tickets", 0)), "Resolved" if lang == "en" else "تم الحل"),
        _kpi_card(str(kpis.get("sla_compliance_pct", 0)) + "%", "SLA Compliance" if lang == "en" else "التزام SLA"),
        _kpi_card(str(kpis.get("avg_resolution_mins", 0)) + " min", "Avg Resolution" if lang == "en" else "متوسط الحل"),
        _kpi_card(str(kpis.get("sla_breached", 0)), "SLA Breaches" if lang == "en" else "انتهاكات SLA"),
        _kpi_card(
            f"{kpis.get('avg_csat') or '—'}",
            "Avg CSAT" if lang == "en" else "متوسط التقييم"
        ),
    ])

    ticket_rows = "".join(_ticket_row(t, lang) for t in tickets)

    if lang == "ar":
        cols = ("الرقم", "الحالة", "الأولوية", "القناة", "التاريخ", "الحل")
        heading = "قائمة التذاكر"
    else:
        cols = ("Number", "Status", "Priority", "Channel", "Created", "Resolved")
        heading = "Ticket List"

    return _PDF_HTML_TEMPLATE.format(
        lang=lang, direction=direction, font_family=font_family,
        period_label=period_label,
        generated_at=datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
        kpi_cards_html=kpi_cards,
        tickets_heading=heading,
        col_number=cols[0], col_status=cols[1], col_priority=cols[2],
        col_channel=cols[3], col_created=cols[4], col_resolved=cols[5],
        ticket_rows_html=ticket_rows,
    )


def _generate_pdf(html: str) -> bytes:
    try:
        import weasyprint  # type: ignore[import-untyped]
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
        return pdf_bytes
    except ImportError:
        log.warning("WeasyPrint not installed — returning HTML as bytes")
        return html.encode("utf-8")
    except Exception as exc:
        log.error("PDF generation failed: %s", exc)
        return html.encode("utf-8")


# ── Celery tasks ──────────────────────────────────────────────────────────────

@celery_app.task(name="reports.generate_scheduled", bind=True, max_retries=2)
def generate_scheduled_report(
    self,
    scheduled_report_id: Optional[str] = None,
    period: Optional[str] = None,
    lang: Optional[str] = None,
    recipients: Optional[list[str]] = None,
) -> dict:
    """
    Generate and email a scheduled report.
    When scheduled_report_id is set, load config from DB (report_config, format, language, recipients).
    Otherwise use legacy args: period, lang, recipients.
    """
    return asyncio.get_event_loop().run_until_complete(
        _generate_and_send_by_id(scheduled_report_id, period=period, lang=lang, recipients=recipients or [])
    )


async def _generate_and_send_by_id(
    scheduled_report_id: Optional[str],
    period: Optional[str] = None,
    lang: Optional[str] = None,
    recipients: Optional[list[str]] = None,
) -> dict:
    from app.core.config import settings
    from app.services.reports import gather_report_data, build_report_pdf, build_report_xlsx

    row = None
    async for db in _get_db():
        if scheduled_report_id:
            from app.models.report import ScheduledReport
            from sqlalchemy import select

            result = await db.execute(
                select(ScheduledReport).where(ScheduledReport.id == uuid.UUID(scheduled_report_id))
            )
            row = result.scalar_one_or_none()
            if not row or not row.is_active:
                return {"ok": False, "reason": "report not found or inactive"}
            cfg = row.report_config or {}
            report_type = cfg.get("report_type", "kpi_summary")
            period = row.frequency
            lang = row.language or "ar"
            recipients = list(row.recipients or [])
            fmt = (row.format or "pdf").lower()
            name_ar = row.name_ar or "تقرير"
            name_en = row.name_en or "Report"
        else:
            report_type = "kpi_summary"
            period = period or "weekly"
            lang = lang or "ar"
            recipients = list(recipients or [])
            fmt = "pdf"
            name_ar = "تقرير"
            name_en = "Report"

        if not recipients:
            return {"ok": False, "recipients": 0}

        period_map = {"daily": "today", "weekly": "week", "monthly": "month"}
        report_period = period_map.get(period, "month")

        data = await gather_report_data(db, report_type, report_period, None)
        if fmt == "xlsx":
            body = build_report_xlsx(data, report_type, lang)
            filename = f"report_{report_period}.xlsx"
        else:
            body = build_report_pdf(data, report_type, lang)
            filename = f"report_{report_period}.pdf"

        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        import aiosmtplib

        subject = f"{name_ar} / {name_en} — {data.get('period_label_en', report_period)}"
        for recipient in recipients:
            msg = MIMEMultipart()
            msg["From"] = settings.SMTP_USER
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText("<p>Please find the attached report.</p>", "html"))
            subtype = "pdf" if fmt == "pdf" else "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            att = MIMEApplication(body, _subtype=subtype)
            att.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(att)
            try:
                await aiosmtplib.send(
                    msg,
                    hostname=settings.SMTP_HOST,
                    port=settings.SMTP_PORT,
                    username=settings.SMTP_USER,
                    password=settings.SMTP_PASSWORD,
                    use_tls=settings.SMTP_TLS,
                    timeout=30,
                )
            except Exception as exc:
                log.error("Failed to send report to %s: %s", recipient, exc)

        if scheduled_report_id and row:
            row.last_sent_at = datetime.now(UTC)
            await db.commit()

    return {"ok": True, "recipients": len(recipients)}


@celery_app.task(name="reports.run_scheduled_due")
def run_scheduled_reports_due() -> dict:
    """
    Beat runs this daily at 07:00; enqueues generate_scheduled_report for each
    active report whose frequency is due (daily=every day, weekly=Sunday, monthly=1st).
    """
    return asyncio.get_event_loop().run_until_complete(_run_due())


async def _run_due() -> dict:
    from app.models.report import ScheduledReport
    from sqlalchemy import select

    now = datetime.now(UTC)
    due_ids: list[str] = []
    async for db in _get_db():
        result = await db.execute(
            select(ScheduledReport).where(ScheduledReport.is_active.is_(True))
        )
        for row in result.scalars().all():
            due = False
            if row.frequency == "daily":
                due = now.hour == 7
            elif row.frequency == "weekly":
                due = now.weekday() == 6 and now.hour == 7  # Sunday
            elif row.frequency == "monthly":
                due = now.day == 1 and now.hour == 7
            if due:
                due_ids.append(str(row.id))
        break
    for rid in due_ids:
        generate_scheduled_report.delay(rid)
    return {"ok": True, "queued": len(due_ids)}


async def _get_db():
    from app.core.database import get_async_session
    async for db in get_async_session():
        yield db


# ── Gamification Beat tasks ───────────────────────────────────────────────────

@celery_app.task(name="gamification.daily_leaderboard")
def daily_leaderboard() -> None:
    asyncio.get_event_loop().run_until_complete(_snapshot("daily"))


@celery_app.task(name="gamification.weekly_leaderboard")
def weekly_leaderboard() -> None:
    asyncio.get_event_loop().run_until_complete(_snapshot("weekly"))


@celery_app.task(name="gamification.monthly_leaderboard")
def monthly_leaderboard() -> None:
    asyncio.get_event_loop().run_until_complete(_snapshot("monthly"))


@celery_app.task(name="gamification.employee_of_month")
def employee_of_month() -> None:
    asyncio.get_event_loop().run_until_complete(_compute_eom())


async def _snapshot(period: str) -> None:
    from app.services.gamification import build_leaderboard_snapshot
    async for db in _get_db():
        async with db.begin():
            await build_leaderboard_snapshot(db, period)


async def _compute_eom() -> None:
    from app.services.gamification import compute_employee_of_month
    async for db in _get_db():
        winner = await compute_employee_of_month(db)
        if winner:
            log.info("Employee of Month computed: %s", winner)
