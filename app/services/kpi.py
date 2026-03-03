"""
KPI Service — provides employee, supervisor, and manager-level metrics.
All queries use async SQLAlchemy.  Redis caching keeps expensive aggregations fast.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket
from app.models.user import User

UTC = timezone.utc


def _today_range() -> tuple[datetime, datetime]:
    today = date.today()
    start = datetime(today.year, today.month, today.day, tzinfo=UTC)
    end   = start + timedelta(days=1)
    return start, end


def _month_range() -> tuple[datetime, datetime]:
    today = date.today()
    start = datetime(today.year, today.month, 1, tzinfo=UTC)
    end   = datetime(today.year + (today.month // 12), (today.month % 12) + 1, 1, tzinfo=UTC)
    return start, end


def _period_range(period: str) -> tuple[datetime, datetime]:
    """Return (start, end) for the requested period."""
    now   = datetime.now(tz=UTC)
    today = now.date()
    if period == "today":
        start = datetime(today.year, today.month, today.day, tzinfo=UTC)
        end   = start + timedelta(days=1)
    elif period == "week":
        start = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=today.weekday())
        end   = start + timedelta(days=7)
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        start = datetime(today.year, q_month, 1, tzinfo=UTC)
        next_q = q_month + 3
        end = datetime(today.year + (1 if next_q > 12 else 0), (next_q - 1) % 12 + 1, 1, tzinfo=UTC)
    elif period == "year":
        start = datetime(today.year, 1, 1, tzinfo=UTC)
        end   = datetime(today.year + 1, 1, 1, tzinfo=UTC)
    else:  # month (default)
        start = datetime(today.year, today.month, 1, tzinfo=UTC)
        end   = datetime(today.year + (today.month // 12), (today.month % 12) + 1, 1, tzinfo=UTC)
    return start, end


# ── Employee KPIs ─────────────────────────────────────────────────────────────

async def get_employee_kpis(
    db: AsyncSession,
    user_id: uuid.UUID,
    redis=None,
) -> dict[str, Any]:
    cache_key = f"kpi:emp:{user_id}:{date.today()}"
    if redis:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    today_start, today_end = _today_range()
    month_start, month_end = _month_range()

    # Resolved today
    resolved_today = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == user_id,
            Ticket.resolved_at >= today_start,
            Ticket.resolved_at < today_end,
        )
    ) or 0

    # Avg resolution time today (seconds)
    avg_res_secs = await db.scalar(
        select(func.avg(Ticket.total_time_seconds)).where(
            Ticket.assigned_to == user_id,
            Ticket.resolved_at >= month_start,
            Ticket.resolved_at < month_end,
            Ticket.total_time_seconds > 0,
        )
    )
    avg_res_mins = int((avg_res_secs or 0) / 60)

    # CSAT this month (avg csat_score)
    csat_avg = await db.scalar(
        select(func.avg(cast(Ticket.csat_score, Float))).where(
            Ticket.assigned_to == user_id,
            Ticket.csat_score.isnot(None),
            Ticket.resolved_at >= month_start,
            Ticket.resolved_at < month_end,
        )
    )

    # SLA compliance this month
    total_resolved = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == user_id,
            Ticket.resolved_at >= month_start,
            Ticket.resolved_at < month_end,
        )
    ) or 0
    resolved_on_time = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == user_id,
            Ticket.resolved_at >= month_start,
            Ticket.resolved_at < month_end,
            Ticket.sla_breached.is_(False),
        )
    ) or 0
    sla_pct = round((resolved_on_time / total_resolved * 100) if total_resolved else 100, 1)

    # Current workload (active tickets)
    workload = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == user_id,
            Ticket.status.in_(("new", "open", "pending_customer", "pending_3rd")),
            Ticket.deleted_at.is_(None),
        )
    ) or 0

    # Peer rank this month (lower rank = better)
    # Rank by resolved count descending among all agents
    peer_ranks = await db.execute(
        select(Ticket.assigned_to, func.count(Ticket.id).label("cnt"))
        .where(
            Ticket.assigned_to.isnot(None),
            Ticket.resolved_at >= month_start,
            Ticket.resolved_at < month_end,
        )
        .group_by(Ticket.assigned_to)
        .order_by(func.count(Ticket.id).desc())
    )
    peers_list = peer_ranks.fetchall()
    total_peers = len(peers_list)
    rank = 1
    for i, (uid, _) in enumerate(peers_list, start=1):
        if uid == user_id:
            rank = i
            break

    result = {
        "resolved_today": resolved_today,
        "avg_resolution_mins": avg_res_mins,
        "csat_avg": round(float(csat_avg), 2) if csat_avg else None,
        "sla_compliance_pct": sla_pct,
        "workload": workload,
        "rank": rank,
        "total_peers": max(total_peers, 1),
    }

    if redis:
        await redis.setex(cache_key, 300, json.dumps(result))  # 5-min cache
    return result


# ── Supervisor KPIs ───────────────────────────────────────────────────────────

async def get_team_workload(
    db: AsyncSession,
    dept_id: Optional[uuid.UUID] = None,
) -> list[dict[str, Any]]:
    """Per-agent workload snapshot — used in supervisor workload table."""
    now   = datetime.now(tz=UTC)
    today_start, today_end = _today_range()

    agents_q = select(User).where(
        User.role == "employee",
        User.is_active.is_(True),
        User.deleted_at.is_(None),
    )
    if dept_id:
        agents_q = agents_q.where(User.department_id == dept_id)
    agents_result = await db.execute(agents_q)
    agents = list(agents_result.scalars().all())

    rows = []
    for agent in agents:
        active_tickets = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent.id,
                Ticket.status.in_(("new", "open", "pending_customer")),
                Ticket.deleted_at.is_(None),
            )
        ) or 0
        resolved_today = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent.id,
                Ticket.resolved_at >= today_start,
                Ticket.resolved_at < today_end,
            )
        ) or 0
        # SLA breaches
        breaches = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent.id,
                Ticket.sla_breached.is_(True),
                Ticket.status.notin_(("resolved", "closed", "archived")),
                Ticket.deleted_at.is_(None),
            )
        ) or 0

        workload_score = min(round(active_tickets / 10 * 100), 100)  # 10 = 100% capacity
        rows.append({
            "agent_id": str(agent.id),
            "full_name": agent.full_name_ar,
            "full_name_en": agent.full_name_en or agent.full_name_ar,
            "is_online": agent.is_online,
            "active_tickets": active_tickets,
            "resolved_today": resolved_today,
            "sla_breaches": breaches,
            "workload_score": workload_score,
        })

    rows.sort(key=lambda r: -r["workload_score"])
    return rows


async def get_sla_violations(
    db: AsyncSession,
    dept_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> list[Ticket]:
    """Return tickets that have breached SLA and are still open."""
    from sqlalchemy.orm import selectinload

    q = (
        select(Ticket)
        .where(
            Ticket.sla_breached.is_(True),
            Ticket.status.notin_(("resolved", "closed", "archived")),
            Ticket.deleted_at.is_(None),
        )
        .options(selectinload(Ticket.assignee), selectinload(Ticket.category))
        .order_by(Ticket.sla_deadline)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Manager KPIs ──────────────────────────────────────────────────────────────

async def get_manager_kpis(
    db: AsyncSession,
    redis=None,
    period: str = "month",
) -> dict[str, Any]:
    cache_key = f"kpi:mgr:{period}:{date.today()}"
    if redis:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    start, end = _period_range(period)

    total_tickets    = await db.scalar(
        select(func.count(Ticket.id)).where(Ticket.created_at >= start, Ticket.created_at < end, Ticket.deleted_at.is_(None))
    ) or 0
    resolved_tickets = await db.scalar(
        select(func.count(Ticket.id)).where(Ticket.resolved_at >= start, Ticket.resolved_at < end, Ticket.deleted_at.is_(None))
    ) or 0
    open_tickets     = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.status.in_(("new", "open", "pending_customer", "pending_3rd")),
            Ticket.deleted_at.is_(None)
        )
    ) or 0
    sla_breached_period = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.sla_breached.is_(True),
            Ticket.created_at >= start, Ticket.created_at < end,
            Ticket.deleted_at.is_(None),
        )
    ) or 0
    resolved_on_time = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.resolved_at >= start, Ticket.resolved_at < end,
            Ticket.sla_breached.is_(False),
            Ticket.deleted_at.is_(None),
        )
    ) or 0
    avg_csat = await db.scalar(
        select(func.avg(cast(Ticket.csat_score, Float))).where(
            Ticket.csat_score.isnot(None),
            Ticket.resolved_at >= start, Ticket.resolved_at < end,
            Ticket.deleted_at.is_(None),
        )
    )
    avg_res_secs = await db.scalar(
        select(func.avg(Ticket.total_time_seconds)).where(
            Ticket.total_time_seconds > 0,
            Ticket.resolved_at >= start, Ticket.resolved_at < end,
            Ticket.deleted_at.is_(None),
        )
    )

    # Reopen rate: tickets that were reopened at least once
    reopened = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.reopen_count > 0,
            Ticket.created_at >= start, Ticket.created_at < end,
            Ticket.deleted_at.is_(None),
        )
    ) or 0

    # Channel breakdown
    chan_result = await db.execute(
        select(Ticket.channel, func.count(Ticket.id))
        .where(Ticket.created_at >= start, Ticket.created_at < end, Ticket.deleted_at.is_(None))
        .group_by(Ticket.channel)
    )
    channel_breakdown = {row[0]: row[1] for row in chan_result.fetchall()}

    # Priority breakdown
    prio_result = await db.execute(
        select(Ticket.priority, func.count(Ticket.id))
        .where(Ticket.created_at >= start, Ticket.created_at < end, Ticket.deleted_at.is_(None))
        .group_by(Ticket.priority)
    )
    priority_breakdown = {row[0]: row[1] for row in prio_result.fetchall()}

    # 7-day daily trend (always last 7 days regardless of period)
    trend_data: list[dict[str, Any]] = []
    for i in range(6, -1, -1):
        day_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
        day_end   = day_start + timedelta(days=1)
        created = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.created_at >= day_start, Ticket.created_at < day_end,
                Ticket.deleted_at.is_(None),
            )
        ) or 0
        resolved_day = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.resolved_at >= day_start, Ticket.resolved_at < day_end,
                Ticket.deleted_at.is_(None),
            )
        ) or 0
        trend_data.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "created": created,
            "resolved": resolved_day,
        })

    sla_compliance = round(resolved_on_time / max(resolved_tickets, 1) * 100, 1)
    fcr_pct  = 0.0  # placeholder (requires timeline join — too expensive here)
    reopen_pct = round(reopened / max(total_tickets, 1) * 100, 1)

    result_data = {
        "total_tickets":      total_tickets,
        "resolved_tickets":   resolved_tickets,
        "open_tickets":       open_tickets,
        "sla_breached":       sla_breached_period,
        "sla_compliance_pct": sla_compliance,
        "avg_csat":           round(float(avg_csat), 2) if avg_csat else None,
        "avg_resolution_mins": int((avg_res_secs or 0) / 60),
        "reopen_pct":         reopen_pct,
        "fcr_pct":            fcr_pct,
        "channel_breakdown":  channel_breakdown,
        "priority_breakdown": priority_breakdown,
        "trend":              trend_data,
    }

    if redis:
        await redis.setex(cache_key, 300, json.dumps(result_data))
    return result_data
