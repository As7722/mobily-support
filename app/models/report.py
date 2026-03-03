from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class ScheduledReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Manager-configured automated reports sent via email on a cron schedule."""

    __tablename__ = "scheduled_reports"
    __table_args__ = (
        CheckConstraint(
            "frequency IN ('daily','weekly','monthly')",
            name="ck_scheduled_reports_frequency",
        ),
        CheckConstraint(
            "format IN ('pdf','csv','xlsx')",
            name="ck_scheduled_reports_format",
        ),
        CheckConstraint(
            "language IN ('ar','en')",
            name="ck_scheduled_reports_language",
        ),
    )

    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    report_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(100), nullable=False)
    recipients: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    format: Mapped[str] = mapped_column(String(10), default="pdf")
    language: Mapped[str] = mapped_column(String(5), default="ar")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


__all__ = ["ScheduledReport"]
