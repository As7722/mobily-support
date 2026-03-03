from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FormVersion(UUIDPrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, Base):
    """No-code form builder — each publish creates a new immutable version."""

    __tablename__ = "form_versions"

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    fields: Mapped[list["FormFieldDefinition"]] = relationship(
        "FormFieldDefinition", back_populates="form_version"
    )


class FormFieldDefinition(UUIDPrimaryKeyMixin, Base):
    """
    Individual field in a form version.
    conditional_logic: {"show_if": {"field": "category_id", "equals": "uuid"}}
    options: [{"value": "uuid", "label_ar": "شبكة", "label_en": "Network"}]
    """

    __tablename__ = "form_field_definitions"

    form_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_versions.id"), nullable=False, index=True
    )
    field_type: Mapped[str] = mapped_column(String(30), nullable=False)
    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    label_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    label_en: Mapped[str] = mapped_column(String(200), nullable=False)
    placeholder_ar: Mapped[Optional[str]] = mapped_column(String(200))
    placeholder_en: Mapped[Optional[str]] = mapped_column(String(200))
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    validation_rules: Mapped[Optional[dict]] = mapped_column(JSONB)
    conditional_logic: Mapped[Optional[dict]] = mapped_column(JSONB)
    options: Mapped[Optional[dict]] = mapped_column(JSONB)

    form_version: Mapped["FormVersion"] = relationship("FormVersion", back_populates="fields")


__all__ = ["FormVersion", "FormFieldDefinition"]
