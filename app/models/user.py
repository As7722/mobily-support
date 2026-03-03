from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('employee','supervisor','manager','admin')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "preferred_language IN ('ar','en')",
            name="ck_users_preferred_language",
        ),
    )

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    full_name_ar: Mapped[str] = mapped_column(String(150), nullable=False)
    full_name_en: Mapped[Optional[str]] = mapped_column(String(150))
    employee_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id")
    )
    preferred_language: Mapped[str] = mapped_column(String(5), default="ar")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(100))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    backup_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    dark_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_email_assign: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_sms_sla: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email_daily: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    department: Mapped[Optional["Department"]] = relationship(  # noqa: F821
        "Department", back_populates="users", foreign_keys=[department_id]
    )
    backup_agent: Mapped[Optional["User"]] = relationship(
        "User", remote_side="User.id", foreign_keys=[backup_agent_id]
    )
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user")  # noqa: F821
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="user")  # noqa: F821
    badges: Mapped[list["UserBadge"]] = relationship("UserBadge", back_populates="user", foreign_keys="UserBadge.user_id")  # noqa: F821


__all__ = ["User"]
