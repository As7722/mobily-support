from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AutomationRule(UUIDPrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, Base):
    """
    IF/AND/THEN automation engine.
    conditions = [{"field": "priority", "operator": "eq", "value": "critical"}]
    actions    = [{"type": "assign_to", "params": {"user_id": "..."}}]
    """

    __tablename__ = "automation_rules"

    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    priority_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    execution_count: Mapped[int] = mapped_column(Integer, default=0)
    last_executed: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    execution_logs: Mapped[list["AutomationExecutionLog"]] = relationship(
        "AutomationExecutionLog", back_populates="rule"
    )


class AutomationExecutionLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "automation_execution_log"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automation_rules.id"), nullable=False, index=True
    )
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    executed_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    rule: Mapped["AutomationRule"] = relationship("AutomationRule", back_populates="execution_logs")


__all__ = ["AutomationRule", "AutomationExecutionLog"]
