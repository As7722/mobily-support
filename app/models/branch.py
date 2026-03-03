from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Branch(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "branches"

    name_ar: Mapped[str] = mapped_column(String(150), nullable=False)
    name_en: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    city_ar: Mapped[Optional[str]] = mapped_column(String(100))
    city_en: Mapped[Optional[str]] = mapped_column(String(100))
    region_ar: Mapped[Optional[str]] = mapped_column(String(100))
    region_en: Mapped[Optional[str]] = mapped_column(String(100))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    internal_notes: Mapped[Optional[str]] = mapped_column(Text)

    employees: Mapped[list["BranchEmployee"]] = relationship(  # noqa: F821
        "BranchEmployee", back_populates="branch"
    )
    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="branch")  # noqa: F821


class BranchEmployee(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Branch staff without a system account — can only submit portal tickets."""

    __tablename__ = "branch_employees"
    __table_args__ = (
        CheckConstraint(
            "preferred_language IN ('ar','en')",
            name="ck_branch_employees_lang",
        ),
    )

    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True
    )
    full_name_ar: Mapped[str] = mapped_column(String(150), nullable=False)
    full_name_en: Mapped[Optional[str]] = mapped_column(String(150))
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    position_ar: Mapped[Optional[str]] = mapped_column(String(100))
    position_en: Mapped[Optional[str]] = mapped_column(String(100))
    preferred_language: Mapped[str] = mapped_column(String(5), default="ar")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    branch: Mapped[Optional["Branch"]] = relationship("Branch", back_populates="employees")


__all__ = ["Branch", "BranchEmployee"]
