from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class CallLog(UUIDPrimaryKeyMixin, Base):
    """
    Records inbound/outbound calls made by agents.
    Accessible via Ctrl+K drawer on the agent dashboard.
    """

    __tablename__ = "call_logs"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    branch_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branch_employees.id")
    )
    caller_phone: Mapped[Optional[str]] = mapped_column(String(20))
    caller_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    reason_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id")
    )
    outcome: Mapped[Optional[str]] = mapped_column(String(30))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), index=True
    )

    agent: Mapped["User"] = relationship("User", foreign_keys=[agent_id])  # noqa: F821
    caller_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[caller_user_id])  # noqa: F821
    branch_employee: Mapped[Optional["BranchEmployee"]] = relationship("BranchEmployee", foreign_keys=[branch_employee_id])  # noqa: F821
    category: Mapped[Optional["Category"]] = relationship("Category", foreign_keys=[category_id])  # noqa: F821
    ticket: Mapped[Optional["Ticket"]] = relationship("Ticket", foreign_keys=[ticket_id])  # noqa: F821


__all__ = ["CallLog"]
