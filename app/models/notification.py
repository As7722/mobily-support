from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, Base):
    """In-app notification for authenticated users."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    body_ar: Mapped[Optional[str]] = mapped_column(Text)
    body_en: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id")
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    user: Mapped["User"] = relationship("User", back_populates="notifications")  # noqa: F821
    ticket: Mapped[Optional["Ticket"]] = relationship("Ticket", foreign_keys=[ticket_id])  # noqa: F821


class NotificationRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    target_roles: ['employee', 'supervisor']
    channels:     ['email', 'sms', 'in_app']
    """

    __tablename__ = "notification_rules"

    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    channels: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    template_key: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


__all__ = ["Notification", "NotificationRule"]
