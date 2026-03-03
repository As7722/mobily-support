from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class TimeTracking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks time agents spend actively working on a ticket."""

    __tablename__ = "time_tracking"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    duration_s: Mapped[Optional[int]] = mapped_column(Integer)
    notes_ar: Mapped[Optional[str]] = mapped_column(Text)
    notes_en: Mapped[Optional[str]] = mapped_column(Text)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="time_trackings")  # noqa: F821
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class FollowUp(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Agent-scheduled reminder to follow up on a ticket."""

    __tablename__ = "follow_ups"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, index=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False, index=True)
    notes_ar: Mapped[Optional[str]] = mapped_column(Text)
    notes_en: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="follow_ups")  # noqa: F821
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])  # noqa: F821


__all__ = ["TimeTracking", "FollowUp"]
