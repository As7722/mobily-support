"""
Report engine — gathers data by report_type and period for PDF/Excel export and scheduled email.
Uses get_manager_kpis and related services; returns a unified structure for rendering.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticket import Ticket
from app.services.kpi import get_manager_kpis, get_sla_violations, _period_range

UTC = timezone.utc

# Report type keys and display names (i18n keys used in UI)
REPORT_TYPES: dict[str, dict[str, str]] = {
    "executive_dashboard": {"name_ar": "الملخص التنفيذي", "name_en": "Executive Dashboard"},
    "kpi_summary": {"name_ar": "ملخص الأداء", "name_en": "KPI Summary"},
    "ticket_stats": {"name_ar": "إحصائيات التذاكر", "name_en": "Ticket Stats"},
    "sla_report": {"name_ar": "تقرير SLA", "name_en": "SLA Report"},
    "agent_performance": {"name_ar": "أداء الموظفين", "name_en": "Agent Performance"},
    "department_summary": {"name_ar": "ملخص الأقسام", "name_en": "Department Summary"},
    "channel_category_mix": {"name_ar": "القنوات والفئات", "name_en": "Channel & Category"},
    "csat_quality": {"name_ar": "جودة التقييم", "name_en": "CSAT Quality"},
    "audit_summary": {"name_ar": "ملخص التدقيق", "name_en": "Audit Summary"},
    "knowledge_base": {"name_ar": "قاعدة المعرفة", "name_en": "Knowledge Base"},
    "full_report": {"name_ar": "التقرير الشامل", "name_en": "Full Report"},
}


def _period_to_kpi(period: str) -> str:
    """Map API period (today/week/month) to get_manager_kpis period."""
    if period in ("today", "week", "month"):
        return period
    return "month"


async def get_recent_tickets_for_period(
    db: AsyncSession,
    period: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch recent tickets (created or resolved in period) for report tables."""
    start, end = _period_range(_period_to_kpi(period))
    q = (
        select(Ticket)
        .where(
            Ticket.deleted_at.is_(None),
            or_(
                (Ticket.created_at >= start) & (Ticket.created_at < end),
                (Ticket.resolved_at >= start) & (Ticket.resolved_at < end),
            ),
        )
        .order_by(Ticket.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    tickets = list(result.scalars().all())
    return [
        {
            "ticket_number": t.ticket_number,
            "status": t.status,
            "priority": t.priority or "",
            "channel": t.channel or "",
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
            "resolved_at": t.resolved_at.strftime("%Y-%m-%d %H:%M") if t.resolved_at else "",
            "sla_breached": bool(t.sla_breached),
        }
        for t in tickets
    ]


async def gather_report_data(
    db: AsyncSession,
    report_type: str,
    period: str,
    redis: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Gather all data needed for a report. Returns a unified structure:
    - kpis: dict from get_manager_kpis
    - trend: list of {date, created, resolved}
    - tickets: list of ticket row dicts (for table)
    - sla_violations: list of ticket dicts (for SLA report)
    - period_label_ar, period_label_en
    """
    kpi_period = _period_to_kpi(period)
    kpis = await get_manager_kpis(db, redis, kpi_period)

    period_labels = {
        "today": ("اليوم", "Today"),
        "week": ("هذا الأسبوع", "This Week"),
        "month": ("هذا الشهر", "This Month"),
    }
    pl = period_labels.get(kpi_period, ("هذا الشهر", "This Month"))

    out: dict[str, Any] = {
        "kpis": kpis,
        "trend": kpis.get("trend", []),
        "tickets": [],
        "sla_violations": [],
        "period_label_ar": pl[0],
        "period_label_en": pl[1],
        "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }

    # Ticket list for most report types
    if report_type in (
        "executive_dashboard",
        "kpi_summary",
        "ticket_stats",
        "sla_report",
        "full_report",
    ):
        out["tickets"] = await get_recent_tickets_for_period(db, period)

    if report_type in ("sla_report", "full_report"):
        violations = await get_sla_violations(db, limit=100)
        out["sla_violations"] = [
            {
                "ticket_number": t.ticket_number,
                "status": t.status,
                "priority": t.priority or "",
                "sla_deadline": t.sla_deadline.strftime("%Y-%m-%d %H:%M") if t.sla_deadline else "",
            }
            for t in violations
        ]

    # Agent performance: top agents from same KPI period
    if report_type in ("agent_performance", "full_report"):
        from app.models.user import User
        p_start, p_end = _period_range(kpi_period)
        agents_result = await db.execute(
            select(
                User.id,
                User.full_name_ar,
                User.full_name_en,
                func.count(Ticket.id).label("resolved"),
                func.avg(Ticket.csat_score).label("csat"),
                func.avg(Ticket.total_time_seconds).label("avg_secs"),
            )
            .join(Ticket, Ticket.assigned_to == User.id, isouter=True)
            .where(
                Ticket.resolved_at >= p_start,
                Ticket.resolved_at < p_end,
                Ticket.status.in_(["resolved", "closed"]),
                Ticket.deleted_at.is_(None),
            )
            .group_by(User.id, User.full_name_ar, User.full_name_en)
            .order_by(func.count(Ticket.id).desc())
            .limit(20)
        )
        rows = agents_result.fetchall()
        out["top_agents"] = [
            {
                "full_name_ar": r.full_name_ar or "",
                "full_name_en": r.full_name_en or r.full_name_ar or "",
                "resolved": r.resolved or 0,
                "csat": round(float(r.csat), 2) if r.csat else None,
                "avg_resolution_mins": int((r.avg_secs or 0) / 60),
            }
            for r in rows
        ]
    else:
        out["top_agents"] = []

    return out


# ── PDF / Excel build (used by API export and Celery worker) ──────────────────

def _pdf_html_template() -> str:
    return """<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&family=Inter:wght@400;700&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: {font_family}, Arial, sans-serif; color: #1f2937; font-size: 13px;
    direction: {direction}; padding: 40px; }}
  .header {{ background: #00AEEF; color: white; padding: 24px; border-radius: 8px; margin-bottom: 24px; }}
  .header h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .header p {{ font-size: 12px; opacity: .9; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; text-align: center; }}
  .kpi-card .value {{ font-size: 28px; font-weight: 700; color: #00AEEF; }}
  .kpi-card .label {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th {{ background: #f9fafb; font-weight: 600; font-size: 11px; padding: 10px 12px; border-bottom: 2px solid #e5e7eb; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f3f4f6; }}
  .badge {{ display: inline-block; border-radius: 9999px; padding: 2px 8px; font-size: 11px; font-weight: 600; }}
  .badge-green {{ background: #dcfce7; color: #166534; }}
  .badge-red {{ background: #fee2e2; color: #991b1b; }}
  .footer {{ margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 12px; font-size: 10px; color: #9ca3af; text-align: center; }}
</style>
</head>
<body>
  <div class="header">
    <h1>{title}</h1>
    <p>{period_label} | {generated_at}</p>
  </div>
  <div class="kpi-grid">{kpi_cards_html}</div>
  <h3 style="margin-bottom:12px; font-size:14px;">{tickets_heading}</h3>
  <table>
    <thead><tr>
      <th>{col_number}</th><th>{col_status}</th><th>{col_priority}</th>
      <th>{col_channel}</th><th>{col_created}</th><th>{col_resolved}</th><th>SLA</th>
    </tr></thead>
    <tbody>{ticket_rows_html}</tbody>
  </table>
  <div class="footer">Mobily Technical Support — Confidential</div>
</body>
</html>"""


def _build_report_pdf_fallback(
    data: dict[str, Any],
    report_type: str,
    lang: str,
    kpis: dict,
    tickets: list[dict],
    cols: tuple,
    heading: str,
) -> bytes:
    """PDF using fpdf2 (works without WeasyPrint). Produces valid binary PDF."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("PDF generation failed. Install fpdf2: pip install fpdf2. Or export as Excel.")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    title_ar = REPORT_TYPES.get(report_type, {}).get("name_ar", "Report")
    title_en = REPORT_TYPES.get(report_type, {}).get("name_en", "Report")
    pdf.cell(0, 10, f"{title_ar} / {title_en}", ln=1)
    pdf.set_font("Helvetica", size=10)
    period_label = data.get("period_label_ar", "") if lang == "ar" else data.get("period_label_en", "")
    pdf.cell(0, 6, f"{period_label} | {data.get('generated_at', '')}", ln=1)
    pdf.ln(4)

    pdf.set_font("Helvetica", size=11)
    pdf.cell(40, 7, "Total Tickets" if lang == "en" else "Total", border=1)
    pdf.cell(30, 7, str(kpis.get("total_tickets", 0)), border=1, ln=1)
    pdf.cell(40, 7, "Resolved" if lang == "en" else "Resolved", border=1)
    pdf.cell(30, 7, str(kpis.get("resolved_tickets", 0)), border=1, ln=1)
    pdf.cell(40, 7, "SLA %" if lang == "en" else "SLA %", border=1)
    pdf.cell(30, 7, str(kpis.get("sla_compliance_pct", 0)), border=1, ln=1)
    pdf.ln(6)

    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, heading, ln=1)
    col_w = (25, 22, 18, 22, 28, 28, 18)
    for i, c in enumerate(cols):
        pdf.cell(col_w[i], 6, c[:12] if isinstance(c, str) else str(c)[:12], border=1)
    pdf.cell(col_w[6], 6, "SLA", border=1, ln=1)
    for t in tickets[:50]:
        pdf.cell(col_w[0], 5, ((t.get("ticket_number") or ""))[:14], border=1)
        pdf.cell(col_w[1], 5, (t.get("status") or "")[:10], border=1)
        pdf.cell(col_w[2], 5, (t.get("priority") or "")[:8], border=1)
        pdf.cell(col_w[3], 5, (t.get("channel") or "")[:10], border=1)
        pdf.cell(col_w[4], 5, (t.get("created_at") or "")[:14], border=1)
        pdf.cell(col_w[5], 5, (t.get("resolved_at") or "-")[:14], border=1)
        pdf.cell(col_w[6], 5, "OK" if not t.get("sla_breached") else "Breach", border=1, ln=1)
    pdf.ln(4)
    pdf.set_font("Helvetica", size=8)
    pdf.cell(0, 5, "Mobily Technical Support - Confidential", ln=1)

    out = pdf.output()
    if isinstance(out, bytes):
        return out
    if isinstance(out, str):
        return out.encode("utf-8")
    return b""


def build_report_pdf(data: dict[str, Any], report_type: str, lang: str) -> bytes:
    """Build PDF bytes from gather_report_data output. Uses fpdf2 for reliable binary PDF output."""
    kpis = data.get("kpis", {})
    tickets = data.get("tickets", [])
    if lang == "ar":
        cols = ("الرقم", "الحالة", "الأولوية", "القناة", "التاريخ", "الحل")
        heading = "قائمة التذاكر"
    else:
        cols = ("Number", "Status", "Priority", "Channel", "Created", "Resolved")
        heading = "Ticket List"
    return _build_report_pdf_fallback(data, report_type, lang, kpis, tickets, cols, heading)


def build_report_xlsx(data: dict[str, Any], report_type: str, lang: str) -> bytes:
    """Build Excel bytes from gather_report_data output."""
    import io
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill
    except ImportError:
        raise RuntimeError("openpyxl not installed")

    wb = openpyxl.Workbook()
    ws = wb.active
    if ws is None:
        raise RuntimeError("No active sheet")
    ws.title = "Summary"
    title_ar = REPORT_TYPES.get(report_type, {}).get("name_ar", "تقرير")
    title_en = REPORT_TYPES.get(report_type, {}).get("name_en", "Report")
    ws["A1"] = f"{title_ar} / {title_en}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = data.get("period_label_ar", "") + " / " + data.get("period_label_en", "")
    ws["A3"] = "Generated: " + data.get("generated_at", "")
    kpis = data.get("kpis", {})
    ws["A5"] = "Total Tickets" if lang == "en" else "إجمالي التذاكر"
    ws["B5"] = kpis.get("total_tickets", 0)
    ws["A6"] = "Resolved" if lang == "en" else "تم الحل"
    ws["B6"] = kpis.get("resolved_tickets", 0)
    ws["A7"] = "SLA %" if lang == "en" else "التزام SLA"
    ws["B7"] = kpis.get("sla_compliance_pct", 0)
    ws["A8"] = "SLA Breaches" if lang == "en" else "انتهاكات SLA"
    ws["B8"] = kpis.get("sla_breached", 0)

    tickets = data.get("tickets", [])
    if tickets:
        ws2 = wb.create_sheet("Tickets", 1)
        headers = ["#", "Status", "Priority", "Channel", "Created", "Resolved", "SLA"] if lang == "en" else ["الرقم", "الحالة", "الأولوية", "القناة", "التاريخ", "الحل", "SLA"]
        for c, h in enumerate(headers, 1):
            cell = ws2.cell(row=1, column=c, value=h)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="00AEEF", end_color="00AEEF", fill_type="solid")
        for r, t in enumerate(tickets, 2):
            ws2.cell(row=r, column=1, value=t.get("ticket_number", ""))
            ws2.cell(row=r, column=2, value=t.get("status", ""))
            ws2.cell(row=r, column=3, value=t.get("priority", ""))
            ws2.cell(row=r, column=4, value=t.get("channel", ""))
            ws2.cell(row=r, column=5, value=t.get("created_at", ""))
            ws2.cell(row=r, column=6, value=t.get("resolved_at", "") or "")
            ws2.cell(row=r, column=7, value="Breached" if t.get("sla_breached") else "OK")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
