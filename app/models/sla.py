from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SLAPolicy(UUIDPrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, Base):
    """Defines SLA clock minutes per priority level."""

    __tablename__ = "sla_policies"

    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    clock_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    business_hours_only: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SLAPause(UUIDPrimaryKeyMixin, Base):
    """Records SLA pause/resume events per ticket."""

    __tablename__ = "sla_pauses"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paused_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    resumed_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(String(50))
    duration_s: Mapped[Optional[int]] = mapped_column(Integer)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="sla_pauses")  # noqa: F821


__all__ = ["SLAPolicy", "SLAPause"]
