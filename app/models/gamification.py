from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class GamificationBadge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    criteria: {"metric": "resolution_time_minutes", "operator": "<", "value": 30}
    """

    __tablename__ = "gamification_badges"

    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    description_ar: Mapped[Optional[str]] = mapped_column(Text)
    description_en: Mapped[Optional[str]] = mapped_column(Text)
    icon_emoji: Mapped[Optional[str]] = mapped_column(String(10))
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user_badges: Mapped[list["UserBadge"]] = relationship("UserBadge", back_populates="badge")


class UserBadge(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_badges"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    badge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gamification_badges.id"), nullable=False
    )
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id")
    )
    awarded_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )
    awarded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    user: Mapped["User"] = relationship("User", back_populates="badges", foreign_keys=[user_id])  # noqa: F821
    badge: Mapped["GamificationBadge"] = relationship("GamificationBadge", back_populates="user_badges")
    awarder: Mapped[Optional["User"]] = relationship("User", foreign_keys=[awarded_by])  # noqa: F821


class LeaderboardSnapshot(UUIDPrimaryKeyMixin, Base):
    """Daily/weekly/monthly performance snapshot per agent."""

    __tablename__ = "leaderboard_snapshots"
    __table_args__ = (
        CheckConstraint(
            "period_type IN ('daily','weekly','monthly','yearly')",
            name="ck_leaderboard_period_type",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    period_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tickets_resolved: Mapped[int] = mapped_column(Integer, default=0)
    avg_resolution_min: Mapped[float] = mapped_column(Float, default=0.0)
    csat_avg: Mapped[float] = mapped_column(Float, default=0.0)
    sla_compliance_pct: Mapped[float] = mapped_column(Float, default=0.0)
    fcr_pct: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class EmployeeOfMonth(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_of_month"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    month: Mapped[date] = mapped_column(Date, nullable=False, comment="First day of the month")
    is_auto_selected: Mapped[bool] = mapped_column(Boolean, default=True)
    announced_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


__all__ = ["GamificationBadge", "UserBadge", "LeaderboardSnapshot", "EmployeeOfMonth"]
