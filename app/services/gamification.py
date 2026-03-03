"""
Gamification Engine
===================
Badges are awarded after ticket resolution if the agent meets the criteria.

Anti-gaming rules:
  1. Minimum 5 minutes handle time (total_time_seconds >= 300).
  2. CSAT gate: score >= 4.0 for CSAT-gated badges.
  3. Supervisor review flag: if ticket was escalated → badge withheld until supervisor approves.
  4. No badge awarded for tickets the agent escalated away.

Badge definitions (evaluated in order after each resolution):
  - speed_resolver : resolved in < 30 min, CSAT >= 4
  - top_resolver   : resolved 10+ tickets this month
  - sla_hero       : 100% SLA compliance this month (min 10 tickets)
  - csat_star      : avg CSAT >= 4.5 this month (min 5 CSAT responses)
  - comeback_kid   : resolved a reopened ticket
  - marathon       : resolved 5+ tickets in one day

Leaderboard snapshots: Celery Beat → daily, weekly, monthly.
Employee of Month: computed on the 1st of each month via Celery Beat.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket

log = logging.getLogger(__name__)
UTC = timezone.utc


# ── Badge definitions ─────────────────────────────────────────────────────────

BADGE_DEFS: dict[str, dict] = {
    "speed_resolver": {
        "name_ar": "مُحلِّل سريع",
        "name_en": "Speed Resolver",
        "icon":    "⚡",
        "description_ar": "حل تذكرة في أقل من 30 دقيقة بتقييم ≥ 4",
        "description_en": "Resolved a ticket in < 30 min with CSAT ≥ 4",
    },
    "top_resolver": {
        "name_ar": "أفضل محلِّل",
        "name_en": "Top Resolver",
        "icon":    "🏆",
        "description_ar": "حل 10 تذاكر أو أكثر هذا الشهر",
        "description_en": "Resolved 10+ tickets this month",
    },
    "sla_hero": {
        "name_ar": "بطل SLA",
        "name_en": "SLA Hero",
        "icon":    "🛡️",
        "description_ar": "100% التزام بـ SLA هذا الشهر (10 تذاكر على الأقل)",
        "description_en": "100% SLA compliance this month (min 10 tickets)",
    },
    "csat_star": {
        "name_ar": "نجم التقييم",
        "name_en": "CSAT Star",
        "icon":    "⭐",
        "description_ar": "متوسط تقييم ≥ 4.5 هذا الشهر (5 تقييمات على الأقل)",
        "description_en": "Avg CSAT ≥ 4.5 this month (min 5 ratings)",
    },
    "comeback_kid": {
        "name_ar": "العودة القوية",
        "name_en": "Comeback Kid",
        "icon":    "🔄",
        "description_ar": "حل تذكرة معادة فتحها",
        "description_en": "Resolved a reopened ticket",
    },
    "marathon": {
        "name_ar": "الماراثون",
        "name_en": "Marathon",
        "icon":    "🏃",
        "description_ar": "حل 5 تذاكر أو أكثر في يوم واحد",
        "description_en": "Resolved 5+ tickets in a single day",
    },
}


# ── Badge award logic ─────────────────────────────────────────────────────────

async def _already_has_badge(
    db: AsyncSession,
    agent_id: uuid.UUID,
    badge_key: str,
    period_start: datetime,
) -> bool:
    """Check if agent already earned this badge in the current period."""
    from app.models.gamification import UserBadge, GamificationBadge

    result = await db.execute(
        select(UserBadge)
        .join(GamificationBadge, UserBadge.badge_id == GamificationBadge.id)
        .where(
            UserBadge.user_id == agent_id,
            GamificationBadge.key == badge_key,
            UserBadge.awarded_at >= period_start,
        )
    )
    return result.scalar_one_or_none() is not None


async def _award_badge(
    db: AsyncSession,
    agent_id: uuid.UUID,
    badge_key: str,
    ticket_id: Optional[uuid.UUID] = None,
) -> bool:
    """Award a badge. Returns True if newly awarded."""
    from app.models.gamification import UserBadge, GamificationBadge

    result = await db.execute(
        select(GamificationBadge).where(GamificationBadge.key == badge_key)
    )
    badge = result.scalar_one_or_none()
    if not badge:
        log.warning("Badge key %s not in DB — skipping award", badge_key)
        return False

    ub = UserBadge(
        id=uuid.uuid4(),
        user_id=agent_id,
        badge_id=badge.id,
        ticket_id=ticket_id,
        awarded_at=datetime.now(tz=UTC),
        is_pending_review=False,
    )
    db.add(ub)
    log.info("Badge '%s' awarded to agent %s", badge_key, agent_id)
    return True


async def check_and_award_badges(
    db: AsyncSession,
    agent_id: uuid.UUID,
    ticket: Ticket,
) -> list[str]:
    """
    Run all badge checks after a ticket is resolved.
    Returns list of badge keys that were newly awarded.
    """
    now = datetime.now(tz=UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    awarded: list[str] = []

    # Anti-gaming: minimum handle time
    if not ticket.total_time_seconds or ticket.total_time_seconds < 300:
        log.debug("Ticket %s below min handle time — no badges", ticket.ticket_number)
        return []

    # Anti-gaming: escalated tickets don't earn badges (for the escalating agent)
    if ticket.current_queue == "supervisor":
        log.debug("Ticket %s was escalated — badges withheld", ticket.ticket_number)
        return []

    # ── speed_resolver ─────────────────────────────────────────────────────
    if (
        ticket.total_time_seconds < 1800  # < 30 min
        and ticket.csat_score and float(ticket.csat_score) >= 4.0
        and not await _already_has_badge(db, agent_id, "speed_resolver", today_start)
    ):
        async with db.begin_nested():
            if await _award_badge(db, agent_id, "speed_resolver", ticket.id):
                awarded.append("speed_resolver")

    # ── top_resolver ────────────────────────────────────────────────────────
    resolved_month = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == agent_id,
            Ticket.resolved_at >= month_start,
            Ticket.status.in_(("resolved", "closed")),
        )
    ) or 0
    if (
        resolved_month >= 10
        and not await _already_has_badge(db, agent_id, "top_resolver", month_start)
    ):
        async with db.begin_nested():
            if await _award_badge(db, agent_id, "top_resolver", ticket.id):
                awarded.append("top_resolver")

    # ── sla_hero ────────────────────────────────────────────────────────────
    if resolved_month >= 10:
        breached_month = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent_id,
                Ticket.resolved_at >= month_start,
                Ticket.sla_breached.is_(True),
            )
        ) or 0
        if (
            breached_month == 0
            and not await _already_has_badge(db, agent_id, "sla_hero", month_start)
        ):
            async with db.begin_nested():
                if await _award_badge(db, agent_id, "sla_hero", ticket.id):
                    awarded.append("sla_hero")

    # ── csat_star ────────────────────────────────────────────────────────────
    from sqlalchemy import Float, cast

    avg_csat = await db.scalar(
        select(func.avg(cast(Ticket.csat_score, Float))).where(
            Ticket.assigned_to == agent_id,
            Ticket.resolved_at >= month_start,
            Ticket.csat_score.isnot(None),
        )
    )
    csat_count = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == agent_id,
            Ticket.resolved_at >= month_start,
            Ticket.csat_score.isnot(None),
        )
    ) or 0
    if (
        avg_csat and float(avg_csat) >= 4.5
        and csat_count >= 5
        and not await _already_has_badge(db, agent_id, "csat_star", month_start)
    ):
        async with db.begin_nested():
            if await _award_badge(db, agent_id, "csat_star", ticket.id):
                awarded.append("csat_star")

    # ── comeback_kid ─────────────────────────────────────────────────────────
    if (ticket.reopen_count or 0) > 0 and not await _already_has_badge(db, agent_id, "comeback_kid", month_start):
        async with db.begin_nested():
            if await _award_badge(db, agent_id, "comeback_kid", ticket.id):
                awarded.append("comeback_kid")

    # ── marathon ─────────────────────────────────────────────────────────────
    resolved_today = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_to == agent_id,
            Ticket.resolved_at >= today_start,
            Ticket.status.in_(("resolved", "closed")),
        )
    ) or 0
    if (
        resolved_today >= 5
        and not await _already_has_badge(db, agent_id, "marathon", today_start)
    ):
        async with db.begin_nested():
            if await _award_badge(db, agent_id, "marathon", ticket.id):
                awarded.append("marathon")

    return awarded


# ── Leaderboard snapshot ──────────────────────────────────────────────────────

async def build_leaderboard_snapshot(
    db: AsyncSession,
    period: str,  # "daily" | "weekly" | "monthly"
) -> None:
    """
    Compute leaderboard rankings and persist to leaderboard_snapshots table.
    Called by Celery Beat.
    """
    from app.models.gamification import LeaderboardSnapshot
    from app.models.user import User
    from sqlalchemy import Float, cast

    now = datetime.now(tz=UTC)
    today = now.date()

    if period == "daily":
        start = datetime(today.year, today.month, today.day, tzinfo=UTC)
        end   = start + timedelta(days=1)
    elif period == "weekly":
        start = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=today.weekday())
        end   = start + timedelta(weeks=1)
    else:  # monthly
        start = datetime(today.year, today.month, 1, tzinfo=UTC)
        m     = today.month % 12 + 1
        y     = today.year + (1 if today.month == 12 else 0)
        end   = datetime(y, m, 1, tzinfo=UTC)

    agents_result = await db.execute(
        select(User).where(User.role == "employee", User.is_active.is_(True), User.deleted_at.is_(None))
    )
    agents = list(agents_result.scalars().all())

    rows: list[tuple[uuid.UUID, int, float]] = []  # (agent_id, resolved_count, avg_csat)
    for agent in agents:
        resolved = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent.id,
                Ticket.resolved_at >= start,
                Ticket.resolved_at < end,
            )
        ) or 0
        avg = await db.scalar(
            select(func.avg(cast(Ticket.csat_score, Float))).where(
                Ticket.assigned_to == agent.id,
                Ticket.resolved_at >= start,
                Ticket.resolved_at < end,
                Ticket.csat_score.isnot(None),
            )
        )
        rows.append((agent.id, resolved, float(avg) if avg else 0.0))

    rows.sort(key=lambda x: (-x[1], -x[2]))

    for rank, (agent_id, resolved, avg_csat) in enumerate(rows, start=1):
        snap = LeaderboardSnapshot(
            id=uuid.uuid4(),
            period=period,
            period_start=start,
            agent_id=agent_id,
            rank=rank,
            resolved_count=resolved,
            avg_csat=avg_csat,
            created_at=now,
        )
        db.add(snap)

    log.info("Leaderboard snapshot saved: period=%s, agents=%d", period, len(rows))


# ── Employee of the Month ─────────────────────────────────────────────────────

async def compute_employee_of_month(db: AsyncSession) -> Optional[uuid.UUID]:
    """
    Compute Employee of the Month on the 1st of each month.
    Scoring: resolved_count*10 + avg_csat*20 - sla_breaches*5.
    Returns the winning agent_id.
    """
    from sqlalchemy import Float, cast

    now   = datetime.now(tz=UTC)
    prev  = (now.replace(day=1) - timedelta(days=1))
    start = datetime(prev.year, prev.month, 1, tzinfo=UTC)
    end   = datetime(now.year, now.month, 1, tzinfo=UTC)

    from app.models.user import User

    agents_result = await db.execute(
        select(User).where(User.role == "employee", User.is_active.is_(True), User.deleted_at.is_(None))
    )
    agents = list(agents_result.scalars().all())

    best_score  = -1.0
    best_agent: Optional[uuid.UUID] = None

    for agent in agents:
        resolved = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent.id,
                Ticket.resolved_at >= start,
                Ticket.resolved_at < end,
            )
        ) or 0
        avg = await db.scalar(
            select(func.avg(cast(Ticket.csat_score, Float))).where(
                Ticket.assigned_to == agent.id,
                Ticket.resolved_at >= start,
                Ticket.resolved_at < end,
                Ticket.csat_score.isnot(None),
            )
        )
        breaches = await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_to == agent.id,
                Ticket.resolved_at >= start,
                Ticket.resolved_at < end,
                Ticket.sla_breached.is_(True),
            )
        ) or 0
        score = resolved * 10 + (float(avg) if avg else 0) * 20 - breaches * 5
        if score > best_score:
            best_score = score
            best_agent = agent.id

    if best_agent:
        log.info("Employee of the Month: agent_id=%s (score=%.1f)", best_agent, best_score)
    return best_agent
