"""
Smart Queue Service
-------------------
Priority score formula (0-100):
  sla_ratio   × 40   — how much SLA time has elapsed (capped at 1.5×)
  priority_wt × 30   — critical=4, high=3, medium=2, low=1 (normalised/4)
  wait_ratio  × 20   — minutes waiting / 480 (one full business day), capped 1.0
  reopen_wt   × 10   — penalise reopened tickets (capped at 1 reopen)
Total max ≈ 100; higher = more urgent / should appear first.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticket import Ticket
from app.services.sla import get_sla_elapsed_ratio

UTC = timezone.utc
PRIORITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}
BUSINESS_DAY_MINUTES = 480  # 8 h


def _priority_score(ticket: Ticket, now: datetime) -> float:
    sla_ratio   = min(get_sla_elapsed_ratio(ticket), 1.5)
    prio_norm   = PRIORITY_WEIGHT.get(ticket.priority, 2) / 4
    created     = ticket.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    wait_ratio  = min((now - created).total_seconds() / 60 / BUSINESS_DAY_MINUTES, 1.0)
    reopen_wt   = min(ticket.reopen_count or 0, 1)

    return (sla_ratio * 40) + (prio_norm * 30) + (wait_ratio * 20) + (reopen_wt * 10)


async def _get_user_dept_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Get all department IDs a user is assigned to (via user_departments table)."""
    from app.models.department import UserDepartment
    result = await db.execute(
        select(UserDepartment.department_id).where(UserDepartment.user_id == user_id)
    )
    return [row[0] for row in result.all()]


async def get_smart_queue(
    db: AsyncSession,
    *,
    user_id: Optional[uuid.UUID] = None,
    role: str = "employee",
    dept_id: Optional[uuid.UUID] = None,
    page: int = 1,
    per_page: int = 25,
    assigned_filter: Optional[str] = None,
    queue_filter: Optional[str] = None,
    filter_agent_id: Optional[uuid.UUID] = None,
    filter_dept_id: Optional[uuid.UUID] = None,
) -> dict:
    """
    Return paginated, priority-scored ticket list.

    Iron Rule #4 — queue_filter segregation:
      "main"        → current_queue='main', visible to all
      "specialized" → current_queue='specialized', filtered by dept_id
      "supervisor"  → current_queue='supervisor', supervisor+ only
      "manager"     → current_queue='manager', manager+ only
      None          → all queues (legacy behaviour, filtered by role)
    """
    ACTIVE_STATUSES = ("new", "open", "pending_customer", "pending_3rd")

    q = (
        select(Ticket)
        .where(Ticket.status.in_(ACTIVE_STATUSES), Ticket.deleted_at.is_(None))
        .options(selectinload(Ticket.assignee), selectinload(Ticket.category))
    )

    # Get all departments for this user (many-to-many)
    user_dept_ids: list[uuid.UUID] = []
    if user_id and role == "employee":
        user_dept_ids = await _get_user_dept_ids(db, user_id)

    # Segregated queue filter (Iron Rule #4)
    if queue_filter:
        q = q.where(Ticket.current_queue == queue_filter)
        if queue_filter == "main":
            q = q.where(Ticket.assigned_to.is_(None))
        elif queue_filter == "specialized":
            if filter_dept_id:
                q = q.where(Ticket.sub_queue_dept_id == filter_dept_id)
            elif role == "employee" and user_dept_ids:
                q = q.where(Ticket.sub_queue_dept_id.in_(user_dept_ids))
            elif role == "employee" and dept_id:
                q = q.where(Ticket.sub_queue_dept_id == dept_id)
        elif queue_filter == "internal_tickets":
            if role == "employee" and user_id:
                q = q.where(Ticket.assigned_to == user_id)
    else:
        if role == "employee" and user_id:
            conditions = [Ticket.assigned_to == user_id, Ticket.assigned_to.is_(None)]
            if user_dept_ids:
                conditions.append(
                    and_(Ticket.current_queue == "specialized", Ticket.sub_queue_dept_id.in_(user_dept_ids))
                )
            elif dept_id:
                conditions.append(
                    and_(Ticket.current_queue == "specialized", Ticket.sub_queue_dept_id == dept_id)
                )
            q = q.where(or_(*conditions))
        elif role == "supervisor":
            q = q.where(Ticket.current_queue.in_(("main", "specialized", "supervisor")))

    if assigned_filter == "mine" and user_id:
        q = q.where(Ticket.assigned_to == user_id)
    elif assigned_filter == "unassigned":
        q = q.where(Ticket.assigned_to.is_(None))

    if filter_agent_id:
        q = q.where(Ticket.assigned_to == filter_agent_id)
    if filter_dept_id:
        q = q.where(Ticket.sub_queue_dept_id == filter_dept_id)

    result = await db.execute(q)
    tickets: list[Ticket] = list(result.scalars().all())

    now = datetime.now(tz=UTC)
    scored = sorted(tickets, key=lambda t: -_priority_score(t, now))

    total   = len(scored)
    start   = (page - 1) * per_page
    page_items = scored[start : start + per_page]

    return {
        "tickets": page_items,
        "scores": {str(t.id): round(_priority_score(t, now), 1) for t in page_items},
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


async def claim_ticket(
    db: AsyncSession,
    ticket_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> Ticket:
    """Assign a ticket to the claiming agent atomically."""
    from datetime import datetime, timezone
    from app.services.timeline import add_event, EventType

    result = await db.execute(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.deleted_at.is_(None),
            Ticket.assigned_to.is_(None),  # only claim if unassigned
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        result2 = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result2.scalar_one_or_none()
        if ticket and ticket.assigned_to == agent_id:
            return ticket
        raise ValueError("ticket_not_claimable")

    now = datetime.now(tz=UTC)
    ticket.assigned_to = agent_id
    ticket.assigned_at  = now
    ticket.updated_at   = now
    if ticket.status == "new":
        ticket.status = "open"
        ticket.last_opened_at = now

    await add_event(
        db,
        ticket_id=ticket.id,
        event_type=EventType.ASSIGNED,
        content_ar="تم الاستلام من الطابور",
        content_en="Claimed from queue",
        actor_id=agent_id,
        actor_type="agent",
        is_public=False,
    )
    await db.flush()
    return ticket


async def auto_balance(
    db: AsyncSession,
    dept_id: Optional[uuid.UUID],
    supervisor_id: uuid.UUID,
) -> int:
    """
    Redistribute unassigned tickets among online agents by ascending workload.
    Returns count of tickets reassigned.
    """
    from sqlalchemy import func
    from app.models.user import User

    # Online agents in dept
    agents_q = select(User).where(
        User.is_active.is_(True),
        User.is_online.is_(True),
        User.role == "employee",
        User.deleted_at.is_(None),
    )
    if dept_id:
        agents_q = agents_q.where(User.department_id == dept_id)

    agents_result = await db.execute(agents_q)
    agents = list(agents_result.scalars().all())
    if not agents:
        return 0

    # Workload per agent
    wl_result = await db.execute(
        select(Ticket.assigned_to, func.count(Ticket.id).label("cnt"))
        .where(
            Ticket.status.in_(("new", "open", "pending_customer")),
            Ticket.deleted_at.is_(None),
            Ticket.assigned_to.in_([a.id for a in agents]),
        )
        .group_by(Ticket.assigned_to)
    )
    workloads: dict[uuid.UUID, int] = {row[0]: row[1] for row in wl_result.fetchall()}
    agents.sort(key=lambda a: workloads.get(a.id, 0))

    # Unassigned tickets
    unassigned_result = await db.execute(
        select(Ticket)
        .where(
            Ticket.assigned_to.is_(None),
            Ticket.status == "new",
            Ticket.deleted_at.is_(None),
        )
        .order_by(Ticket.created_at)
    )
    unassigned = list(unassigned_result.scalars().all())

    from app.services.timeline import add_event, EventType
    now = datetime.now(tz=UTC)
    count = 0
    for i, ticket in enumerate(unassigned):
        agent = agents[i % len(agents)]
        ticket.assigned_to   = agent.id
        ticket.assigned_at   = now
        ticket.status        = "open"
        ticket.last_opened_at = now
        ticket.updated_at    = now
        await add_event(
            db,
            ticket_id=ticket.id,
            event_type=EventType.ASSIGNED,
            content_ar=f"تم التوزيع التلقائي — {agent.full_name_ar}",
            content_en=f"Auto-balanced — {agent.full_name_en or agent.full_name_ar}",
            actor_id=supervisor_id,
            actor_type="agent",
            is_public=False,
        )
        count += 1

    await db.flush()
    return count
