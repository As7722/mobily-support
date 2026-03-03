from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class AgentSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Weekly schedule per agent.
    schedule: {"sunday": {"start": "08:00", "end": "16:00"}, "monday": "OFF", ...}
    """

    __tablename__ = "agent_schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_agent_schedules_user_week"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    schedule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class ShiftSwap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shift_swaps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_shift_swaps_status",
        ),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    requested_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    swap_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    requester: Mapped["User"] = relationship("User", foreign_keys=[requester_id])  # noqa: F821
    requested: Mapped["User"] = relationship("User", foreign_keys=[requested_id])  # noqa: F821
    approver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by])  # noqa: F821


class LeaveRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_leave_requests_status",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason_ar: Mapped[Optional[str]] = mapped_column(Text)
    reason_en: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
    approver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by])  # noqa: F821


class Holiday(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Official Saudi holidays that pause SLA clock."""

    __tablename__ = "holidays"

    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)


__all__ = ["AgentSchedule", "ShiftSwap", "LeaveRequest", "Holiday"]
