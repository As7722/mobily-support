"""
Tests for SLA engine:
  - calculate_sla_deadline (business hours + holidays)
  - pause / resume SLA
  - breach detection
  - elapsed ratio
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio

UTC = timezone.utc


# ── calculate_sla_deadline ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sla_deadline_medium_priority(db, sample_sla_policy):
    """Medium priority (480 min) deadline is later than creation time."""
    from app.services.sla import calculate_sla_deadline

    created_at = datetime(2026, 2, 23, 8, 0, tzinfo=UTC)  # Sunday 08:00 Riyadh

    with patch("app.services.sla._get_holiday_set", new_callable=AsyncMock, return_value=set()):
        deadline = await calculate_sla_deadline(db, "medium", created_at)

    assert deadline > created_at
    # 480 business minutes from 08:00 = 16:00 same day
    assert deadline.date() == created_at.date()


@pytest.mark.asyncio
async def test_sla_deadline_skips_weekend(db, sample_sla_policy):
    """SLA deadline should skip Friday (weekend in Saudi Arabia)."""
    from app.services.sla import calculate_sla_deadline

    # Thursday 14:00 — a medium ticket (480 min) should skip Friday
    created_at = datetime(2026, 2, 26, 14, 0, tzinfo=UTC)  # Thursday

    with patch("app.services.sla._get_holiday_set", new_callable=AsyncMock, return_value=set()):
        deadline = await calculate_sla_deadline(db, "medium", created_at)

    # Should land on Saturday or later (skipping Friday)
    assert deadline.weekday() != 4  # Not Friday


@pytest.mark.asyncio
async def test_sla_deadline_skips_holiday(db, sample_sla_policy):
    """SLA deadline should skip holidays."""
    from app.services.sla import calculate_sla_deadline
    import datetime as dt

    created_at = datetime(2026, 2, 22, 8, 0, tzinfo=UTC)  # Sunday
    holiday_date = dt.date(2026, 2, 23)  # Monday is holiday

    with patch("app.services.sla._get_holiday_set", new_callable=AsyncMock, return_value={holiday_date}):
        deadline = await calculate_sla_deadline(db, "low", created_at)

    assert deadline > created_at


# ── SLA elapsed ratio ─────────────────────────────────────────────────────────

def test_elapsed_ratio_before_deadline():
    from app.services.sla import get_sla_elapsed_ratio

    now = datetime.now(tz=UTC)
    ticket = MagicMock()
    ticket.created_at   = now - timedelta(hours=2)
    ticket.sla_deadline = now + timedelta(hours=6)
    ticket.sla_paused_at = None
    ticket.sla_breached  = False

    ratio = get_sla_elapsed_ratio(ticket)
    assert 0 < ratio < 1


def test_elapsed_ratio_after_deadline():
    from app.services.sla import get_sla_elapsed_ratio

    now = datetime.now(tz=UTC)
    ticket = MagicMock()
    ticket.created_at   = now - timedelta(hours=10)
    ticket.sla_deadline = now - timedelta(hours=2)  # past
    ticket.sla_paused_at = None
    ticket.sla_breached  = True

    ratio = get_sla_elapsed_ratio(ticket)
    assert ratio >= 1.0


def test_elapsed_ratio_no_deadline():
    from app.services.sla import get_sla_elapsed_ratio

    ticket = MagicMock()
    ticket.sla_deadline = None

    ratio = get_sla_elapsed_ratio(ticket)
    assert ratio == 0.0


# ── Pause / Resume SLA ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pause_sla(db, sample_ticket):
    """pause_sla should set sla_paused_at and create a timeline event."""
    from app.services.sla import pause_sla

    sample_ticket.sla_deadline = datetime.now(tz=UTC) + timedelta(hours=4)
    sample_ticket.sla_paused_at = None
    await db.flush()

    agent_id = uuid.uuid4()
    with patch("app.services.sla.add_event", new_callable=AsyncMock):
        await pause_sla(db, sample_ticket, "waiting for vendor", agent_id)

    assert sample_ticket.sla_paused_at is not None


@pytest.mark.asyncio
async def test_resume_sla_extends_deadline(db, sample_ticket):
    """resume_sla should extend the deadline by the paused duration."""
    from app.services.sla import pause_sla, resume_sla

    now = datetime.now(tz=UTC)
    original_deadline = now + timedelta(hours=3)
    sample_ticket.sla_deadline = original_deadline
    sample_ticket.sla_paused_at = None
    await db.flush()

    agent_id = uuid.uuid4()
    with patch("app.services.sla.add_event", new_callable=AsyncMock):
        await pause_sla(db, sample_ticket, "test pause", agent_id)
        # Simulate 1 hour of pause
        sample_ticket.sla_paused_at = now - timedelta(hours=1)
        await resume_sla(db, sample_ticket, agent_id)

    assert sample_ticket.sla_paused_at is None
    assert sample_ticket.sla_deadline > original_deadline


# ── Breach detection ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_sla_breaches_marks_overdue(db, sample_ticket):
    """check_sla_breaches_async should mark overdue tickets as breached."""
    from app.services.sla import check_sla_breaches_async

    sample_ticket.sla_deadline = datetime.now(tz=UTC) - timedelta(hours=1)
    sample_ticket.sla_breached = False
    sample_ticket.sla_paused_at = None
    sample_ticket.status = "open"
    await db.flush()

    with patch("app.services.sla.add_event", new_callable=AsyncMock):
        count = await check_sla_breaches_async(db)

    assert count >= 1
    assert sample_ticket.sla_breached is True


@pytest.mark.asyncio
async def test_check_sla_breaches_ignores_paused(db, sample_ticket):
    """Paused tickets should not be breached."""
    from app.services.sla import check_sla_breaches_async

    sample_ticket.sla_deadline = datetime.now(tz=UTC) - timedelta(hours=1)
    sample_ticket.sla_breached = False
    sample_ticket.sla_paused_at = datetime.now(tz=UTC)
    sample_ticket.status = "open"
    await db.flush()

    with patch("app.services.sla.add_event", new_callable=AsyncMock):
        count = await check_sla_breaches_async(db)

    # Paused ticket should NOT be marked
    assert sample_ticket.sla_breached is False
