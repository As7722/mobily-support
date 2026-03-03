from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Department(UUIDPrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "departments"

    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    portal_fields: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="department", foreign_keys="User.department_id")  # noqa: F821
    categories: Mapped[list["Category"]] = relationship("Category", back_populates="department")  # noqa: F821
    user_departments: Mapped[list["UserDepartment"]] = relationship("UserDepartment", back_populates="department")


class UserDepartment(Base):
    """Many-to-many: a user can belong to multiple departments."""
    __tablename__ = "user_departments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
    department: Mapped["Department"] = relationship("Department", back_populates="user_departments")


__all__ = ["Department", "UserDepartment"]
