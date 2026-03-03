from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class SystemAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Live banner alerts shown at top of every page via SSE."""

    __tablename__ = "system_alerts"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','warning','critical')",
            name="ck_system_alerts_severity",
        ),
    )

    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    message_ar: Mapped[str] = mapped_column(Text, nullable=False)
    message_en: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    starts_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )
    ends_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class SystemStatus(UUIDPrimaryKeyMixin, Base):
    """Per-system operational status displayed on /status page."""

    __tablename__ = "system_statuses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('operational','degraded','partial_outage','major_outage')",
            name="ck_system_statuses_status",
        ),
    )

    system_name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    system_name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="operational", index=True)
    description_ar: Mapped[Optional[str]] = mapped_column(String(255))
    description_en: Mapped[Optional[str]] = mapped_column(String(255))
    eta_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    incidents: Mapped[list["Incident"]] = relationship("Incident", back_populates="system")


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Past incidents linked to a system — visible on /status history."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('investigating','identified','monitoring','resolved')",
            name="ck_incidents_status",
        ),
    )

    system_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("system_statuses.id"), index=True
    )
    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    description_ar: Mapped[Optional[str]] = mapped_column(Text)
    description_en: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="investigating", index=True)
    started_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))

    system: Mapped[Optional["SystemStatus"]] = relationship("SystemStatus", back_populates="incidents")


class ScheduledMaintenance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_maintenance"

    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    description_ar: Mapped[Optional[str]] = mapped_column(Text)
    description_en: Mapped[Optional[str]] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


__all__ = ["SystemAlert", "SystemStatus", "Incident", "ScheduledMaintenance"]
