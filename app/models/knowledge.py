from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeArticle(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "knowledge_articles"

    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    content_ar: Mapped[str] = mapped_column(Text, nullable=False)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), index=True
    )
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    not_helpful_count: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    audience: Mapped[str] = mapped_column(String(20), default="internal", index=True)
    attachment_file_name: Mapped[Optional[str]] = mapped_column(String(255))
    attachment_storage_key: Mapped[Optional[str]] = mapped_column(String(500))
    attachment_mime_type: Mapped[Optional[str]] = mapped_column(String(120))
    attachment_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)

    category: Mapped[Optional["Category"]] = relationship("Category", foreign_keys=[category_id])  # noqa: F821
    author: Mapped[Optional["User"]] = relationship("User", foreign_keys=[author_id])  # noqa: F821


class CannedResponse(UUIDPrimaryKeyMixin, Base):
    """Quick-insert templates triggered by /shortcut in ticket reply box."""

    __tablename__ = "canned_responses"

    shortcut: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    content_ar: Mapped[str] = mapped_column(Text, nullable=False)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )


__all__ = ["KnowledgeArticle", "CannedResponse"]
